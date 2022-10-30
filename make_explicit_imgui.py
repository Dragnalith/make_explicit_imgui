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

class Config:
    def __init__(self, root_folder):
        self.imgui_h = root_folder / 'imgui.h'
        self.imgui_internal_h = root_folder / 'imgui_internal.h'
        self.imgui_cpp = root_folder / 'imgui.cpp'
        self.imgui_tables = root_folder / 'imgui_tables.cpp'
        self.imgui_widgets = root_folder / 'imgui_widgets.cpp'
        self.imgui_draw = root_folder / 'imgui_draw.cpp'
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
            self.imgui_draw
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

    def get_string(self, source_range: clang.cindex.SourceRange):
        start : clang.cindex.SourceLocation = source_range.start
        end : clang.cindex.SourceLocation = source_range.end

        start_file = pathlib.Path(str(start.file))
        end_file = pathlib.Path(str(end.file))
        assert start_file == end_file, "start file ({}) and end of file ({}) does not match".format(start.file, end.file)

        if start_file not in self._sources:
            return None

        source = self._sources[start_file]
        
        # Be careful line and column start index is '1'
        # but array start index is '0' so we need to subtract 1.

        if start.line == end.line:
            return source[start.line - 1][start.column - 1:end.column-1]

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
            declaration = ctx.get_string(arg.extent)
            assert declaration is not None, "Cannot parse declaration of this arg: {} '{}'".format(arg.kind, arg.spelling)
            params.append(FunctionParameter(arg.spelling, arg.type.spelling, declaration))

        self.name : str = cursor.spelling
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

        assert self.name is not None
        assert self.return_type is not None

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

def parse(ctx: ParsingContext, verbose=False) -> list[FunctionEntry]:
    """
        Parse a translation unit, find all ImGui api.
        Return a list of FunctionEntry contains all api found
    """
    apis : list[FunctionEntry] = []

    child : clang.cindex.Cursor
    for child in ctx.tu.cursor.get_children():
        if (child.kind == clang.cindex.CursorKind.NAMESPACE):
            for c in child.get_children():
                if c.kind in [CursorKind.FUNCTION_DECL]:
                    func = FunctionEntry(ctx, c)
                    if func.is_api:
                        apis.append(func)
    
    return apis

def iterate_namespace(cursor: clang.cindex.Cursor) -> Iterable[clang.cindex.Cursor]:
    child : clang.cindex.Cursor
    for child in cursor.get_children():
        if (child.kind == clang.cindex.CursorKind.NAMESPACE):
            for subchild in iterate_namespace(child):
                yield subchild
        else:
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

def find_function(ctx: ParsingContext, verbose=False):
    """
        Build Call Graph to find which function depend on
        an implict ImGuiContent.
    """

    if False:
        with open('dump.txt', 'w') as file:
            def write_func(x):
                file.write(x + '\n')
            rprint_cursor(ctx.tu.cursor, write_func=write_func)
        return

    funcs : list[FunctionEntry] = []
    def add_function_visitor(cursor: clang.cindex.Cursor):
        if pathlib.Path(str(cursor.location.file)) in ctx.config.imgui_sources:
            func = FunctionEntry(ctx, cursor)
            funcs.append(func)

        return False

    visit_cursor(ctx.tu.cursor, [CursorKind.FUNCTION_DECL, CursorKind.CXX_METHOD], add_function_visitor)

    for f in funcs:
        if f.is_method:
            print('[{}] is_def: {}, method_of: {}, loc: {}'.format(f.fq_name, f.is_definition, f.class_type, f.location))
        else:
            print('[{}] is_def: {}, method_of: None, loc: {}'.format(f.fq_name, f.is_definition, f.location))

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
'''

    index = clang.cindex.Index.create()

    tu = index.parse(config.tmp, unsaved_files=[(config.tmp, tmp_content)], args=['-std=c++17'])
    ctx = ParsingContext(tu, config)

    if len(tu.diagnostics) > 0:
        for d in tu.diagnostics:
            print(d)

    find_function(ctx, verbose=args.verbose)

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

    apis = parse(ctx, verbose=args.verbose)
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
