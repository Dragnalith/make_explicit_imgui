This script attempts to convert a Dear ImGUI repository to add API using explicit context

- Run the script
```
pip install libclang
python make_explicit_imgui.py <path-to-imgui-repository>
```
- Apply the following manual steps:
  - nullptr to ImGuiStyle constructor
  - nullptr to ImGuiListClipper destructor and method
  - Fix GetClipboardTextFn signature and SetClipboardTextFn