import subprocess
from re import U
from unicodedata import name
import clang.cindex
from clang.cindex import CursorKind, TypeKind
import argparse
import pathlib
import os
from typing import Iterable

BLACKLIST = set([
    'CreateContext',
    'DestroyContext',
    'GetCurrentContext',
    'SetCurrentContext',
    'AddContextHook',
    'RemoveContextHook',
    'CallContextHooks'
    'CreateListClipper',
    'CreateTextFilter'
])

CLASS_WITH_CONTEXT = set([
    'ImGuiIO',
    'ImGuiWindow',
    'ImGuiTextFilter',
    'ImGuiListClipper',
    'ImGuiInputTextCallbackData',
    'ImGuiInputTextState',
])

SPECIAL_TEMPLATE_FUNC = set([
    'ScaleRatioFromValueT',
    'ScaleValueFromRatioT',
    'DragBehaviorT',
    'SliderBehaviorT',
    'RoundScalarWithFormatT',
    'CheckboxFlagsT',
])

class CodeRange:
    def __init__(self, file, start_line, start_column, end_line, end_column):
        if isinstance(file, str):
            file = pathlib.Path(file)

        self.file = file
        self.start_line = start_line
        self.start_column = start_column
        self.end_line = end_line
        self.end_column = end_column


    def copy(self):
        return CodeRange(self.file, self.start_line, self.start_column, self.end_line, self.end_column)

    def __key(self):
        return (self.file, self.start_line, self.start_column)

    def __hash__(self):
        return hash(self.__key())

    def __eq__(self, other):
        if isinstance(other, FunctionEntry):
            return self.__key() == other.__key()
        return NotImplemented
    def __str__(self):
        assert self.start_line == self.end_line
        return '{}:{}:{}-{}'.format(self.file, self.start_line, self.start_column, self.end_column)

    @staticmethod
    def from_source_range(source_range: clang.cindex.SourceRange):
        start : clang.cindex.SourceLocation = source_range.start
        end : clang.cindex.SourceLocation = source_range.end

        start_file = pathlib.Path(str(start.file))
        end_file = pathlib.Path(str(end.file))
        assert start_file == end_file, "start file ({}) and end of file ({}) does not match".format(start.file, end.file)

        return CodeRange(start_file, start.line, start.column, end.line, end.column)

    @staticmethod
    def from_source_location(source_location: clang.cindex.SourceLocation, offset: int):
        file = pathlib.Path(str(source_location.file))

        return CodeRange(file, source_location.line, source_location.column, source_location.line, source_location.column + offset)

class Config:
    def __init__(self, root_folder):
        self.root_folder = pathlib.Path(root_folder).resolve()
        self.imgui_h = self.root_folder / 'imgui.h'
        self.imstb_textedit = self.root_folder / 'imstb_textedit.h'
        self.imgui_internal_h = self.root_folder / 'imgui_internal.h'
        self.imgui_cpp = self.root_folder / 'imgui.cpp'
        self.imgui_tables = self.root_folder / 'imgui_tables.cpp'
        self.imgui_widgets = self.root_folder / 'imgui_widgets.cpp'
        self.imgui_draw = self.root_folder / 'imgui_draw.cpp'
        self.imgui_demo = self.root_folder / 'imgui_demo.cpp'
        self.imguiex_h = self.root_folder / 'imguiex.h'
        self.imgui_implicit = self.root_folder / 'imgui_implicit.cpp'
        self.tmp = self.root_folder / 'tmp.cpp'
        self.this_script = pathlib.Path(__file__).resolve()
        self.script_root = self.this_script.parent.resolve()
        self.test_cpp =  self.script_root / 'test/test.cpp'
        self.imgui_sources = set([
            self.imgui_h,
            self.imgui_internal_h,
            self.imgui_cpp,
            self.imgui_tables,
            self.imgui_widgets,
            self.imgui_draw,
            self.imgui_demo,
            self.imstb_textedit
        ])

    def is_valid_func(self, cursor):
        return cursor is not None \
            and pathlib.Path(str(cursor.location.file)) in self.imgui_sources \
            and cursor.spelling not in BLACKLIST \
            and get_id(cursor) is not None


class TransformStrRequest:
    """
        start and end are expressed in index, not in column
    """
    def __init__(self, start : int, end : int, before: str, after: str):
        self.start = start
        self.end = end
        assert self.end - self.start == len(before)
        self.before = before
        self.after = after

