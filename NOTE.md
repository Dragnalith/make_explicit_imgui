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