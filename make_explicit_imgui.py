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
        self.imguiex_h = root_folder / 'imguiex.h'
        self.imguiex_cpp = root_folder / 'imguiex.cpp'
        self.imgui_internal_h = root_folder / 'imgui_internal.h'
        self.imgui_cpp = root_folder / 'imgui.cpp'
        self.imgui_tables = root_folder / 'imgui_tables.cpp'
        self.imgui_widgets = root_folder / 'imgui_widgets.cpp'
        self.imgui_draw = root_folder / 'imgui_draw.cpp'
        self.tmp = root_folder / 'tmp.cpp'

class ParsingContext:
    def __init__(self, tu: clang.cindex.TranslationUnit):
        self.tu = tu
        self._sources = dict()

    def add_source(self, path):
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

class ApiParameter:
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

class ApiEntry:
    def __init__(self, name, return_type, params, fmtargs = None, fmtlist = None):
        self.name : str = name
        self.return_type : str = format_type_name(return_type)
        self.params : list[ApiParameter] = params
        self.param_count = len(self.params)
        self.fmtargs = int(fmtargs[11]) if fmtargs is not None else 0
        self.fmtlist = int(fmtlist[11]) if fmtlist is not None else 0

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
            params = params + [ApiParameter('...', '', '...')]
        return 'IMGUI_API {type} {name}({signature}){suffix};'.format(
            type=self.return_type, 
            name=self.name, 
            signature=make_signature(params),
            suffix=suffix
        )

def rprint_cursor(cursor: clang.cindex.Cursor, indent=''):
    print_cursor(cursor, indent)
    for c in cursor.get_children():
        rprint_cursor(c,indent=indent+'  ')

def print_cursor(cursor: clang.cindex.Cursor, indent=''):
    print('{indent}{kind}: spelling: {spelling}, location: {location}'.format(indent=indent, kind=cursor.kind, spelling=cursor.spelling, location=cursor.location))
    print_type(cursor.type, indent=indent)

def print_type(type: clang.cindex.Type, indent=''):
    print('{indent}TYPE - {kind}: spelling: {spelling}'.format(indent=indent, kind=type.kind, spelling=type.spelling))

def parse_one_api(ctx: ParsingContext, cursor: clang.cindex.Cursor, verbose=False) -> ApiEntry:
    """
        Parse a clang.cindex.Cursor, determine it is a ImGui api.
        If it is return an ApiEntry, otherwise return None
    """
    if cursor.kind != CursorKind.FUNCTION_DECL:
        return None

    if verbose and cursor.spelling in ['TreeNodeExV']:
        rprint_cursor(cursor)

    child : clang.cindex.Cursor
    is_api = False
    params : list[ApiParameter] = []
    fmtargs = None
    fmtlist = None
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
        assert declaration is not None, "Cannot parse declaration of this arg: {}".format(arg)
        params.append(ApiParameter(arg.spelling, arg.type.spelling, declaration))

            
    if is_api:
        return ApiEntry(
            name=cursor.spelling, 
            return_type=cursor.type.get_result().spelling,
            params=params,
            fmtargs=fmtargs,
            fmtlist=fmtlist
        )
    else:
        return None

def parse(ctx: ParsingContext, verbose=False) -> list[ApiEntry]:
    """
        Parse a translation unit, find all ImGui api.
        Return a list of ApiEntry contains all api found
    """
    apis : list[ApiEntry] = []

    child : clang.cindex.Cursor
    for child in ctx.tu.cursor.get_children():
        if (child.kind == clang.cindex.CursorKind.NAMESPACE):
            for c in child.get_children():
                api = parse_one_api(ctx, c, verbose=verbose)
                if api is not None:
                    apis.append(api)
    
    return apis

def iterate_namespace(cursor: clang.cindex.Cursor) -> Iterable[clang.cindex.Cursor]:
    child : clang.cindex.Cursor
    for child in cursor.get_children():
        if (child.kind == clang.cindex.CursorKind.NAMESPACE):
            for subchild in iterate_namespace(child):
                yield subchild
        else:
            yield child

def iterate_recursive(cursor: clang.cindex.Cursor) -> Iterable[clang.cindex.Cursor]:
    child : clang.cindex.Cursor
    for child in cursor.get_children():
        yield child
        for subchild in iterate_recursive(child):
            yield subchild

def find_function_cursor(cursor: clang.cindex.Cursor) -> clang.cindex.Cursor:
    deff = cursor.get_definition()

    return deff