class SourceLine:
    def __init__(self, line: str):
        self.line : str = line
        self.replace_context : TransformStrRequest = None
        self.transform_call : list[TransformStrRequest] = list()
        self.transform_proto : TransformStrRequest = None
        self.other_request : list[TransformStrRequest]  = list()
        self.delete = False

    def request_replace_context(self, implicit_context : CodeRange):
        assert self.replace_context is None
        self.replace_context = TransformStrRequest(implicit_context.start_column - 1, implicit_context.end_column - 1, 'GImGui', 'ctx')

    def request_replace(self, req : TransformStrRequest):
        self.other_request.append(req)

    def request_replace_proto(self, code_range: CodeRange, name: str, has_arg: bool):
        assert self.transform_proto is None
        arg = 'ImGuiContext* ctx' + (', ' if has_arg > 0 else '')
        self.transform_proto = TransformStrRequest(code_range.start_column - 1, code_range.end_column , name + '(', name + '(' + arg)

    def request_replace_call(self, var_name: str, code_range: CodeRange, name: str, has_arg):
        arg = var_name + (', ' if has_arg > 0 else '')
        request = TransformStrRequest(code_range.start_column - 1, code_range.end_column, name + '(', name + '(' + arg)
        self.transform_call.append(request)

    def transform(self):
        requests : list[TransformStrRequest] = list()
        if self.replace_context is not None:
            requests.append(self.replace_context)
        
        if self.transform_proto is not None:
            requests.append(self.transform_proto)

        requests += self.transform_call
        requests += self.other_request

        requests.sort(key = lambda x: x.start)

        new_line = str()
        next_char_index = 0
        for req in requests:
            while next_char_index < req.start:
                new_line += self.line[next_char_index]
                next_char_index += 1
            new_line += req.after
            next_char_index += len(req.before)

        while next_char_index < len(self.line):
            new_line += self.line[next_char_index]
            next_char_index += 1

        self.line = new_line

    @staticmethod
    def test():
        source = SourceLine('inline MyFunc(int a, float val = 0.f) { ImGuiContext& g = *GImGui; Foo(28); SuperBar(); Foo(29);')
        source.request_replace_context(CodeRange('', 1, 60, 1, 66))
        source.request_replace_proto(CodeRange('', 1, 8, 1, 14), 'MyFunc', 2)
        source.request_replace_call('ctx', CodeRange('', 1, 68, 1, 71), 'Foo', 1)
        source.request_replace_call('ctx', CodeRange('', 1, 77, 1, 85), 'SuperBar', 0)
        source.request_replace_call('ctx', CodeRange('', 1, 89, 1, 92), 'Foo', 1)
        source.transform()
        assert source.line == 'inline MyFunc(ImGuiContext* ctx, int a, float val = 0.f) { ImGuiContext& g = *ctx; Foo(ctx, 28); SuperBar(ctx); Foo(ctx, 29);', 'Source test failed'


class ParsingContext:
    def __init__(self, tu: clang.cindex.TranslationUnit, config: Config):
        self.tu = tu
        self._sources : dict[pathlib.Path, list[SourceLine]] = dict()
        self.output_sources : set[pathlib.Path] = set()
        self.config = config
        for source in config.imgui_sources:
            self._add_source(source)

        for source in config.imgui_sources:
            self.output_sources.add(source)

        self._log_symbols = [
            'IMGUI_DEBUG_LOG',
            'IMGUI_DEBUG_LOG_ACTIVEID',
            'IMGUI_DEBUG_LOG_FOCUS',
            'IMGUI_DEBUG_LOG_POPUP',
            'IMGUI_DEBUG_LOG_NAV',
            'IMGUI_DEBUG_LOG_CLIPPER',
            'IMGUI_DEBUG_LOG_IO',
            'IMGUI_DEBUG_LOG_DOCKING',
            'IMGUI_DEBUG_LOG_VIEWPORT'
        ]

    def _add_source(self, path):
        if not isinstance(path, pathlib.Path):
            path = pathlib.Path(path)

        lines = []
        with open(path) as file:
            lines += list(file)
        self._sources[path] = [SourceLine(line) for line in lines]

    def get_line(self, path, line):
        if isinstance(path, str):
            path = pathlib.Path(str(path))

        assert path in self._sources
        return self._sources[path][line - 1].line

    def find_until(self, path, line_num : int, column_num : int,  search_char : str) -> CodeRange:
        """
            Find a string `symbol` in a line and return a CodeRange. Start search at `column_num`
        """
        if not isinstance(path, pathlib.Path):
            path = pathlib.Path(str(path))

        line = self.get_line(path, line_num)
        for i in range(column_num - 1, len(line)):
            if line[i] == search_char:
                return CodeRange(path, line_num, column_num, line_num, i + 2) # +1 to include to searched char, +1 for index to column

        return None

    def find_symbol(self, path, line_num : int, column_num : int,  symbol : str) -> CodeRange:
        """
            Find a string `symbol` in a line and return a CodeRange. Start search at `column_num`
        """
        if not isinstance(path, pathlib.Path):
            path = pathlib.Path(str(path))

        line = self.get_line(path, line_num)
        offset = line.find(symbol, column_num - 1) + 1
        if offset > 0:
            lenght = len(symbol)
            return CodeRange(path, line_num, offset, line_num, offset + lenght)
        else:
            return None

    def find_log_symbol(self, location: clang.cindex.SourceLocation) -> CodeRange:
        for symbol in self._log_symbols:
            code_range = self.find_symbol(location.file, location.line, location.column, symbol + '(')
            if code_range is not None:
                code_range.end_column = code_range.end_column - 1
                return symbol, code_range

        return None

    def get_string(self, code_range: CodeRange):
        source = self._sources[code_range.file]
        
        # Be careful line and column start index is '1'
        # but array start index is '0' so we need to subtract 1.

        if code_range.start_line == code_range.end_line:
            return source[code_range.start_line - 1].line[code_range.start_column - 1:code_range.end_column-1]

        else:
            assert False, "`get_string(...)` is not implemented for multiline source range yet"

    def request_replace_context(self, implicit_context : CodeRange):
        assert implicit_context.file in self._sources
        self._sources[implicit_context.file][implicit_context.start_line - 1].request_replace_context(implicit_context)

    def request_replace(self, path : pathlib.Path, line: int, request : TransformStrRequest):
        self._sources[path][line - 1].request_replace(request)

    def request_replace_proto(self, path : pathlib.Path, line: int, code_range: CodeRange, name: str, has_arg : bool):
        assert path in self._sources
        self._sources[path][line - 1].request_replace_proto(code_range, name, has_arg)

    def request_replace_call(self, path : pathlib.Path, line: int, var_name: str,  code_range: CodeRange, name: str, has_arg : int):
        assert path in self._sources
        self._sources[path][line - 1].request_replace_call(var_name, code_range, name, has_arg)

    def transform_sources(self):
        for path, source in self._sources.items():
            if path in self.output_sources:
                with open(path, 'w') as file:
                    for l in source:
                        l.transform()
                        file.write(l.line)

