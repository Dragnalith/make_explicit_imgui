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
  - C function vs class
  - ListClipper construction
  - atomic for MetricsActiveAllocation

- 2022-11-01 Problem:
  - Multithread
  - Link of independent library without interop

    
