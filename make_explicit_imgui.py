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
        self.file = file
        self.start_line = start_line
        self.start_column = start_column
        self.end_line = end_line
        self.end_column = end_column

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

class ParsingContext:
    def __init__(self, tu: clang.cindex.TranslationUnit, config: Config):
        self.tu = tu
        self._sources = dict()
        self.config = config
        for source in config.imgui_sources:
            self._add_source(source)

    def _add_source(self, path):
        if not isinstance(path, pathlib.Path):
            path = pathlib.Path(path)

        lines = []
        with open(path) as file:
            lines += list(file)
        self._sources[path] = lines

    def get_string(self, code_range: CodeRange):
        source = self._sources[code_range.file]
        
        # Be careful line and column start index is '1'
        # but array start index is '0' so we need to subtract 1.

        if code_range.start_line == code_range.end_line:
            return source[code_range.start_line - 1][code_range.start_column - 1:code_range.end_column-1]

        else:
            assert False, "`get_string(...)` is not implemented for multiline source range yet"

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
        self.implicit_context = None
        for child in iterate_recursive(cursor):
            if child.spelling == 'GImGui':
                self.implicit_context = child.extent
                break

        assert self.name is not None
        assert self.return_type is not None

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

class FunctionDatabase:
    """
        Assumption all entry always at least a definition, and sometimes a declaration too.
    """
    def __init__(self, ctx: ParsingContext, funcs : list[FunctionEntry]):
        self._ctx = ctx
        self._declarations : dict[FunctionEntry] = dict()
        self._definitions : dict[FunctionEntry] = dict()
        self._func_to_call : dict[FunctionEntry, set(FunctionEntry)] = dict()
        self._call_to_func : dict[FunctionEntry, set(FunctionEntry)] = dict()
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
            self._func_to_call[f] = set()
            self._call_to_func[f] = set()
            if f.id not in self._declarations:
                self._declarations[f.id] = f

    def iter_declarations(self) -> Iterable[FunctionEntry]:
        for decl in self._declarations.values():
            yield decl

    def add_call(self, func_id: str, call_id: str):
        func = self._definitions.get(func_id)
        call = self._definitions.get(call_id)
        if func is not None and call is not None:
            self._call_to_func[call].add(func)
            self._func_to_call[func].add(call)

    def dump_func_to_call(self):
        for func, callees in self._func_to_call.items():
            print(func.fq_name + ':')
            for call in callees:
                print('    * ' + call.fq_name)

    def compute_context_need(self):
        for call, funcs in self._call_to_func.items():
            if call.implicit_context is not None:
                self._set_need_context_recursive(call)

    def _set_need_context_recursive(self, call):
        decl_entry = self._declarations[call.id]
        def_entry = self._definitions[call.id]
        if def_entry.visited:
            assert decl_entry.visited
            return
        
        decl_entry.need_context_param = True
        def_entry .need_context_param = True
        def_entry.visited = True
        decl_entry.visited = True

        for func in self._call_to_func[call]:
            self._set_need_context_recursive(func)

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
        if cursor.kind in requested_kinds:
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
            else:
                func = FunctionEntry(ctx, cursor)
                funcs.append(func)

        return False

    visit_cursor(ctx.tu.cursor, [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD], add_function_visitor)

    if verbose:
        for f in funcs:
            use_context = 'YES' if f.implicit_context is not None else 'NO'
            if f.is_method:
                print('[{}] use_context: {}, is_def: {}, method_of: {}, loc: {}'.format(f.fq_name, use_context, f.is_definition, f.class_type, f.location))
            else:
                print('[{}] use_context: {}, is_def: {}, method_of: None, loc: {}'.format(f.fq_name, use_context, f.is_definition, f.location))

    return funcs

def find_function_call(ctx: ParsingContext, config: Config, func_db : FunctionDatabase, verbose=False):
    funcs : list[FunctionEntry] = []
    
    def function_declaration_visitor(func_cursor: clang.cindex.Cursor):
        def function_call_visitor(call_cursor: clang.cindex.Cursor):
            definition = call_cursor.get_definition()
            if definition is not None:
                func_db.add_call(func_cursor.mangled_name, definition.mangled_name)

            return True
        visit_cursor(func_cursor, [CursorKind.CALL_EXPR], function_call_visitor)

    visit_cursor(ctx.tu.cursor, [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD], function_declaration_visitor)

    func_db.compute_context_need()

    print('--- NEED CONTEXT ---')
    for decl in func_db.iter_declarations():
        if decl.need_context_param:
            print(decl.fq_name)

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

    tu = index.parse(config.tmp, unsaved_files=[(config.tmp, tmp_content)], args=['-std=c++17'])
    ctx = ParsingContext(tu, config)

    if len(tu.diagnostics) > 0:
        for d in tu.diagnostics:
            print(d)

    funcs = find_function(ctx, config, verbose=args.verbose)
    func_db = FunctionDatabase(ctx, funcs)
    find_function_call(ctx, config, func_db, verbose=args.verbose)

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