def format_type_name(type_name):
    """
        This function remove space before '*' and '&' as it is the style of ImGui
    """

    if len(type_name) == 0:
        return type_name

    result = ''
    for i in range(len(type_name) - 1):
        if type_name[i] == ' ' and type_name[i+1] in ['*','&']:
            continue
        result += type_name[i]

    result += type_name[-1]

    return result

class FunctionParameter:
    def __init__(self, name : str, type : str, declaration : str, code_range : CodeRange):
        self.name : str = name
        self.type : str = format_type_name(type)
        self.code_range = code_range
        
        self.declaration : str = declaration
        if self.declaration is None:
            self.declaration = '{} {}'.format(type, name)

        assert self.name is not None
        assert self.type is not None
        assert self.declaration is not None

    def __str__(self):
        return self.declaration

class FunctionEntry:
    def __init__(self, ctx: ParsingContext, cursor: clang.cindex.Cursor):
        assert cursor.kind in [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD, CursorKind.FUNCTION_TEMPLATE]

        params : list[FunctionParameter] = []
        is_api = False
        fmtargs_range = None
        fmtlist_range = None
        child : clang.cindex.Cursor
        for child in cursor.get_children():
            if child.kind == CursorKind.ANNOTATE_ATTR:
                if child.spelling == 'imgui_api':
                    is_api = True
                if child.spelling.startswith('IM_FMTARGS'):
                    range = CodeRange.from_source_range(child.extent)
                    range.start_column += len('IM_FMTARGS(')
                    range.end_column -= len(')')

                    remove_me = ctx.get_string(range)
                    fmtargs_range = range
                if child.spelling.startswith('IM_FMTLIST'):
                    range = CodeRange.from_source_range(child.extent)
                    range.start_column += len('IM_FMTLIST(')
                    range.end_column -= len(')')
                    remove_me = ctx.get_string(range)
                    fmtlist_range = range

        self.is_api=is_api

        arg : clang.cindex.Cursor

        self.imgui_context_arg : FunctionParameter = None

        for arg in cursor.get_arguments():
            arg_code_range = CodeRange.from_source_range(arg.extent)
            declaration = ctx.get_string(arg_code_range)
            assert declaration is not None, "Cannot parse declaration of this arg: {} '{}'".format(arg.kind, arg.spelling)
            function_param = FunctionParameter(arg.spelling, arg.type.spelling, declaration, arg_code_range)
            if 'ImGuiContext' in declaration:
                self.imgui_context_arg = function_param
            params.append(function_param)

        self.kind = cursor.kind
        self.name : str = cursor.spelling
        self.fq_name : str = get_fully_qualified_name(cursor)
        self.id : str = cursor.mangled_name if cursor.kind != CursorKind.FUNCTION_TEMPLATE else self.fq_name
        assert self.id is not None and self.id != ''
        self.code_range : CodeRange = CodeRange.from_source_location(cursor.location, len(cursor.spelling))
        self.return_type : str = format_type_name(cursor.type.get_result().spelling)
        self.params : list[FunctionParameter] = params
        self.param_count = len(list(cursor.type.argument_types()))
        self.fmtargs_range = fmtargs_range
        self.fmtlist_range = fmtlist_range
        self.fmtargs = int(ctx.get_string(fmtargs_range)) if fmtargs_range is not None else 0
        self.fmtlist = int(ctx.get_string(fmtlist_range)) if fmtlist_range is not None else 0
        self.location=cursor.location
        
        self.method_class = get_fully_qualified_name(cursor.semantic_parent) if (cursor.kind == CursorKind.CXX_METHOD) else None
        self.is_definition=cursor.is_definition()

        self.visited = False
        self.need_context_param = False
        self.implicit_contexts : list[CodeRange] = []

        # hardcoded cases
        if self.name == 'GetKeyIndex':
            self.is_obsolete_keyio = True
        else:
            self.is_obsolete_keyio = False

        args = list(cursor.get_arguments())
        if self.name == 'ImageButton' and len(args) > 0 and args[0].spelling == 'user_texture_id':
            self.is_obsolete_functions = True
        elif self.name == 'CalcListClipping':
            self.is_obsolete_functions = True
        else:
            self.is_obsolete_functions = False


        def gimgui_visitor(cursor_stack):
            assert len(cursor_stack) > 0
            child = cursor_stack[-1]
            if child.spelling == 'GImGui':
                code_range = CodeRange.from_source_range(child.extent)
                if (code_range.start_column == code_range.end_column):
                    code_range = ctx.find_symbol(code_range.file, code_range.start_line, code_range.start_column, 'GImGui')
                    assert code_range is not None

                self.implicit_contexts.append(code_range)
                return False
            return True
        visit_cursor(cursor, None, gimgui_visitor)
    
        assert self.name is not None
        assert self.return_type is not None

    def is_valid(self, ctx: ParsingContext) -> bool:
        if self.name != ctx.get_string(self.code_range):
            return False
        for c in self.implicit_contexts:
            if 'GImGui' != ctx.get_string(c):
                return False

        return True
    
    def __key(self):
        return self.id

    def __hash__(self):
        return hash(self.__key())

    def __eq__(self, other):
        if isinstance(other, FunctionEntry):
            return self.__key() == other.__key()
        return NotImplemented

    def __str__(self):
        params = self.params
        arg_offset = 0

        suffix = ''
        if self.fmtlist > 0:
            suffix = ' IM_FMTLIST({})'.format(self.fmtlist + arg_offset)
        if self.fmtargs > 0:
            suffix = ' IM_FMTARGS({})'.format(self.fmtargs + arg_offset)
            params = params + [FunctionParameter('...', '', '...')]
        return 'IMGUI_API {type} {name}({signature}){suffix};'.format(
            type=self.return_type, 
            name=self.name, 
            signature=make_signature(params),
            suffix=suffix
        )

