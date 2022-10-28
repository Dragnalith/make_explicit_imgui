from logging import root
from re import U
import clang.cindex
import argparse
import pathlib
import typing

parser = argparse.ArgumentParser()
parser.add_argument('repository_path', action='store', type=str, help="path to the root of dear imgui repository")
args = parser.parse_args()

root_folder = pathlib.Path(args.repository_path)
imgui_h = root_folder / 'imgui.h'
imgui_cpp = root_folder / 'imgui.cpp'
tmp = root_folder / 'tmp.cpp'
index = clang.cindex.Index.create()

tu = index.parse(tmp, unsaved_files=[(tmp, '#include "imgui.h"\n')],args=['-std=c++17'])


def filter_node_list_by_node_kind(nodes: typing.Iterable[clang.cindex.Cursor], kinds: list) -> typing.Iterable[clang.cindex.Cursor]:
    result = []
    for i in nodes:
        if i.kind in kinds:
            yield i
    return

all_classes = filter_node_list_by_node_kind(tu.cursor.get_children(), [clang.cindex.CursorKind.CLASS_DECL, clang.cindex.CursorKind.STRUCT_DECL])
for i in all_classes:
    print (i.spelling)

