import pathlib
import re
import argparse

#API_PATTERN = re.compile(r'^(\s*)IMGUI_API(\s*)([\w\[\]&\*]*)(\s*)(\w*)\((.*)\)\;((\s*)//(.*))?$')
#API_PATTERN1 = re.compile(r'^(\s*)IMGUI_API(\s*)([\w\[\]&\*]*)(\s*)(\w*)\((.*)\)\s*(?:IM_FMTARGS\(.\))|(?:IM_FMTLIST\(.\))\;((\s*)//(.*))?$')
API_PATTERN1 = re.compile(r'^(\s*)IMGUI_API(\s*)([\w\[\]&\*]*)(\s*)(\w*)\((.*)\).+(?:T)|(?:S)\(.\)\;\s*$')
API_PATTERN2 = re.compile(r'^(\s*)IMGUI_API(\s*)([\w\[\]&\*]*)(\s*)(\w*)\((.*)\)\;\s*$')
SIGNATURE_PATTERN1 = re.compile(r'^([\w\s\[\]&\*]*[\w\[\]&\*])\s+([\w\.]+(?:\[\])?)\s*$')
SIGNATURE_PATTERN2 = re.compile(r'^([\w\s\[\]&\*]*[\w\[\]&\*])\s+([\w\.]+(?:\[\])?)\s?=\s?[-\w\.]*\s*$')
START_NS_PATTERN = re.compile(r'^namespace\s*ImGui.*$')
END_NS_PATTERN = re.compile(r'^}.*$')

def cleanup_parenthesis_content(text):
    output = str()
    count = 0
    for c in text:
        if (c == '('):
            count += 1
        assert count >= 0, 'Error in cleaning parenthesis of the following string: {}'.format(text)
        if count == 0:
            output += c
        if (c == ')'):
            count -= 1
    return output

def parse_args(signature):
    args = []
    split_signature = cleanup_parenthesis_content(signature).split(',')
    if split_signature[0] != '':
        for s in split_signature:
            if '...' in s:
                args.append(...)
                continue
            result = SIGNATURE_PATTERN1.match(s)
            if result is None:
                result = SIGNATURE_PATTERN2.match(s)
            assert result is not None, 'Problem is parsing the following signature: {} ({})'.format(s, signature)
            args.append(result.group(2))

    return args

def match_api(text):
    text = text.split('//', 1)[0]
    result = API_PATTERN1.match(text)
    if result is None:
        return API_PATTERN2.match(text)
    return result

def test_regex_pattern():
    test_signature = [
        '',
        'ImGuiFocusedFlags flags=0',
        'ImGuiID id, const ImVec2& size = ImVec2(0, 0), bool border = false, ImGuiWindowFlags flags = 0',
    ]

    args0 = parse_args(test_signature[0])
    assert len(args0) == 0
    args1 = parse_args(test_signature[1])
    assert len(args1) == 1
    assert args1[0] == 'flags'
    args2 = parse_args(test_signature[2])
    assert len(args2) == 4
    assert args2[0] == 'id'
    assert args2[1] == 'size'
    assert args2[2] == 'border'
    assert args2[3] == 'flags'

    test_api = [
        '    IMGUI_API void          SetCurrentContext(ImGuiContext* ctx);',
        '    IMGUI_API ImGuiIO&      GetIO();                                    // access the IO structure (mouse/keyboard/gamepad inputs, time, various configuration options/flags)',
        '    IMGUI_API void          TextDisabledV(const char* fmt, va_list args)                    IM_FMTLIST(1);',
        '    IMGUI_API void          TextDisabled(const char* fmt, ...)                              IM_FMTARGS(1); // shortcut for PushStyleColor(ImGuiCol_Text, style.Colors[ImGuiCol_TextDisabled]); Text(fmt, ...); PopStyleColor();'

    ]

    result = match_api(test_api[0])
    assert result is not None
    api0 = ApiEntry(result)
    assert api0.name == 'SetCurrentContext'
    assert api0.result_type == 'void'
    
    result = match_api(test_api[1])
    assert result is not None
    api1 = ApiEntry(result)
    assert api1.result_type == 'ImGuiIO&'

    result = match_api(test_api[2])
    assert result is not None
    api2 = ApiEntry(result)
    assert api2.result_type == 'void'
    assert api2.name == 'TextDisabledV'
    assert api2.signature == 'const char* fmt, va_list args'

    result = match_api(test_api[3])
    assert result is not None
    api3 = ApiEntry(result)
    assert api3.result_type == 'void'
    assert api3.name == 'TextDisabled'
    assert api3.signature == 'const char* fmt, ...'