class CallEntry:
    def __init__(self, caller, callee, code_range, call_name, has_arg : bool):
        self.id = (code_range.file, code_range.start_line, code_range.start_column)
        self.caller = caller
        self.callee = callee
        self.code_range : CodeRange = code_range
        self.call_name = call_name
        self.has_arg = has_arg

    def __key(self):
        return self.id

    def __hash__(self):
        return hash(self.__key())

    def __eq__(self, other):
        if isinstance(other, CallEntry):
            return self.__key() == other.__key()
        return NotImplemented

class FunctionDatabase:
    """
        Assumption all entry always at least a definition, and sometimes a declaration too.
    """
    def __init__(self, ctx: ParsingContext, funcs : list[FunctionEntry]):
        self._ctx = ctx
        self._declarations : dict[str, FunctionEntry] = dict()
        self._definitions : dict[str, FunctionEntry] = dict()
        self._caller_to_call : dict[FunctionEntry, set(CallEntry)] = dict()
        self._callee_to_call : dict[FunctionEntry, set(CallEntry)] = dict()
        self._calls : dict[CallEntry, CallEntry] = dict()
        self._log_call : set[(str, CodeRange)] = set()
        for f in funcs:
            if f.is_definition:
                assert f.id not in self._definitions
                self._definitions[f.id] = f
            else:
                if f.id in self._declarations:
                    print('WARNING: {} is declared in {} and in {}'.format(f.fq_name, f.location, self._declarations[f.id].location))
                    if pathlib.Path(str(f.location.file)) != ctx.config.imgui_demo:
                        self._declarations[f.id] = f
                else:
                    self._declarations[f.id] = f

        for f in funcs:
            assert f.id in self._definitions

        for f in self._definitions.values():
            self._caller_to_call[f] = set()
            self._callee_to_call[f] = set()
            if f.id not in self._declarations:
                self._declarations[f.id] = f

    def iter_declarations(self) -> Iterable[FunctionEntry]:
        for decl in self._declarations.values():
            yield decl

    def iter_definitions(self) -> Iterable[FunctionEntry]:
        for decl in self._definitions.values():
            yield decl

    def iter_calls(self) -> Iterable[CallEntry]:
        for call in self._calls.values():
            yield call

    def iter_log_calls(self) -> Iterable[CodeRange]:
        for call in self._log_call:
            yield call

    def iter(self) -> Iterable[FunctionEntry]:
        for id in self._definitions.keys():
            decl = self._declarations[id]
            definition = self._definitions[id]
            if decl.code_range != definition.code_range:
                yield decl
            yield definition

    def add_call(self, caller_id: str, callee_id: str, code_range: CodeRange, call_name:str):
        caller = self._definitions.get(caller_id)
        callee = self._definitions.get(callee_id)
        if caller is not None and callee is not None:
            param_code_range : CodeRange = code_range.copy()
            param_code_range.start_column = code_range.end_column
            param_code_range.end_column = param_code_range.start_column + 2
            text = self._ctx.get_string(param_code_range)
            assert text[0] == '('
            call = CallEntry(caller, callee, code_range, call_name, text != '()')
            if call in self._calls:
                prev_call = self._calls[call]
                assert call not in self._calls

            self._calls[call] = call
            self._caller_to_call[caller].add(call)
            self._callee_to_call[callee].add(call)

    def add_log_call(self, name : str, code_range : CodeRange, method_class : str):
        assert code_range not in self._log_call
        self._log_call.add((name, code_range, method_class))

    def compute_context_need(self):
        for id, func in self._definitions.items():
            if len(func.implicit_contexts) > 0:
                self._set_need_context_recursive(func)

    def debug_print_calls(self):
        for call in self.iter_calls():
            print('--')
            print('{} -> {}'.format(call.caller.name, call.callee.name))
            print('{}({})'.format(call.code_range.file.absolute(), call.code_range.start_line))

    def _set_need_context_recursive(self, callee):
        decl_entry = self._declarations[callee.id]
        def_entry = self._definitions[callee.id]
        if def_entry.visited:
            assert decl_entry.visited
            return
        
        def_entry.visited = True
        decl_entry.visited = True

        if def_entry.method_class in CLASS_WITH_CONTEXT:
            assert decl_entry.method_class in CLASS_WITH_CONTEXT
            return
        
        #if len(def_entry.params) >= 1 and def_entry.params[0].declaration.startswith('ImGuiContext'):
        #    assert len(decl_entry.params) >= 1 and decl_entry.params[0].declaration.startswith('ImGuiContext')
        #    return

        decl_entry.need_context_param = True
        def_entry .need_context_param = True

        for call in self._callee_to_call[callee]:
            self._set_need_context_recursive(call.caller)

