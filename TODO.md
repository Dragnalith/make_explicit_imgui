# Goal
- Automatically convert imgui repository to expose api with explicit context
  - Rename imgui.cpp and imgui.h to imguiex.cpp and imguiex.h
- Generate new imgui.h and imgui.cpp which provide the backward compatible implict context api but implemented on the explict context api

# TODO

- [X] List API
  - [X] List name
  - [X] List return type
  - [X] List parameters
  - [X] List default value
  - [X] How to deal with variadic parameters?
- [X] Whitelist API which does not need `ImGuiContext` to be added
- [X] Separate code path to find API from code path finding all function definition and call expression
- [ ] Find all function definition
  - [ ] Discriminate if function or method, if method find the type
  - [ ] Discriminate if use implicit context or not
- [ ] Build call graph and find which function depends on the implicit context
- [ ] Find all call expression
  - [ ] With source location
- [ ] Keep only call expression defined in imgui code
- [ ] Separate imguiex.h from imguiex_internal.h
- [ ] How to deal with API comment?
