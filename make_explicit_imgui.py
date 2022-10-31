import subprocess
from re import U
import clang.cindex
from clang.cindex import CursorKind, TypeKind
import argparse
import pathlib
from typing import Iterable

WHITELIST = set([
    'CreateContext',
    'DestroyContext',
    'GetCurrentContext',
    'SetCurrentContext',
    'AddContextHook',
    'RemoveContextHook',
    'CallContextHooks'
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
        self.root_folder = root_folder
        self.imgui_h = root_folder / 'imgui.h'
        self.imgui_internal_h = root_folder / 'imgui_internal.h'
        self.imgui_cpp = root_folder / 'imgui.cpp'
        self.imgui_tables = root_folder / 'imgui_tables.cpp'
        self.imgui_widgets = root_folder / 'imgui_widgets.cpp'
        self.imgui_draw = root_folder / 'imgui_draw.cpp'
        self.imgui_demo = root_folder / 'imgui_demo.cpp'
        self.imguiex_h = root_folder / 'imguiex.h'
        self.imguiex_cpp = root_folder / 'imguiex.cpp'
        self.tmp = root_folder / 'tmp.cpp'
        self.test_cpp = pathlib.Path(__file__).parent / 'test/test.cpp'
        self.imgui_sources = set([
            self.imgui_h,
            self.imgui_internal_h,
            self.imgui_cpp,
            self.imgui_tables,
            self.imgui_widgets,
            self.imgui_draw,
            self.imgui_demo
        ])

        # Those API need special handling
        self.blacklist = [
            'CreateContext',
            'DestroyContext',
            'GetCurrentContext',
            'SetCurrentContext',
            'MemAlloc',
            'MemFree',
        ]

    def is_valid_func(self, cursor):
        return cursor is not None \
            and pathlib.Path(str(cursor.location.file)) in self.imgui_sources \
            and cursor.spelling not in self.blacklist


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
        self.transform_call : list[TransformStrRequest] = set()
        self.transform_proto : TransformStrRequest = None
        self.delete = False

    def request_replace_context(self, implicit_context : CodeRange):
        assert self.replace_context is None
        self.replace_context = TransformStrRequest(implicit_context.start_column - 1, implicit_context.end_column - 1, 'GImGui', 'ctx')

    def request_replace_proto(self, code_range: CodeRange, name: str, has_arg: bool):
        assert self.transform_proto is None
        arg = 'ImGuiContext* ctx' + (', ' if has_arg > 0 else '')
        self.transform_proto = TransformStrRequest(code_range.start_column - 1, code_range.end_column , name + '(', name + '(' + arg)

    def request_replace_call(self, code_range: CodeRange, name: str, has_arg):
        arg = 'ctx' + (', ' if has_arg > 0 else '')
        request = TransformStrRequest(code_range.start_column - 1, code_range.end_column, name + '(', name + '(' + arg)
        self.transform_call.add(request)

    def transform(self):
        requests : list[TransformStrRequest] = list()
        if self.replace_context is not None:
            requests.append(self.replace_context)
        
        if self.transform_proto is not None:
            requests.append(self.transform_proto)

        if len(self.transform_call) > 0:
            requests += self.transform_call
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
        source.request_replace_call(CodeRange('', 1, 68, 1, 71), 'Foo', 1)
        source.request_replace_call(CodeRange('', 1, 77, 1, 85), 'SuperBar', 0)
        source.request_replace_call(CodeRange('', 1, 89, 1, 92), 'Foo', 1)
        source.transform()
        assert source.line == 'inline MyFunc(ImGuiContext* ctx, int a, float val = 0.f) { ImGuiContext& g = *ctx; Foo(ctx, 28); SuperBar(ctx); Foo(ctx, 29);', 'Source test failed'


class ParsingContext:
    def __init__(self, tu: clang.cindex.TranslationUnit, config: Config):
        self.tu = tu
        self._sources : dict[pathlib.Path, list[SourceLine]] = dict()
        self.config = config
        for source in config.imgui_sources:
            self._add_source(source)

    def _add_source(self, path):
        if not isinstance(path, pathlib.Path):
            path = pathlib.Path(path)

        lines = []
        with open(path) as file:
            lines += list(file)
        self._sources[path] = [SourceLine(line) for line in lines]

    def get_line(self, path, line):
        if isinstance(path, str):
            path = pathlib.Path(path)

        assert path in self._sources
        return self._sources[path][line - 1].line

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

    def request_replace_proto(self, path : pathlib.Path, line: int, code_range: CodeRange, name: str, has_arg : bool):
        assert path in self._sources
        self._sources[path][line - 1].request_replace_proto(code_range, name, has_arg)

    def request_replace_call(self, path : pathlib.Path, line: int, code_range: CodeRange, name: str, has_arg : int):
        assert path in self._sources
        self._sources[path][line - 1].request_replace_call(code_range, name, has_arg)

    def transform_sources(self):
        for path, source in self._sources.items():
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
    def __init__(self, name : str, type : str, declaration : str = None):
        self.name : str = name
        self.type : str = format_type_name(type)
        
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
        assert cursor.kind in [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD]

        params : list[FunctionParameter] = []
        is_api = False
        fmtargs = None
        fmtlist = None
        child : clang.cindex.Cursor
        for child in cursor.get_children():
            if child.kind == CursorKind.ANNOTATE_ATTR:
                if child.spelling == 'imgui_api':
                    is_api = True
                if child.spelling.startswith('IM_FMTARGS'):
                    fmtargs = child.spelling
                if child.spelling.startswith('IM_FMTLIST'):
                    fmtlib = child.spelling

        arg : clang.cindex.Cursor
        for arg in cursor.get_arguments():
            declaration = ctx.get_string(CodeRange.from_source_range(arg.extent))
            assert declaration is not None, "Cannot parse declaration of this arg: {} '{}'".format(arg.kind, arg.spelling)
            params.append(FunctionParameter(arg.spelling, arg.type.spelling, declaration))

        self.name : str = cursor.spelling
        self.id : str = cursor.mangled_name
        assert self.id is not None and self.id != ''
        self.code_range : CodeRange = CodeRange.from_source_location(cursor.location, len(cursor.spelling))
        self.fq_name : str = get_fully_qualified_name(cursor)
        self.return_type : str = format_type_name(cursor.type.get_result().spelling)
        self.params : list[FunctionParameter] = params
        self.param_count = len(self.params)
        self.fmtargs = int(fmtargs[11]) if fmtargs is not None else 0
        self.fmtlist = int(fmtlist[11]) if fmtlist is not None else 0
        self.is_api=is_api
        self.location=cursor.location
        self.is_method=cursor.kind == CursorKind.CXX_METHOD
        self.is_definition=cursor.is_definition()
        if self.is_method:
            self.class_type = get_fully_qualified_name(cursor.semantic_parent)

        self.visited = False
        self.need_context_param = False
        self.implicit_contexts : list[CodeRange] = []

        def gimgui_visitor(child):
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
    def __init__(self, caller, callee, code_range, has_arg : bool):
        self.id = (code_range.file, code_range.start_line, code_range.start_column)
        self.caller = caller
        self.callee = callee
        self.code_range = code_range
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
        self._declarations : dict[FunctionEntry] = dict()
        self._definitions : dict[FunctionEntry] = dict()
        self._caller_to_call : dict[FunctionEntry, set(CallEntry)] = dict()
        self._callee_to_call : dict[FunctionEntry, set(CallEntry)] = dict()
        self._calls : dict[CallEntry, CallEntry] = dict();
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

    def iter(self) -> Iterable[FunctionEntry]:
        for id in self._definitions.keys():
            decl = self._declarations[id]
            definition = self._definitions[id]
            if decl.code_range != definition.code_range:
                yield decl
            yield definition

    def add_call(self, caller_id: str, callee_id: str, code_range: CodeRange):
        caller = self._definitions.get(caller_id)
        callee = self._definitions.get(callee_id)
        if caller is not None and callee is not None:
            param_code_range : CodeRange = code_range.copy()
            param_code_range.start_column = code_range.end_column
            param_code_range.end_column = param_code_range.start_column + 2
            text = self._ctx.get_string(param_code_range)
            assert text[0] == '('
            call = CallEntry(caller, callee, code_range, text != '()')
            if call in self._calls:
                prev_call = self._calls[call]
                assert call not in self._calls

            self._calls[call] = call
            self._caller_to_call[caller].add(call)
            self._callee_to_call[callee].add(call)

    def compute_context_need(self):
        for id, func in self._definitions.items():
            if len(func.implicit_contexts) > 0:
                self._set_need_context_recursive(func)

    def _set_need_context_recursive(self, callee):
        decl_entry = self._declarations[callee.id]
        def_entry = self._definitions[callee.id]
        if def_entry.visited:
            assert decl_entry.visited
            return
        
        decl_entry.need_context_param = True
        def_entry .need_context_param = True
        def_entry.visited = True
        decl_entry.visited = True

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

def get_fully_qualified_name(cursor: clang.cindex.Cursor):
    res = cursor.spelling
    cursor = cursor.semantic_parent
    while cursor.kind != CursorKind.TRANSLATION_UNIT:
        res = cursor.spelling + '::' + res
        cursor = cursor.semantic_parent
    return res

def visit_cursor(parent: clang.cindex.Cursor, requested_kinds: CursorKind , callback):
    cursor : clang.cindex.Cursor
    for cursor in parent.get_children():
        visit_child = True
        if requested_kinds is None or cursor.kind in requested_kinds:
            visit_child = callback(cursor)
        if visit_child:
            visit_cursor(cursor, requested_kinds, callback)
    return

def find_function(ctx: ParsingContext, config: Config, verbose=False):
    """
        Build Call Graph to find which function depend on
        an implict ImGuiContent.
    """

    funcs : list[FunctionEntry] = []
    def add_function_visitor(cursor: clang.cindex.Cursor):
        if pathlib.Path(str(cursor.location.file)) in ctx.config.imgui_sources:
            if cursor.mangled_name == '':
                if verbose:
                    print('mangle error in {} ({})'.format(cursor.spelling, cursor.location))
            elif config.is_valid_func(cursor):
                func = FunctionEntry(ctx, cursor)
                assert func.is_valid(ctx)
                funcs.append(func)

        return False

    visit_cursor(ctx.tu.cursor, [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD], add_function_visitor)

    return funcs

def find_function_call(ctx: ParsingContext, config: Config, func_db : FunctionDatabase, verbose=False):
    funcs : list[FunctionEntry] = []
    
    def function_declaration_visitor(func_cursor: clang.cindex.Cursor):
        def function_call_visitor(call_cursor: clang.cindex.Cursor):
            definition = call_cursor.get_definition()
            if config.is_valid_func(call_cursor) and config.is_valid_func(definition):
                code_range = ctx.find_symbol(call_cursor.location.file, call_cursor.location.line, call_cursor.location.column, call_cursor.spelling + '(')
                if code_range is not None:
                    code_range.end_column = code_range.end_column - 1 # Remove the '(')
                    text = ctx.get_string(code_range)
                    assert text == call_cursor.spelling
                    func_db.add_call(func_cursor.mangled_name, definition.mangled_name, code_range)
                else:
                    print('WARNING: {} cannot be found at {}'.format(call_cursor.spelling, call_cursor.location))

            return True
        visit_cursor(func_cursor, [CursorKind.CALL_EXPR], function_call_visitor)

    visit_cursor(ctx.tu.cursor, [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD], function_declaration_visitor)

    func_db.compute_context_need()

    print('--- REMOVE GLOBAL CONTEXT ---')
    for func in func_db.iter_definitions():
        for implicit_context in func.implicit_contexts:
            ctx.request_replace_context(implicit_context)
            if verbose:
                print('Replace `GImGui` with `context` in {} at {}'.format(func.fq_name, implicit_context))
    print('--- ADD CONTEXT PARAMETER ---')
    for func in func_db.iter():
        if func.need_context_param:
            ctx.request_replace_proto(func.code_range.file, func.code_range.start_line, func.code_range, func.name, func.param_count > 0)
            if verbose:
                print('Add `ImGuiContext* context` to {} at {}'.format(func.fq_name, func.code_range))
    print('--- FORWARD CONTEXT ---')
    for call in func_db.iter_calls():
        if call.callee.need_context_param:
            ctx.request_replace_call(call.code_range.file, call.code_range.start_line, call.code_range, call.callee.name, call.has_arg)
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
        return ', '.join(['{} {}'.format(p.type, p.name) for p in params])

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

def run_research(args, config):
    tmp_content = \
'''
#include "imgui.cpp"\n
#include "imgui_draw.cpp"\n
#include "imgui_tables.cpp"\n
#include "imgui_widgets.cpp"\n
#include "imgui_demo.cpp"\n
'''

    index = clang.cindex.Index.create()
    
    if args.execute:
        subprocess.run(['git', 'checkout', '-f', '*.cpp', '*.h'], cwd=config.root_folder)

    tu = index.parse(config.tmp, unsaved_files=[(config.tmp, tmp_content)], args=['-std=c++17'])
    ctx = ParsingContext(tu, config)

    if len(tu.diagnostics) > 0:
        for d in tu.diagnostics:
            print(d)

    funcs = find_function(ctx, config, verbose=args.verbose)
    func_db = FunctionDatabase(ctx, funcs)
    find_function_call(ctx, config, func_db, verbose=args.verbose)

    if args.execute:
        ctx.transform_sources()

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

def generate(args, config):
    tmp_content = \
'''
#define IM_FMTARGS(x) __attribute__((annotate("IM_FMTARGS(" #x ")")))
#define IM_FMTLIST(x) __attribute__((annotate("IM_FMTLIST(" #x ")")))
#define IMGUI_API __attribute__((annotate("imgui_api")))
#include "imgui.h"\n
#include "imgui_internal.h"\n
'''

    index = clang.cindex.Index.create()

    replace_in_file(config.imgui_h, [
        ('#define IM_FMTARGS', '//TMP#define IM_FMTARGS'),
        ('#define IM_FMTLIST', '//TMP#define IM_FMTLIST'),
    ])

    tu = index.parse(config.tmp, unsaved_files=[(config.tmp, tmp_content)], args=['-std=c++17'])
    ctx = ParsingContext(tu, config)

    replace_in_file(config.imgui_h, [
        ('//TMP#define IM_FMTARGS', '#define IM_FMTARGS'),
        ('//TMP#define IM_FMTLIST', '#define IM_FMTLIST'),
    ])

    if len(tu.diagnostics) > 0:
        for d in tu.diagnostics:
            print(d)

    apis = parse(ctx, config, verbose=args.verbose)
    if args.print:
        for api in apis:
            print(api)

    if args.execute:
        with open(config.imguiex_h, 'w', encoding='utf-8') as file:
            context_param : FunctionParameter = FunctionParameter('context', 'ImGuiContext*')
            file.write('#include "imgui.h"\n')
            file.write('#include "imgui_internal.h"\n\n')
            file.write('namespace ImGuiEx\n')
            file.write('{\n')
            for api in apis:
                if api.name in WHITELIST:
                    params = api.params
                    arg_offset = 0
                else:
                    params = [context_param] + api.params
                    arg_offset = 1
                suffix = ''
                if api.fmtlist > 0:
                    suffix = ' IM_FMTLIST({})'.format(api.fmtlist + arg_offset)
                if api.fmtargs > 0:
                    suffix = ' IM_FMTARGS({})'.format(api.fmtargs + arg_offset)
                    params = params + [FunctionParameter('...', '', '...')]
                file.write('    IMGUI_API {type} {name}({signature}){suffix};\n'.format(
                    type=api.return_type, 
                    name=api.name, 
                    signature=make_signature(params),
                    suffix=suffix
                ))
            file.write('}\n')
            
        with open(config.imguiex_cpp, 'w', encoding='utf-8') as file:
            context_arg : FunctionParameter = FunctionParameter('GImGui', 'ImGuiContext*')
            file.write('#include "imgui.h"\n')
            file.write('#include "imguiex.h"\n\n')
            file.write('ImGuiContext*   GImGui = NULL;\n\n')
            file.write('namespace ImGui\n')
            file.write('{\n')
            for api in apis:
                params = api.params
                name = api.name
                if api.name in WHITELIST:
                    args = api.params
                else:
                    args = [context_arg] + api.params
                if api.fmtargs > 0:
                    params = params + [FunctionParameter('...', '', '...')]
                    args = args + [FunctionParameter('args', 'va_list')]
                    name = name + 'V'
                file.write('    {type} {name}({signature}) {{\n'.format(type=api.return_type, name=api.name, signature=make_signature(params, with_default=False)))
                if (api.fmtargs) > 0:
                    file.write('        va_list args;\n');
                    file.write('        va_start(args, fmt);\n');
                file.write('        ImGuiEx::{name}({args});\n'.format(name=name,args=make_args(args)))
                if (api.fmtargs) > 0:
                    file.write('        va_end(args);\n');
                file.write('    }\n')
            file.write('}\n')

def main():
    SourceLine.test()

    parser = argparse.ArgumentParser()
    parser.add_argument('repository_path', action='store', type=str, help="path to the root of dear imgui repository")
    parser.add_argument('-v', '--verbose', action='store_true', default=False)
    parser.add_argument('-p', '--print', action='store_true', default=False)
    parser.add_argument('-x', '--execute', action='store_true', default=False, help="Actually do the imgui repository conversion")
    parser.add_argument('-r', '--research', action='store_true', default=False, help="Run research code made to explore how to parse imgui with libclang")
    parser.add_argument('-d', '--dump-test-ast', action='store_true', default=False, help="Dump AST of manually written code for experimentation purpose")
    args = parser.parse_args()

    root_folder = pathlib.Path(args.repository_path)

    config = Config(root_folder)

    if args.research:
        run_research(args, config)
    elif args.dump_test_ast:
        dump_test_ast(args, config)
    else:
        generate(args, config)

if __name__ == '__main__':
    main()