def default_write_func(x):
    print(x)

def rprint_cursor(cursor: clang.cindex.Cursor, indent='', write_func=default_write_func):
    print_cursor(cursor, indent, write_func=write_func)
    for c in cursor.get_children():
        rprint_cursor(c,indent=indent+'  ', write_func=write_func)

def print_cursor(cursor: clang.cindex.Cursor, indent='', write_func=default_write_func):
    write_func('{indent}{kind}: spelling: {spelling}, location: {location}'.format(indent=indent, kind=cursor.kind, spelling=cursor.spelling, location=cursor.location))
    print_type(cursor.type, indent=indent, write_func=write_func)

def print_type(type: clang.cindex.Type, indent='', write_func=default_write_func):
    write_func('{indent}TYPE - {kind}: spelling: {spelling}'.format(indent=indent, kind=type.kind, spelling=type.spelling))

def parse(ctx: ParsingContext, config: Config, verbose=False) -> list[FunctionEntry]:
    """
        Parse a translation unit, find all ImGui api.
        Return a list of FunctionEntry contains all api found
    """
    apis : list[FunctionEntry] = []

    for f in find_function(ctx, config, verbose=verbose):
        if f.is_api and f.code_range.file == config.imgui_h:
            apis.append(f)
    
    return apis

def iterate_recursive(parent: clang.cindex.Cursor) -> Iterable[clang.cindex.Cursor]:
    cursor : clang.cindex.Cursor
    for cursor in parent.get_children():
        yield cursor
        for child in iterate_recursive(cursor):
            yield child

def get_fully_qualified_name(cursor: clang.cindex.Cursor) -> str:
    res = cursor.spelling
    cursor = cursor.semantic_parent
    while cursor.kind != CursorKind.TRANSLATION_UNIT:
        res = cursor.spelling + '::' + res
        cursor = cursor.semantic_parent
    return res

def get_id(cursor: clang.cindex.Cursor) -> str:
    if cursor.spelling in SPECIAL_TEMPLATE_FUNC:
        return get_fully_qualified_name(cursor)
    elif cursor.mangled_name is not None and cursor.mangled_name != '':
        return cursor.mangled_name
    else:
        return None

