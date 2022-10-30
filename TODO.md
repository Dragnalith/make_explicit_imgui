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
- [X] Find all function definition
  - [X] Discriminate if function or method, if method find the type
  - [X] Discriminate if use implicit context or not
  - [X] Find Text location
  - [X] Replace the old api parsing with this new code
- [X] Fix function database: Need better identification for function than just name
- [X] Build call graph and find which function depends on the implicit context
- [X] Find all call location
- [ ] Apply modification
- [ ] Handle function which already have an unused ctx parameter (like in imgui_tables.cpp)