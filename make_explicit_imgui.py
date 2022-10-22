import pathlib
import re
import argparse

API_PATTERN = re.compile(r'^(\s*)IMGUI_API(\s*)([\w\[\]&\*]*)(\s*)(\w*)\((.*)\)\;(\s*)//(.*)$')
START_NS_PATTERN = re.compile(r'^namespace\s*ImGui.*$')
END_NS_PATTERN = re.compile(r'^}.*$')

class ApiEntry:
    def __init__(self, re_result, line_ending, line_number):
        self.line_ending = line_ending
        self.line_number = line_number;
        self.indent_size = len(re_result.group(1))
        self.spacing_1 = len(re_result.group(2))
        self.result_type = re_result.group(3)
        self.spacing_2 = len(re_result.group(4))
        self.name = re_result.group(5)
        self.signature = re_result.group(6)
        self.comment_space = re_result.group(7)
        self.comment = re_result.group(8)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('repository_path', action='store', type=str, help="path to the root of dear imgui repository")
    args = parser.parse_args()

    root_folder = pathlib.Path(args.repository_path)

    imgui_h = root_folder / 'imgui.h'
    imgui_internal_h = root_folder / 'imgui_internal.h'
    imgui_cpp = root_folder / 'imgui.cpp'
    imgui_tables = root_folder / 'imgui_tables.h'
    imgui_widgets = root_folder / 'imgui_widgets.h'

    assert imgui_h.is_file()

    apis : list[ApiEntry] = []
    inside_api_scope = False
    with open(imgui_h, 'r', encoding='utf-8') as file:

        file.seek(0)
        line_number = 0
        while True:
            line_number += 1
            line = file.readline()

            if len(line) == 0:
                break

            if inside_api_scope == False:
                result = START_NS_PATTERN.match(line)
                if result is not None:
                    print('Start API scope at line {}'.format(line_number))
                    inside_api_scope = True
                continue

            if line.endswith('\r'):
                line_ending = '\r'
            elif line.endswith('\r\n'):
                line_ending = '\r\n'
            elif line.endswith('\n'):
                line_ending = '\n'
            line = line.rstrip('\r').rstrip('\n')

            result = API_PATTERN.match(line)
            if result is not None:
                apis.append(ApiEntry(result, line_ending, line_number))
            else:
                result = END_NS_PATTERN.match(line)
                if result is not None:
                    inside_api_scope = False
                    print('Exit API scope at line {}'.format(line_number))

    for api in apis:
        print('    IMGUI_API {} {}(ImGuiContext* context, {});'.format(api.result_type, api.name, api.signature))

if __name__ == '__main__':
    main()