def visit_cursor(parent: clang.cindex.Cursor, requested_kinds: CursorKind , callback, stack = [], debug_stack = []):
    cursor : clang.cindex.Cursor
    for cursor in parent.get_children():
        visit_child = True
        pop_stack = False
        if requested_kinds is None or cursor.kind in requested_kinds:
            stack.append(cursor)
            pop_stack = True
            visit_child = callback(stack)
        if visit_child:
            debug_stack.append(cursor.kind)
            visit_cursor(cursor, requested_kinds, callback, stack)
            debug_stack.pop()
        if pop_stack:
            stack.pop()
    return

def find_function(ctx: ParsingContext, config: Config, verbose=False):
    """
        Build Call Graph to find which function depend on
        an implict ImGuiContent.
    """

    funcs : list[FunctionEntry] = []
    def add_function_visitor(cursor_stack: list[clang.cindex.Cursor]):
        assert len(cursor_stack) > 0
        cursor = cursor_stack[-1]
        if pathlib.Path(str(cursor.location.file)) in ctx.config.imgui_sources:
            if cursor.mangled_name == '' and not cursor.kind == CursorKind.FUNCTION_TEMPLATE:
                if verbose:
                    print('mangle error in {} ({})'.format(cursor.spelling, cursor.location))
            elif config.is_valid_func(cursor):
                func = FunctionEntry(ctx, cursor)
                if func.name == 'IsLegacyNativeDupe':
                    i=0
                    i+=1
                assert func.is_valid(ctx)
                funcs.append(func)

        return True

    visit_cursor(ctx.tu.cursor, [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD, CursorKind.FUNCTION_TEMPLATE], add_function_visitor)

    return funcs

def find_function_call(ctx: ParsingContext, config: Config, func_db : FunctionDatabase, verbose=False):
    funcs : list[FunctionEntry] = []
    
    def function_visitor(cursor_stack: list[clang.cindex.Cursor]):
        assert len(cursor_stack) >= 1
        last_cursor = cursor_stack[-1]
        if last_cursor.kind != CursorKind.CALL_EXPR:
            return True
        
        if len(cursor_stack) < 2:
            return True

        func_cursor = None
        for c in reversed(cursor_stack):
            if c.kind != CursorKind.CALL_EXPR:
                func_cursor = c
                break

        assert func_cursor is not None
        call_cursor = cursor_stack[-1]

        if func_cursor.kind in [CursorKind.CONSTRUCTOR, CursorKind.DESTRUCTOR, CursorKind.CONVERSION_FUNCTION]:
            return True

        definition = call_cursor.get_definition()
        if config.is_valid_func(func_cursor) and config.is_valid_func(definition):
            extent = call_cursor.extent
            if definition.spelling in SPECIAL_TEMPLATE_FUNC:
                code_range = ctx.find_until(call_cursor.location.file, call_cursor.location.line, call_cursor.location.column, '(')
                text = ctx.get_string(code_range)
                i = True
            else:
                code_range = ctx.find_symbol(call_cursor.location.file, call_cursor.location.line, call_cursor.location.column, call_cursor.spelling + '(')

            if code_range is not None:
                code_range.end_column = code_range.end_column - 1 # Remove the '(')
                text = ctx.get_string(code_range)
                assert text.startswith(call_cursor.spelling)
                func_db.add_call(get_id(func_cursor), get_id(definition), code_range, text)
            elif call_cursor.spelling == 'DebugLog':
                name, code_range = ctx.find_log_symbol(call_cursor.location)
                assert name is not None and code_range is not None
                func_db.add_log_call(name, code_range, get_fully_qualified_name(func_cursor.semantic_parent) if func_cursor.kind == CursorKind.CXX_METHOD else None)
            else:
                if verbose:
                    print('WARNING: {} cannot be found at {}'.format(call_cursor.spelling, call_cursor.location))

        return True

    visit_cursor(ctx.tu.cursor, [CursorKind.FUNCTION_DECL, CursorKind.CONSTRUCTOR, CursorKind.DESTRUCTOR, CursorKind.CONVERSION_FUNCTION, CursorKind.CXX_METHOD, CursorKind.FUNCTION_TEMPLATE, CursorKind.CALL_EXPR], function_visitor)

    func_db.compute_context_need()

    for func in func_db.iter_definitions():
        for implicit_context in func.implicit_contexts:
            ctx.request_replace_context(implicit_context)
            if verbose:
                print('Replace `GImGui` with `context` in {} at {}'.format(func.fq_name, implicit_context))

    for func in func_db.iter():
        if func.need_context_param:
            if not func.is_definition:
                if func.fmtargs_range is not None:
                    req = TransformStrRequest(func.fmtargs_range.start_column - 1, func.fmtargs_range.end_column - 1, str(func.fmtargs), str(func.fmtargs + 1))
                    ctx.request_replace(func.fmtargs_range.file, func.fmtargs_range.start_line, req)
                if func.fmtlist_range is not None:
                    req = TransformStrRequest(func.fmtlist_range.start_column - 1, func.fmtlist_range.end_column - 1, str(func.fmtlist), str(func.fmtlist + 1))
                    ctx.request_replace(func.fmtlist_range.file, func.fmtlist_range.start_line, req)

            if func.imgui_context_arg is None:
                has_arg = func.param_count > 0
                ctx.request_replace_proto(func.code_range.file, func.code_range.start_line, func.code_range, func.name, has_arg)
                if verbose:
                    print('Add `ImGuiContext* context` to {} at {}'.format(func.fq_name, func.code_range))
            elif 'ctx' not in func.imgui_context_arg.declaration:
                arg = func.imgui_context_arg
                req = TransformStrRequest(arg.code_range.start_column - 1, arg.code_range.end_column - 1, arg.declaration, 'ImGuiContext* ctx')
                ctx.request_replace(arg.code_range.file, arg.code_range.start_line, req)

    for call in func_db.iter_calls():
        if call.callee.need_context_param and call.callee.imgui_context_arg is None:
            var_name = 'Ctx' if call.caller.method_class in CLASS_WITH_CONTEXT else 'ctx'
            ctx.request_replace_call(call.code_range.file, call.code_range.start_line, var_name, call.code_range, call.call_name, call.has_arg)
            if verbose:
                print('Forward `context` to {} at {}'.format(call.callee.fq_name, call.code_range))
    
    for name, code_range, method_class in func_db.iter_log_calls():
        var_name = 'Ctx' if method_class in CLASS_WITH_CONTEXT else 'ctx'
        ctx.request_replace_call(code_range.file, code_range.start_line, var_name, code_range, name, True)
        if verbose:
            print('Forward `context` to {} at {}'.format(call.callee.fq_name, call.code_range))

