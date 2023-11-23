# Overview

The repository contains a script which can convert Dear ImGUI library to use an explicit context as argument of every API instead of a
global context as it is today.

```
// Implict API
bool state;
ImGui::Begin("My Window"e);
ImGui::Button("My Button", &state);
ImGui::End();

// Explicit API
ImGuiContext* ctx = ImGui::CreateContext();
bool state;
ImGui::Begin(ctx, "My Window"e);
ImGui::Button(ctx, "My Button", &state);
ImGui::End(ctx);
```

# Explicit branches

https://github.com/Dragnalith/imgui contains two branches `master-explicit` and `docking-explicit` which are respectively the convert to explicit API of `master` and `docking` from https://github.com/ocornut/imgui

Most of the conversion is made automatically using the make_explicit_imgui.py script in this repository. But still some commit has been written by hands.

Those two branches are made of 3 kind of commit:
- Some pre-generation commits. Those commits are written by hand and are expected to be merge into the master branch of Dear ImGui.
- One commit generated using `make_explicit_imgui.py convert` commands. This commit message of the generated commit starts with a "[generated]" tag.
- Some post-generation commits. Those commits are written by hand to fix and finish the conversion.

Rebasing `master-explicit` and `docking-explicit` simply using `git rebase` leads to too many conflicts. Instead the strategy
is to rebase only pre-generation and post-generation commits, but to regenerate the generated commit each time.

pre-generation and post-generation commits are very small compared to the generated one. They are expected to be cheap to maintain, i.e conflicting with upstream branches very rarely.

# How To Rebase

- As a prerequisite, you need to install libclang. Do so with `pip`:
```
pip install libclang
```
- To rebase `master-explicit` branch on top of the most recent `master` run this command:
```
python make_explicit_imgui.py rebase <path-to-imgui> --branch master-explicit --base origin/master
```
- To rebase `docking-explicit` branch on top of the most recent `docking` run this command:
```
python make_explicit_imgui.py rebase <path-to-imgui> --branch docking-explicit --base origin/docking
```