class ApiEntry:
    def __init__(self, re_result, line_ending = '\n', line_number = 0):
        self.line_ending = line_ending
        self.line_number = line_number;
        self.indent_size = len(re_result.group(1))
        self.spacing_1 = len(re_result.group(2))
        self.result_type = re_result.group(3)
        self.spacing_2 = len(re_result.group(4))
        self.name = re_result.group(5)
        self.signature = re_result.group(6)
        #self.args = parse_args(self.signature)

def parse_apis(apis : list[ApiEntry], buffer):
    inside_api_scope = False

    buffer.seek(0)
    line_number = 0
    while True:
        line_number += 1
        line = buffer.readline()

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

        result = match_api(line)
        if result is not None:
            apis.append(ApiEntry(result, line_ending, line_number))
        else:
            result = END_NS_PATTERN.match(line)
            if result is not None:
                inside_api_scope = False
                print('Exit API scope at line {}'.format(line_number))

    return apis
def main():
    test_regex_pattern()
    parser = argparse.ArgumentParser()
    parser.add_argument('repository_path', action='store', type=str, help="path to the root of dear imgui repository")
    args = parser.parse_args()

    root_folder = pathlib.Path(args.repository_path)

    imgui_h = root_folder / 'imgui.h'
    imguiex_h = root_folder / 'imguiex.h'
    imguiex_cpp = root_folder / 'imguiex.cpp'
    imgui_internal_h = root_folder / 'imgui_internal.h'
    imgui_cpp = root_folder / 'imgui.cpp'
    imgui_tables = root_folder / 'imgui_tables.h'
    imgui_widgets = root_folder / 'imgui_widgets.h'

    assert imgui_h.is_file()

    apis : list[ApiEntry] = []
    with open(imgui_h, 'r', encoding='utf-8') as file:
        apis = parse_apis(apis, file)
    with open(imgui_internal_h, 'r', encoding='utf-8') as file:
        apis = parse_apis(apis, file)

    with open(imguiex_h, 'w', encoding='utf-8') as file:
        file.write('#include "imgui.h"\n\n')
        file.write('namespace ImGuiEx\n')
        file.write('{\n')
        for api in apis:
            if len(api.signature) > 0:
                sep = ', '
            else:
                sep = ''
            file.write('    IMGUI_API {type}{ws}{name}(ImGuiContext* context{sep}{signature});\n'.format(type=api.result_type, ws=' '*api.spacing_2, name=api.name, sep=sep, signature=api.signature))
        file.write('}\n')
        
    with open(imguiex_cpp, 'w', encoding='utf-8') as file:
        file.write('#include "imgui.h"\n')
        file.write('#include "imguiex.h"\n\n')
        file.write('#include "imgui.h"\n\n')
        file.write('ImGuiContext*   GImGui = NULL;\n\n')
        file.write('namespace ImGui\n')
        file.write('{\n')
        for api in apis:
            if len(api.signature) > 0:
                sep = ', '
            else:
                sep = ''
            file.write('    {type}{ws}{name}({signature}) {{\n'.format(type=api.result_type, ws=' '*api.spacing_2, name=api.name, sep=sep, signature=api.signature))
            #file.write('        ImGuiEx::{name}(GImGui{sep}{args});'.format(name=api.name,sep=sep,args=', '.join(api.args)))
            file.write('    }\n')
        file.write('}\n')


if __name__ == '__main__':
    main()