def make_signature(params: list[FunctionParameter], with_default=True) -> str:
    """
        Given the list of FunctionParameter, return a string containing a valid C++ signature
        which can be used in C++ function declaration
    """
    if with_default:
        return ', '.join([str(p) for p in params])
    else:
        def strip_after_equal(x):
            index = x.find('=')
            if index >= 0:
                return x[:index]
            else:
                return x
        return ', '.join([strip_after_equal(str(p)) for p in params])

def make_args(params: list[FunctionParameter]) -> str:
    """
        Given the list of FunctionParameter, return a string containing a valid C++ list of argument
        which can be used in C++ function call
    """
    return ', '.join([p.name for p in params])

def replace_in_file(path, pairs):
    with open(path, 'r') as file :
        filedata = file.read()

    for p in pairs:
        filedata = filedata.replace(p[0], p[1])

    with open(path, 'w') as file:
        file.write(filedata)

def generate(args, config: Config):
    print('--------')
    print('CONVERT SETTINGS:')
    print('  repository path = {}'.format(config.root_folder))
    print('  apply = {}'.format('enabled' if args.apply else 'disabled'))
    print('  commit = {}'.format('enabled' if args.commit else 'disabled'))
    print('--------')
    tmp_content = \
'''
#define IM_STATIC_ASSERT(...) static_assert(true)
#define IM_FMTARGS(x) __attribute__((annotate("IM_FMTARGS(" #x ")")))
#define IM_FMTLIST(x) __attribute__((annotate("IM_FMTLIST(" #x ")")))
#define IMGUI_API __attribute__((annotate("imgui_api")))
#include "imgui.cpp"\n
#include "imgui_draw.cpp"\n
#include "imgui_tables.cpp"\n
#include "imgui_widgets.cpp"\n
#include "imgui_demo.cpp"\n
'''

    index = clang.cindex.Index.create()
    
    # Disable annotation which generate compilation error with libclang
    replace_in_file(config.imgui_h, [
        ('#define IM_FMTARGS', '//TMP#define IM_FMTARGS'),
        ('#define IM_FMTLIST', '//TMP#define IM_FMTLIST'),
    ])
    replace_in_file(config.imgui_internal_h, [
        ('#define IM_STATIC_ASSERT', '//TMP#define IM_STATIC_ASSERT'),
    ])

    print('parse C++ sources...')
    tu = index.parse(config.tmp, unsaved_files=[(config.tmp, tmp_content)], args=['-std=c++17'])

    replace_in_file(config.imgui_h, [
        ('//TMP#define IM_FMTARGS', '#define IM_FMTARGS'),
        ('//TMP#define IM_FMTLIST', '#define IM_FMTLIST'),
    ])
    replace_in_file(config.imgui_internal_h, [
        ('//TMP#define IM_STATIC_ASSERT', '#define IM_STATIC_ASSERT'),
    ])

    ctx = ParsingContext(tu, config)

    if len(tu.diagnostics) > 0:
        for d in tu.diagnostics:
            print(d)

    print('Analyze syntax tree...')
    funcs = find_function(ctx, config, verbose=args.verbose)
    func_db = FunctionDatabase(ctx, funcs)
    find_function_call(ctx, config, func_db, verbose=args.verbose)

    apis = [f for f in func_db.iter() if f.is_api and f.code_range.file == config.imgui_h and f.method_class is None]

    methods = [f for f in func_db.iter_definitions() if f.need_context_param and f.method_class is not None]
    methods.sort(key= lambda f: f.method_class)
    classes = set([f.method_class for f in methods])

    if args.verbose:
        print('# Dump the list of classes depending on GImGui #')
        for c in classes:
            print(c)
            for m in [m for m in methods if m.method_class == c]:
                print(' -> ' + m.fq_name)

    if args.apply:
        print('Apply conversion...')
        ctx.transform_sources()

        if args.commit:
            commit_message = """[generated] Convert Dear ImGui API to use an explicit ImGuiContext.

This commit has been generated by the make_explicit_imgui.py script available
in the https://github.com/Dragnalith/make_explicit_imgui/ repository.
"""
            result = subprocess.run(['git', 'commit', '-a', '-F', '-'], input=commit_message.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=config.root_folder)

            stdout = result.stdout.decode()
            stderr = result.stderr.decode()
            if result.returncode != 0:
                print(stdout)
                print(stderr)
                print("`git commit` has failed")
                exit(-1)

        print('Conversion is successful !')
    else:
        print('Parsing and analysis are successful')
        print('(conversion is not applied because the `apply` option is disabled)')

