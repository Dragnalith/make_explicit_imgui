This script attempts to convert a Dear ImGUI repository to add API using explicit context

- Run the script
```
pip install libclang
python make_explicit_imgui.py <path-to-imgui-repository>
```
- Apply the following manual steps:
  - Update IM_FMTARGS and IM_FMTLIST
  - Rename ImGuiListClipper and ImGuiTextFilter to ImGuiListClipperEx and ImGuiTextFilterEx
    and create related subclass to keep backward compatibility
  - Move CreateContext, DestroyContext, GetCurrentContext, and SetCurrentContext to
    imgui_implicit.cpp
  - Create a new ImGuiEx::CreateContext and ImGuiEx::DestroyContext
  - Move GImGui to imgui_implicit.cpp
  - Move ImGuiOnceUponAFrame
  - Fix Build error related to the few API which cannot be converted automatically
  - Fix ShowDemo and other function in imgui_demo.cpp
  - Rewrite documentation related to CONTEXT AND MEMORY ALLOCATORS