# OpenRigLogic bindings build

The addon needs Epic's OpenRigLogic Python bindings (`dna` and `riglogic`). They are not in this
repo. CI builds them from source and stages them into the layout the addon's loader
(`src/addons/character_dna/bindings/__init__.py`) expects:

```
src/addons/character_dna/bindings/<os>/<arch>/py313/
    dna.py  riglogic.py  _py3dna13_2_9.<pyd|so>  _py3riglogic13_2_9.<pyd|so>
```

Those folders are git-ignored; nothing compiled is committed.

OpenRigLogic is MIT-licensed (Copyright Epic Games, Inc.); see
`src/addons/character_dna/bindings/LICENSE-OpenRigLogic.txt`.

## Inputs

- OpenRigLogic at the commit pinned as `OPENRIGLOGIC_SHA` in `.github/workflows/ci.yaml`
  (13.2.9, `main` @ `1b20901`).
- `openriglogic-blender.patch`, applied with `git apply`. It is cross-platform:
  - links `Python3::Module` instead of `Python3::Python` (Blender embeds Python statically on
    macOS; on Windows both link `python313.lib`);
  - fixes the `SWIG_TYPE_TABLE` name so wrong-type arguments raise `TypeError` instead of
    segfaulting (EpicGames/OpenRigLogic#3).
- Python 3.13 (Blender 5.x), SWIG 4.2.1 (`pip install swig==4.2.1`; 4.5.0 fails), CMake.
  Windows also needs MSVC (Visual Studio 2022+) and `pip install pefile`; macOS needs Ninja.

## Build

```
git -C OpenRigLogic apply ../bindings-build/openriglogic-blender.patch
python bindings-build/build_bindings.py --source OpenRigLogic --out staged-bindings
```

Run it with the Python 3.13 you want to build against. The script configures and builds only
`py3dna` and `py3riglogic` (tests and benchmarks off, so no network access), stages the outputs,
checks their dependencies, and imports both from the staged folder.

| Step | macOS arm64 | Windows x64 |
|---|---|---|
| Toolchain | Apple clang, Ninja | MSVC, Visual Studio generator (`-A x64`) |
| C++ runtime | system `libc++` | static (`CMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded`, `/MT`) |
| Python link | none (`-undefined dynamic_lookup`) | `python313.lib` → imports `python313.dll` |
| Output | `.dylib`, renamed to `.so` | `.pyd` directly |
| Fix-ups | `install_name_tool` to `@loader_path`, drop rpath, ad-hoc `codesign` | none |
| Check | `otool -L`: no `@rpath` or build paths | `pefile`: no `VCRUNTIME`/`MSVCP`/UCRT DLLs, imports `python313.dll` |

## Tests

- `tests_core/` runs against the staged tree with `CHARACTER_DNA_BINDINGS_DIR=staged-bindings`
  (set `CHARACTER_DNA_REQUIRE_BINDINGS=1` to fail instead of skip when they are missing).
- `scripts/ci/bindings_in_addon.py` loads them through the addon's own loader inside Blender and
  round-trips and evaluates a synthetic DNA.