def dump_test_ast(args, config):
    index = clang.cindex.Index.create()

    tu = index.parse(str(config.test_cpp), args=['-std=c++17'])

    if len(tu.diagnostics) > 0:
        for d in tu.diagnostics:
            print(d)

    with open('test_ast_dump.txt', 'w') as file:
        def write_func(x):
            file.write(x + '\n')
        rprint_cursor(tu.cursor, write_func=write_func)

def main():
    SourceLine.test()

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')

    convert_parser = subparsers.add_parser('convert', help='convert a Dear ImGui repository to explicit context API')
    convert_parser.add_argument('repository_path', action='store', type=str, help="path to the root of dear imgui repository")
    convert_parser.add_argument('-v', '--verbose', action='store_true', default=False)
    convert_parser.add_argument('-x', '--apply', action='store_true', default=False, help="Do apply the conversion. Otherwise it just parses without applying the modification")
    convert_parser.add_argument('-c', '--commit', action='store_true', default=False, help="Commit the result of the conversion")
    convert_parser.add_argument('-d', '--dump-test-ast', action='store_true', default=False, help="Dump AST of manually written code for experimentation purpose")

    rebase_parser = subparsers.add_parser('rebase', help='rebase an existing explicit context API branch')
    rebase_parser.add_argument('repository_path', action='store', type=str, help="path to the root of dear imgui repository")
    rebase_parser.add_argument('--branch', action='store', required=True)
    rebase_parser.add_argument('--base', action='store', required=False)
    rebase_parser.add_argument('--onto', action='store', required=False)

    rtransform = subparsers.add_parser('rtransform', help='internal command used by `rebase` command')
    rtransform.add_argument('filepath', action='store', type=str, help="path to the root of dear imgui repository")
    
    args = parser.parse_args()

    if args.command == 'convert':
        config = Config(args.repository_path)

        if args.dump_test_ast:
            dump_test_ast(args, config)
        else:
            generate(args, config)
    elif args.command == 'rebase':
        config = Config(args.repository_path)

        if args.onto is None:
            args.onto = args.base

        print('--------')
        print('REBASE SETTINGS:')
        print('  repository path = {}'.format(config.root_folder))
        print('  branch = {}'.format(args.branch))
        print('  base = {}'.format(args.base))
        print('  onto = {}'.format(args.onto))
        print('--------')

        env_vars = os.environ.copy()
        env_vars['GIT_SEQUENCE_EDITOR'] = 'python "{}" rtransform'.format(config.this_script.as_posix())
        result = subprocess.run(['git', 'rebase', '-i', '--onto', args.onto, args.base, args.branch], cwd=config.root_folder, env=env_vars)

        if result.returncode != 0:
            result = subprocess.run(['git', 'rebase', '--abort'], cwd=config.root_folder)
            print("`git rebase -i` has failed")

            exit(-1)

    elif args.command == 'rtransform':
        filepath = pathlib.Path(args.filepath)
        this_script = pathlib.Path(__file__).resolve()
        input_text = filepath.read_text()
        output_text = ""
        for line in input_text.splitlines():
            if len(line) == 0 or line[0] == '#':
                continue

            items = line.split(' ')
            if len(items) > 2 and items[2] == '[generated]':
                output_text += "exec python {this} convert . -xc\n".format(this=this_script.as_posix())
            else:
                output_text += line
                output_text += "\n"


        filepath.write_text(output_text)

    else:
        print('error while parsing command line')
        exit(-1)

if __name__ == '__main__':
    main()
