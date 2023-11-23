- An ImGuiIO instance can only be used if it is the ImGuiIO set to the current context

- 2022-10-31 Script Problem:
    - The number of argument of a call expression is different
- 2022-10-31 Integration issue:
    - ImGui::CreateContext, ImGui::DestroyContext, ImGui::GetCurrentContext, ImGui::SetCurrentContext should not be part of the explicit ImGui API
        possible solution: Move those API on the implicit API side
    - MemAlloc and MemFree depend on GImGui context from tracking memory allocation
    - ImGuiOnceUponAFrame
    - ImGuiStyle() constructor use ctx to set default style
    - ImGuiListClipper class wants to depend on the context
    - GetClipboardTextFn, SetClipboardTextFn function pointer type need a context
    - DebugLogV
    - imstb_textedit also depend on context
    - MyCallback need ImGuiContext* (imgui_demo.cpp)
    - ImGuiInputTextCallbackData need context
- 2022-11-01 Class and methods depending on GImGui:
    ImGuiIO
        -> ImGuiIO::AddInputCharacter     
        -> ImGuiIO::AddInputCharacterUTF16
        -> ImGuiIO::AddInputCharactersUTF8
        -> ImGuiIO::AddKeyAnalogEvent     
        -> ImGuiIO::AddKeyEvent
        -> ImGuiIO::AddMousePosEvent      
        -> ImGuiIO::AddMouseButtonEvent   
        -> ImGuiIO::AddMouseWheelEvent    
        -> ImGuiIO::AddFocusEvent
    ImGuiListClipper
        -> ImGuiListClipper::Begin
        -> ImGuiListClipper::End
        -> ImGuiListClipper::Step
    ImGuiStackSizes
        -> ImGuiStackSizes::SetToCurrentState
        -> ImGuiStackSizes::CompareWithCurrentState
    ImGuiInputTextState
        -> ImGuiInputTextState::OnKeyPressed
    ImGuiWindow
        -> ImGuiWindow::CalcFontSize
        -> ImGuiWindow::TitleBarHeight
        -> ImGuiWindow::TitleBarRect
        -> ImGuiWindow::MenuBarHeight
        -> ImGuiWindow::MenuBarRect
        -> ImGuiWindow::GetID
        -> ImGuiWindow::GetID
        -> ImGuiWindow::GetID
    ImGuiInputTextCallbackData
        -> ImGuiInputTextCallbackData::InsertChars
- 2022-11-01 Design Choice:
  - Physical design of file
  - Namespace ImGuiEx
  - Memory allocator explicit/implicit
  - C function vs class (problem because of imgui_internal.h)
  - OnKeyPressed
  - Style
  - atomic for MetricsActiveAllocation
  - Introduce 
    - ImGuiTextFilter::Draw
    - ImGuiListClipper
  - Macro DISABLE_IMPLICIT_API
  - Move ImGuiOnceUponAFrame
  

- 2022-11-01 Problem:
  - Multithread
  - Link of independent library without interop

- 2022-11-02: ImGuiTextFilterEx and ImGuiListClipperEx will be created to have

- 2023-05-18: Try to re-apply make_explicit_imgui.py on recent imgui codebase
  - Manual Step:
    - Move ImGuiOnceUponAFrame
    - Replace `ImGuiEx::GetFrameCount()` with `ImGui::GetFrameCount()` in ImGuiOnceUponAFrame::operator boo()
    - Remove in imgui_internal.h `inline GetKeyData(...)`
    - In imgui.cpp
      - fix `struct funcs { static bool IsLegacyNativeDupe(`
      - Remove GImGui in imgui.cpp
      - In ImGuiListClipper replace ImGuiEx::GetCurrentContext() with NULL
      - Remove ImGuiEx::SetCurrentContext
      - Replace ImGuiEx::GetAllocatorFunctions, ImGuiEx::CreateContext, ImGuiEx::DestroyContext
    - In imgui_implicit.cpp
      - Remove ShowDemoWindow, ShowAboutWindow, ShowFontSelector, ShowStyleSelector, ShowStyleEditor, ShowUserGuide

- 2023-11-21: Update some patches
  - Methodology:
    - Comment from the patch list of make_explicit_imgui.py all patchs which are failing.
    - One by one:
      - apply the patch manually
      - update the patch file using `git diff > ...`
      - uncomment the patch on the patch
      - very the patch does not fail anymore

- 2023-11-23: Changing strategy from patch management to rebase
  - Instead of applying patches stored in this repository, the new strategy is to rebase a branch containing the patches
  - The branch is expected to have:
    - a list preparatory commits to be applied before using make_explicit_imgui.py
    - then one generated commit coming from the execution of make_explicit_imgui.py
    - followed by a list of fix commits fixing the remaing issues by hand
  - The now flow is to rebase using `git rebase -i` with the following algo:
    - apply the preparatory commit
    - drop the generated commits
    - regenerate using make_explicit_imgui.py
    - apply the fix commits