def find_function_cursor2(cursor: clang.cindex.Cursor, kind: CursorKind) -> clang.cindex.Cursor:
    spelling_candidate = [
        cursor.spelling,
        'class ' + cursor.spelling,
        'struct ' + cursor.spelling
    ]
    kind_candidate = [
        CursorKind.TYPE_REF,
        CursorKind.DECL_REF_EXPR
    ]
    candidate = None
    for child in iterate_recursive(cursor):
        if child.kind in kind_candidate and child.spelling in spelling_candidate:
            candidate = child

    if candidate.kind == CursorKind.DECL_REF_EXPR:
        cursor_def = candidate.get_definition()
        cursor_decl = candidate.type.get_declaration()
        def_parent = cursor_def.semantic_parent

        assert def_parent is not None

        return cursor_def
    if candidate.kind == CursorKind.TYPE_REF:
        cursor = candidate.type.get_declaration()
        assert cursor.kind != CursorKind.NO_DECL_FOUND
        return cursor

    return None

        
def get_fully_qualified_name2(cursor: clang.cindex.Cursor):
    type = cursor.type
    semantic_parent : clang.cindex.Cursor =  cursor.semantic_parent
    if semantic_parent.kind == CursorKind.TRANSLATION_UNIT:
        return type.spelling
    else:
        return get_fully_qualified_name(semantic_parent) + '::' + type.spelling

def get_fully_qualified_name(cursor: clang.cindex.Cursor):
    res = cursor.spelling
    cursor = cursor.semantic_parent
    while cursor.kind != CursorKind.TRANSLATION_UNIT:
        res = cursor.spelling + '::' + res
        cursor = cursor.semantic_parent
    return res

def parse_function_call(ctx: ParsingContext, verbose=False):
    """
        Build Call Graph to find which function depend on
        an implict ImGuiContent.
    """

    cursor : clang.cindex.Cursor
    for cursor in iterate_namespace(ctx.tu.cursor):
        if (cursor.kind == CursorKind.FUNCTION_DECL or cursor.kind == CursorKind.CXX_METHOD):
            use_implicit_context = False
            call_list = []
            for child in iterate_recursive(cursor):
                if child.spelling == 'GImGui':
                    use_implicit_context = True
                if child.kind == CursorKind.CALL_EXPR:
                    function_def = find_function_cursor(child)
                    if function_def is not None:
                        call_list.append(get_fully_qualified_name(function_def))
                    else:
                        print('error: {} ({})'.format(child.spelling, child.location))

            # if use_implicit_context:
            #     print('--start--')
            #     print(get_fully_qualified_name(cursor))
            #     for c in call_list:
            #         print('   ' + c)
            #     print('--end--')

def make_signature(params: list[ApiParameter], with_default=True) -> str:
    """
        Given the list of ApiParameter, return a string containing a valid C++ signature
        which can be used in C++ function declaration
    """
    if with_default:
        return ', '.join([str(p) for p in params])
    else:
        return ', '.join(['{} {}'.format(p.type, p.name) for p in params])

def make_args(params: list[ApiParameter]) -> str:
    """
        Given the list of ApiParameter, return a string containing a valid C++ list of argument
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
//#include "imgui.cpp"\n
#include "imgui_draw.cpp"\n
//#include "imgui_tables.cpp"\n
//#include "imgui_widgets.cpp"\n
'''

    index = clang.cindex.Index.create()


    tu = index.parse(config.tmp, unsaved_files=[(config.tmp, tmp_content)], args=['-std=c++17'])
    ctx = ParsingContext(tu)
    ctx.add_source(config.imgui_h)
    ctx.add_source(config.imgui_internal_h)

    if len(tu.diagnostics) > 0:
        for d in tu.diagnostics:
            print(d)

    parse_function_call(ctx, verbose=args.verbose)

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
    ctx = ParsingContext(tu)
    ctx.add_source(config.imgui_h)
    ctx.add_source(config.imgui_internal_h)

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
            context_param : ApiParameter = ApiParameter('context', 'ImGuiContext*')
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
                    params = params + [ApiParameter('...', '', '...')]
                file.write('    IMGUI_API {type} {name}({signature}){suffix};\n'.format(
                    type=api.return_type, 
                    name=api.name, 
                    signature=make_signature(params),
                    suffix=suffix
                ))
            file.write('}\n')
            
        with open(config.imguiex_cpp, 'w', encoding='utf-8') as file:
            context_arg : ApiParameter = ApiParameter('GImGui', 'ImGuiContext*')
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
                    params = params + [ApiParameter('...', '', '...')]
                    args = args + [ApiParameter('args', 'va_list')]
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
    args = parser.parse_args()

    root_folder = pathlib.Path(args.repository_path)

    config = Config(root_folder)

    if args.research:
        run_research(args, config)
    else:
        generate(args, config)

if __name__ == '__main__':
    main()
