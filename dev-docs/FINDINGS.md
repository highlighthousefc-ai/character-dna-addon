# Findings

Record every verified fact, error, and dead end here.

## Day-1 spike (2026-09-21), macOS arm64

### Environment (verified)
- macOS 26.6.2 (build 25G83), Apple Silicon (arm64), Apple clang 21.0.0, Xcode installed.
- Blender **5.1.2** at `/Applications/Blender.app` (build date 2026-05-19).
  - `sys.version` = **3.13.9** (built with Clang 17), `sysconfig.get_platform()` = `macosx-11.2-arm64`.
  - Bundled Python: `/Applications/Blender.app/Contents/Resources/5.1/python/bin/python3.13`.
- Test DNAs (real binaries, not git-lfs pointers; they start with the magic bytes `DNA\0`):
  - `~/MetaHuman-DNA-Calibration/data/dna_files/Ada.dna` (73.7 MB), `Taro.dna`
  - `~/MetaHuman-DNA-Calibration/data/mh4/dna_files/Ada.dna` (67.7 MB, "mh4" variant)
  - The DNA Calibration clone is at commit `8297ff1` (2025-06-20).
- OpenRigLogic cloned to `~/OpenRigLogic` at commit `1b20901` (2026-08-28), `RL_VERSION 13.2.9`, **MIT** license (verified in LICENSE).

### License facts
- **MetaHuman-DNA-Calibration is NOT MIT.** Its `LICENSE` is Epic's proprietary "MetaHuman DNA Calibration License Agreement". Do not bundle its code or binaries (`dnacalib`, its `lib/`) without legal review. OpenRigLogic (MIT) is the library to ship.
- The DNA Calibration repo ships prebuilt `_py3dna` / `_py3dnacalib` only for Windows and Linux (Maya 2022-2024 folders). **None for macOS**, so we must compile.

### Build: macOS pitfalls (verified)
1. **Blender's Python is statically linked into the Blender executable.** There is no `libpython3.13.dylib` in the app bundle, and the bundled `lib-dynload/*.so` link only against `libSystem`. The wrappers must therefore **not** link `libpython`. They must be linked as modules (`-undefined dynamic_lookup`) so they resolve Python symbols from the host Blender process. Upstream `python/{dna,riglogic}/CMakeLists.txt` link `Python3::Python` (the full library). Linking that would load a second Python runtime into Blender and crash or misbehave.
   - Fix: a local patch (`~/OpenRigLogic-blender-macos.patch`) changes `COMPONENTS Interpreter Development` to `Development.Module`, and `Python3::Python` to `Python3::Module`, in both wrapper CMakeLists.
2. **Blender ships only `pyconfig.h`, not the full CPython headers** (`Python.h` and `patchlevel.h` are missing). Pointing CMake at Blender's interpreter fails with "missing: Python3_INCLUDE_DIRS". Dead end: `-DPython3_INCLUDE_DIR=<blender include>` also fails because `patchlevel.h` is missing.
   - Fix: install a standalone CPython **3.13.9** (`uv python install 3.13.9`, from python-build-standalone) and use it for configure and headers.
   - ABI check: the `pyconfig.h` diff between uv 3.13.9 and Blender 3.13.9 shows only OS feature macros (`HAVE_*`). The ABI-relevant macros match: `Py_GIL_DISABLED`, `Py_DEBUG` and `Py_TRACE_REFS` are all undefined, and `SIZEOF_VOID_P`/`SIZEOF_LONG` are 8. `Py_ENABLE_SHARED` differs, which is harmless for module builds.
3. The build tools come from a venv (`~/.venvs/orl-build`): cmake 4.4.3, ninja, **swig 4.2.1** (pip wheel available for macOS arm64). SWIG 4.5.0 is untested here; BUILD-BINDINGS.md says it breaks.
4. Configure command used:
   ```
   PATH=~/.venvs/orl-build/bin:$PATH cmake -S . -B build-blender51 -G Ninja \
     -DCMAKE_BUILD_TYPE=Release -DRL_BUILD_PYTHON_WRAPPER=3.13 -DBUILD_SHARED_LIBS=OFF \
     -DPython3_EXECUTABLE=$(uv python find 3.13.9) \
     -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0   # first build used 11.2; final build 11.0 to match the wheel tag
   ninja -C build-blender51 py3dna py3riglogic
   ```
   Configuring fetches googletest (network needed).
5. **Upstream CMake bug: SWIG type-table name breaks `PyCapsule_Import` and causes segfaults.** Upstream passes `SWIG_TYPE_TABLE="py3dna-13.2.9"` (quoted, with dots). SWIG stringifies it into the capsule name `swig_runtime_data4.type_pointer_capsule"py3dna-13.2.9"`. `PyCapsule_Import` splits that name on the dots, so the lookup always fails and `SWIG_GetModule` returns NULL. The first runtime type query (for example, passing an `int` or `bytes` where a `const char*` is expected, as in `reader.getMetaDataValue(0)`) then dereferences NULL and **segfaults the whole process** (Blender or plain CPython alike). Crash site: `SWIG_pchar_descriptor` <- `_wrap_DescriptorReader_getMetaDataValue`.
   - Not caused by the SWIG version: it reproduces with SWIG 4.2.1 and with SWIG 4.3.1 (dead end: switching SWIG).
   - Epic's `RigLogic.i` already works around this for riglogic's lookup of dna's types (its `GetSwigModule` uses `getattr` instead of `PyCapsule_Import`). That is why riglogic works, but `dna`'s own lookup was still broken.
   - Fix (included in the patch): `SWIG_TYPE_TABLE=py3dna_13_2_9` / `py3riglogic_13_2_9`, unquoted with no dots. After it, the same calls raise `TypeError` instead of crashing. Worth reporting upstream.
   - **Still crashes after the fix:** passing `None` to any `const char*` parameter. SWIG maps `None` to a NULL pointer by design and Epic's C++ dereferences it. **Rule for `dna_io`: validate every string argument (`str`, not `None`) before calling into `dna`.**
6. **macOS output naming:** CMake emits `_py3dna13_2_9.13.2.9.dylib` (plus symlinks). Python on macOS only imports extension modules ending in `.so`, so they must be renamed. `_py3riglogic` links `_py3dna` as a shared library via `@rpath/_py3dna13_2_9.13.dylib`, with an **absolute LC_RPATH into the build folder** (not portable). `spikes/day1/stage_bindings_macos.sh` renames to `.so`, rewrites the dependency to `@loader_path/_py3dna13_2_9.so`, deletes the rpath and **ad-hoc re-signs** (`install_name_tool` invalidates arm64 code signatures). After staging, `otool -L` shows only `@loader_path`, `libc++` and `libSystem`, with no libpython. Both modules have `minos 11.0` (built with `-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0`).
7. The build took about **30 s wall-clock** on 6 cores (M-series). No detached build needed. The full patch is in `spikes/day1/openriglogic-blender-macos.patch` (apply to OpenRigLogic `1b20901`).
8. The same staged `.so` files also import in standalone uv CPython 3.13.9, so `dna_io` unit tests can run outside Blender with that interpreter.
9. `blender --background --python x.py` **exits 0 even when the script raises**. Always pass `--python-exit-code 1` in tests and CI.

### Step results
| Step | Result | Evidence |
|---|---|---|
| 1 Build bindings for Blender's Python | PASS (with patch) | see pitfalls above |
| 2 Import inside Blender | PASS | `import dna, riglogic` inside Blender 5.1.2 background |
| 3 Load real DNA, print counts | PASS | table below |
| 4 Round trip unchanged | PASS | all 6 DNAs: every compared field identical and **output file byte-identical** to input (`spikes/day1/inspect_and_roundtrip.py`) |
| 5 Evaluate RigLogic | PASS | jawOpen drives the expected outputs (below) |
| 6 Bundle as extension wheel | PASS (headless) | `blender --command extension validate/build/install-file` into a clean profile (`BLENDER_USER_RESOURCES=<tmp>`); a fresh launch auto-enables the extension and the evaluate spike runs from the installed wheel |
| 7 Current UE (5.6-5.8) DNA | PASS | UE 5.8 archetypes, plus MetaHuman Creator DCC exports from **UE 5.6.0** and **UE 5.8.0** (head + body each): steps 3-4 byte-identical round trip, step 5 jawOpen drives FACIAL_C_Jaw. See "Step 7 (2026-09-21)" |
| 8 Upstream spikes + timings | PASS | both `specs/spikes/*.py` run unmodified in Blender |

Commands (from the repo root):
```
spikes/day1/stage_bindings_macos.sh ~/OpenRigLogic/build-blender51 ~/metahuman-addon-build/stage-macos-arm64-py313
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python-exit-code 1 \
  --python spikes/day1/run_in_blender.py -- ~/metahuman-addon-build/stage-macos-arm64-py313 \
  spikes/day1/inspect_and_roundtrip.py <in.dna> <out.dna>      # or probe_eval_jaw.py / specs/spikes/*.py
```

### DNA facts (verified with the reader)
| File | dbName | fmt gen/ver | LODs | meshes | joints | raw ctl | GUI ctl | BS channels | BS targets | anim maps | PSDs | joint groups | RBF |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DNACalib `dna_files/Ada.dna` | DHI | 2/1 | 8 | 50 | 865 | 258 | 168 | 687 | 763 | 82 | 476 | 125 | 0 |
| DNACalib `dna_files/Taro.dna` | DHI | 2/1 | 8 | 50 | 865 | 258 | 168 | 687 | 763 | 82 | 476 | 125 | 0 |
| DNACalib `mh4/dna_files/Ada.dna` | MH.4 | 2/1 | 8 | 50 | 870 | 269 | 174 | 782 | 858 | 82 | 545 | 124 | 0 |
| UE 5.8 `ArchetypeDNA/SKM_Face.dna` | MH.6 | 2/**5** | 8 | 50 | 870 | 263 | 174 | **0** | 0 | 82 | 545 | 122 | 1 |
| UE 5.8 `ArchetypeDNA/SKM_Body.dna` | MHB.1 | 2/5 | 4 | 4 | 342 | 176 | 0 | 0 | 0 | 0 | 0 | 72 | **72** |
| UE 5.8 `ArchetypeDNA/body_head_combined.dna` | MHB.1 | 2/5 | 4 | 4 | 342 | 176 | 0 | 0 | 0 | 0 | 0 | 72 | 72 |
- UE 5.8 archetypes are in `/Users/Shared/Epic Games/UE_5.8/Engine/Plugins/MetaHuman/MetaHumanCoreTechLib/Content/ArchetypeDNA/` (Epic-owned: never commit them).
- Head LOD0 (all face DNAs): 9 meshes, `head_lod0_mesh` 24049 vertices. LOD mesh counts per LOD: 9, 9, 8, 7, 5, 4, 4, 4. Face DNAs have 50 meshes in total across LODs.
- Blend shape targets exist only on LOD0 meshes (Ada: head 681, teeth 2, eyeL 2, eyeR 2, cartilage 76).
- **The UE 5.8 face archetype has zero blend shape channels.** Its expressions are joints-only plus animated (wrinkle) maps. An importer must not assume blend shapes exist.
- Body DNA raw controls are quaternion components (e.g. `calf_l.qx`) feeding the RBF solvers. Driving index 0 to 1.0 (what the upstream spike does) is not a meaningful pose, so **RBF evaluation is effectively untested** (open item).
- Coordinate system on every file: x=0 (left), y=2 (up), z=4 (front), so **Y-up**. Translation unit 0 = cm, rotation unit 0 = degrees. Enum values: `Direction_left=0, right=1, up=2, down=3, front=4, back=5`, `TranslationUnit_cm=0, m=1`, `RotationUnit_degrees=0, radians=1`. No Z-up DNA available to test the other convention yet.
- Metadata: face DNAs have `archetype=Eu`, body has none. **API note:** `getMetaDataValue(key)` takes the key string, not an index.
- The old-format (gen2/v1) files are written back as v1 (byte-identical), so the writer preserves the source format version.

### RigLogic evaluation facts (verified)
- Joint outputs: **9 floats per joint** (tx ty tz rx ry rz sx sy sz); length = 9 x jointCount.
- With all raw controls at 0, every joint output (including the scale columns) is 0. **Outputs are deltas from the neutral pose, not absolute transforms** (VERIFY how RigLogic `Configuration` affects this before building the bone applier).
- Evaluation is deterministic (same inputs give bit-identical outputs).
- `CTRL_expressions.jawOpen = 1` on Ada: blend shape `jaw_open` = 1.0 (the only non-zero channel). Animated maps `head_cm1_color.head_wm1_jawOpen` and `head_wm1_normal.head_wm1_jawOpen` change. 647 joints move; `FACIAL_C_Jaw` and `FACIAL_C_LowerLipRotation` change rotation by |23.6| deg on X (sign not checked). On the UE 5.8 face: `FACIAL_C_Jaw` |dRx| = 22.2 deg, 667 joints move, no blend shapes.

### Performance baseline (Blender 5.1.2, Apple Silicon, from `specs/spikes/spike_read_evaluate.py`, all controls random)
| DNA | `calculate()` ms/frame | copy joint+BS outputs to lists ms/frame |
|---|---|---|
| Ada (DHI) | 0.13-0.14 | 0.11 |
| Ada (MH.4) | 0.136-0.139 | 0.11-0.12 |
| UE 5.8 SKM_Face | 0.134 | 0.10 |
| UE 5.8 SKM_Body | 0.010 | 0.04 |
- Load times: Ada (73 MB) about 0.1 s with `DataLayer_All`. Unchanged write about 0.8 s (Ada), 0.1-0.3 s (UE 5.8 files).
- `writer.setFrom(reader)` + `setVertexPositions(mesh, [[x,y,z], ...])` edit round trip works (`spike_roundtrip_write.py`: +1.000 on vertex 0 Y, the rest identical) on both Ada variants.

### Extension packaging facts (verified in Blender 5.1.2 source + run)
- Manifest `schema_version = "1.0.0"`, with `platforms = ["macos-arm64"]` and `wheels = ["./wheels/<file>.whl"]`. Wheel filenames must have 5-6 dash-separated parts and use forward slashes. Blender maps `macosx_11_0_arm64` to `macos-arm64` (`blender_ext.py: blender_platforms_from_wheel_platform`).
- **All enabled extensions' wheels are unpacked into one shared directory**, `<user extensions>/.local/lib/python3.13/site-packages`. Blender picks one wheel per distribution name (highest version). So top-level modules named `dna` / `riglogic` would **collide with any other extension shipping the same names** (e.g. another MetaHuman addon). No validator rule rejects top-level modules inside wheels. The real risk is this name clash, so this corrects the claim in `BUILD-BINDINGS.md`.
- The SWIG wrappers already have an upstream hook for isolation: `dna.py`/`riglogic.py` look for a `sys.meta_path` entry named `IsolatedModuleLoader` with `load_module(name, rootdir=...)` / `get_module_rootdir(name)`. It lives in Epic's generated code, not in Poly Hammer's. Using this hook (instead of the spike's top-level wheel) is the likely path to collision-free packaging. **Decide before feature work.**
- Spike extension: `spikes/day1/ext/` (manifest + `__init__.py` that only imports). Wheel built by `spikes/day1/make_wheel.py` (dist `openriglogic_bindings`, 13.2.9, `cp313-cp313-macosx_11_0_arm64`, about 780 KB zipped).
- `blender --command extension install-file -r user_default -e <zip>` installs and enables headlessly. `BLENDER_USER_RESOURCES=<dir>` gives a fully isolated clean profile.

### Not done / open
- DNACalib not built: proprietary license, legacy (not updated for UE 5.6+), and not needed, since the `dna` writer handled every edit tried so far.
- Only macOS arm64 + Blender 5.1 (Python 3.13). Not built: Windows x64, Linux x64, macOS x64, or Blender versions with other Python versions (e.g. 4.5 LTS, which ships **VERIFY** 3.11).
- No user-exported MetaHuman Creator 5.6-5.8 DNA tested (only Epic's 5.8 archetypes).
- RBF (body) evaluation not meaningfully exercised.
- GUI install through Preferences not done by a human (headless install verified).

## Fork investigation (2026-09-21), details in `docs/02-fork-and-windows.md`
- `poly-hammer/meta-human-dna-addon` was renamed to `poly-hammer/character-dna-addon`. LICENSE.md is verbatim GPL-3.0 (pyproject's LGPLv3 classifier is a stale mistake). Cloned read-only to `~/character-dna-addon` (remote `upstream`, HEAD `61525f6`).
- Its compiled bindings **and** the `_riglogic_blender` native runtime come from a **private** repo (`poly-hammer/character-dna-bindings`). No source or binaries are public. Live evaluation in the free addon requires `_riglogic_blender`.
- `editors/` is a submodule to a **private** Pro repo. "Pro" = whether `editors/__init__.py` exists; the public code has no license check.
- Their `bindings/__init__.py` already uses Epic's `IsolatedModuleLoader` hook, strips bare `dna`/`riglogic` names and nulls `__file__`. This is the name-collision fix.
- Correction to BUILD-BINDINGS.md: Blender 5.1's "Policy violation with top level module" is a **UI warning** (`addon_utils._extensions_warnings_get`), not a validator rejection. It only covers modules whose file lies inside an extension's own folder, not wheel-installed ones in `.local/site-packages`.
- `blender --command extension build --split-platforms` exists in 5.1.
- Their `dna_io` imports `bpy`. Sentry reports to `sentry.poly-hammer.com` (consent-based).
- Their `tests/test_files/dna/` holds MetaHuman Creator exports from **UE 5.6.0** (`ada`) and **UE 5.8.0** (`default`), as LFS objects (~117 MB, not pulled).
- The `None` → `const char*` segfault reproduces with no input files (an in-memory DNA); it affects `setName`, `setJointName`, `setMetaData(key)`, `getMetaDataValue`, `FileStream(path)`. Issue drafts are in `docs/drafts/`.
- Blender's download server returns 403 to scripted (urllib) requests, so the contents of the Windows zip are unverified.

## Step 7 (2026-09-21): MetaHuman Creator exports
Inputs: the 4 git-lfs test DNAs from `poly-hammer/character-dna-addon` @ `61525f6`, `tests/test_files/dna/{ada,default}/{head,body}.dna`, pulled with `git lfs pull --include="tests/test_files/dna/**"` into `~/character-dna-addon` (outside our repo; Epic-generated data, not to be committed). `ExportManifest.json`: `ada` = UE 5.6.0 (2025-06-26), `default` = UE 5.8.0 (2026-06-08).

| File | sha256 (prefix) | dbName | fmt gen/ver | joints | raw ctl | GUI ctl | BS channels | BS targets | PSDs | RBF | round trip | jawOpen |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ada/head (5.6) | e6e79729 | MH.6 | 2/5 | 870 | 263 | 174 | 782 | 858 | 545 | 1 | byte-identical | 1 BS channel, 2 anim maps, 667 joints; Jaw dR x 22.8 |
| ada/body (5.6) | a1426858 | MHB.1 | 2/5 | 342 | 176 | 0 | 0 | 0 | 0 | 72 | byte-identical | n/a |
| default/head (5.8) | b6c9b804 | MH.6 | 2/5 | 870 | 263 | 174 | 782 | 858 | 545 | 1 | byte-identical | same pattern; Jaw dR x 22.2 |
| default/body (5.8) | 261aa780 | MHB.1 | 2/**7** | 342 | 176 | 0 | 0 | 0 | 0 | 72 | byte-identical | n/a |

Facts:
- DCC exports **do carry blend shapes** (782 channels / 858 targets, 737 on head_lod0_mesh), unlike the UE 5.8 archetype `SKM_Face.dna` (0). The importer must handle both.
- Blend shapes exist only on LOD0 meshes.
- The UE 5.8 **body** export uses DNA format **version 7**; OpenRigLogic 13.2.9 reads and rewrites it byte-identically. Heads are still version 5.
- Head name is `'Archetype'` even in a user export; the body name is empty. Don't use `getName()` as the character name; use `ExportManifest.json` `metaHumanName` when present.
- Load times in Blender: head about 0.1 s, body about 0.01 s; head write about 0.6 s; full compare about 1.1 s.
- Setup note: `brew install git-lfs` (3.8.0); `git lfs install --local` only (it offered `--system`, not used).

## Fork cleanup (2026-09-21)
Fork: https://github.com/highlighthousefc-ai/character-dna-addon (public). Local clone `~/character-dna-addon`, remotes `origin` (fork) and `upstream` (Poly Hammer). Branch `cleanup/strip-upstream`, 7 commits on top of upstream `61525f6`. Repo-local git identity: `highlighthousefc-ai <242834748+highlighthousefc-ai@users.noreply.github.com>` (GitHub noreply, so the personal email isn't published).

Verified after the pass: the addon registers/unregisters headless in Blender 5.1.2 (25 operators); `extension validate` passes; `tests_core` 5/5 pass with the staged macOS bindings (2 pass, 3 skip without them); the no-bpy guard fails when a `bpy` import is planted in `dna_core` (mutation check); ruff findings in inherited code are unchanged vs upstream (6 in `src`, ruff 0.16.8).

Dead ends / known gaps:
- Upstream is not lint-clean with its own locked ruff 0.15.8 (57 findings across src/tests/scripts), so CI reports inherited findings without failing and enforces ruff only on our new code.
- The inherited Blender test suite (`tests/`) is **not runnable yet** and partly **still assumes Pro code**: fixtures set `output.auto_update_lods` (property removed), calibrator tests expect Pro LOD propagation, and `test_native_runtime.py` imports `character_dna.editors...`. It also needs bindings, the private `_riglogic_blender` runtime and the LFS DNAs. It needs a rework pass before it goes in CI.
- `tests/utilities/rbf_editor.py` was kept **unread**, because the free `test_body_rig_logic.py` imports it.
- `paths_exclude_pattern` still excludes `bindings/windows|macos|linux`; per-platform packaging of bindings is part of the bindings build/package step (§5.3), not this pass.
- Branding (name, maintainer, docs URLs, README) is untouched until the one-commit rename.

### First CI run (2026-09-21), PR highlighthousefc-ai/character-dna-addon#1, run 35667350685: all 7 jobs pass
- The register smoke test works with the PyPI `bpy` module on windows-latest and macos-latest: bpy 5.1.* resolved to Blender 5.1.2 and bpy 5.2.* to 5.2.2 LTS, both on Python 3.13.15. 25 operators register, then unregister.
- `dna_core` on both OSes: the 2 no-bpy guard tests pass and the 3 round-trip tests skip (no bindings in CI yet).
- Lint: 57 inherited findings reported but not failing; our code and formatting are clean.
- Actions were enabled on the fork by default (no manual enable needed).
- Notice: `ubuntu-latest` moves to Ubuntu 26 from 2026-10-19 (lint job only).

## Windows bindings in CI (2026-09-21), PR highlighthousefc-ai/character-dna-addon#2, run 35669438203: all 9 jobs pass
Build (`bindings-build/build_bindings.py`, windows-latest):
- Visual Studio 18 2026 generator, MSVC 19.51.36256, CMake 4.4.3, SWIG 4.2.1 from pip (`swig4.0.exe` in Scripts), CPython 3.13.15 from `actions/setup-python` (its `include/` + `libs/python313.lib`). Build about 3.5 min.
- `-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded` works as is (OpenRigLogic's `cmake_minimum_required(3.15)` means CMP0091 is NEW); no CMake patch needed.
- The unchanged spike patch applies on Windows **once `core.autocrlf=false`** (dead end: the runner's default autocrlf=true made `git apply` fail with "patch does not apply").
- UseSWIG writes `_py3dna13_2_9.pyd` / `_py3riglogic13_2_9.pyd` under `Release/` (multi-config); the `VERSION`/`SOVERSION` properties don't change the name. No rename, no rpath fix-up, no signing.
- pefile imports: **both `.pyd`s import only `kernel32.dll` and `python313.dll`**, so no VCRUNTIME/MSVCP/UCRT and no dependency of riglogic on the dna `.pyd` (unlike macOS, where `_py3riglogic` links `_py3dna`). Each `.pyd` statically contains its own copy of the DNA library.
- `-DRL_BUILD_TESTS=OFF -DRL_BUILD_BENCHMARKS=OFF` avoids the googletest download (no network needed at configure).
- The same script's macOS path reproduces the spike build locally (same `@loader_path` links, tests pass).

Runtime:
- tests_core on Windows with bindings required: 9/9 pass (round trip byte-identical; synthetic jawOpen 0/0.5/1 gives jaw rx 0/12.5/25, deterministic). **Objects cross between the two `/MT` modules safely** (a reader from dna passed into RigLogic from riglogic), which the plan had flagged as VERIFY.
- The addon's own loader loads them from `bindings/windows/x64/py313/` under the bpy module 5.1.2 and 5.2.2 (CPython 3.13.15) and in the **real Blender 5.1.2 Windows build (Python 3.13.9, MSC v.1944)**. No bare `dna`/`riglogic` left in `sys.modules`; `platform.processor()` gives `x64`. Built against 3.13.15 headers, runs on Blender's 3.13.9 (same `python313.dll` ABI).

Blender 5.1.2 Windows zip, verified (it resolves the §5.1 VERIFY items):
- `python313.dll` **and** `python3.dll` next to `blender.exe`, and again in `5.1/python/bin/` with `python.exe`. EXT_SUFFIX `.cp313-win_amd64.pyd`.
- `5.1/python/` has only `bin`, `DLLs`, `lib`: **no `include/`, no `libs/python313.lib`, no `pyconfig.h`**. Blender can't be the build SDK on Windows, so a python.org / setup-python 3.13 is required (on macOS it ships at least `pyconfig.h`).
- Top level has `ucrtbase.dll` and a `blender.crt` folder (probably the VC++ runtime as a side-by-side assembly, not inspected); `blender.shared/` has no VC++ runtime DLLs. Our `/MT` build doesn't depend on either.
- download.blender.org serves the zip (414 MB) to `curl`; the earlier 403 was only for Python's urllib user agent. Cached in CI with `actions/cache`.

## macOS bindings in CI, per-platform packaging, clean install (2026-09-21)
PR #2 merged as `f2c519f` (the first `gh pr merge` hit a GitHub 502 and left the PR stuck in "merge already in progress"; the REST merge endpoint `PUT /repos/.../pulls/2/merge` worked). Follow-up: PR highlighthousefc-ai/character-dna-addon#3, run 35671801231, all 11 jobs pass.

macOS bindings job (macos-latest, arm64): the same `build_bindings.py`; AppleClang 21.0.0, python.org framework CPython 3.13.15, SWIG 4.2.1 and Ninja from pip, about 1 min. **Dead end in my own check:** `otool -L` prints the library's own path first, and on runners that is under `/Users/runner/`, which my "absolute build path" check flagged. Fixed to check only the linked libraries. `dna_core` 9/9 now pass on macOS with bindings required.

`--split-platforms` (read in Blender 5.1 `bl_pkg/cli/blender_ext.py`, then confirmed by building):
- It **filters only wheels** by platform tag (`build_paths_filter_by_platform`). Every other file goes into every platform's zip: a Windows zip built from a tree with macOS bindings contained the macOS `.so` files.
- It writes a `[build.generated]` block into each zip's manifest: `platforms = ["<platform>"]` and the matching `wheels`. Zip names are `<id>-<version>-<platform with _>.zip`.
- It refuses to run if the manifest declares no `platforms`.
- The manifest tags `windows-x64` and `macos-arm64` work: each zip gets exactly its own tag and its own pyufbx wheel (`win_amd64` / `macosx_11_0_arm64`).
- So `scripts/ci/package_extension.py` builds from a tree holding only one platform's bindings, keeps only that platform's zip, and verifies it. The manifest's `paths_exclude_pattern` no longer excludes `bindings/<os>/`.

The zips (CI artifacts `character_dna-windows-x64` / `character_dna-macos-arm64`):
| | macOS arm64 | Windows x64 |
|---|---|---|
| File | `character_dna-0.13.7-macos_arm64.zip` | `character_dna-0.13.7-windows_x64.zip` |
| Size | 11.89 MB (11,894,392 B) | 11.91 MB (11,910,150 B) |
| Files | 386 | 386 |
| Bindings | `bindings/macos/arm64/py313/`: `_py3dna13_2_9.so` 1.91 MB, `_py3riglogic13_2_9.so` 2.66 MB, `dna.py`, `riglogic.py` | `bindings/windows/x64/py313/`: `_py3dna13_2_9.pyd` 1.46 MB, `_py3riglogic13_2_9.pyd` 1.56 MB, `dna.py`, `riglogic.py` |
| Wheel | `pyufbx-...-macosx_11_0_arm64.whl` 0.88 MB | `pyufbx-...-win_amd64.whl` 0.79 MB |
- Shared content (381 files, byte-identical once the Windows package job also sets `core.autocrlf=false`): `resources/poses` 312 JSON files (7.0 MB zipped / 15.4 MB raw), `resources/blends` 2 files (2.2 / 14.5 MB), `resources/mappings` (0.6 / 4.7 MB), images, rig definitions, and the Python package (including `dna_core`). No tests, `__pycache__` or other platform's files.
- **Dead end:** before the autocrlf fix, the Windows zip carried CRLF copies of the text resources (poses 15.83 MB raw vs 15.42 MB).

Clean install (the last unverified item in the plan), both platforms, real Blender 5.1.2:
- `blender --command extension install-file -r user_default -e <zip>` into an empty `BLENDER_USER_RESOURCES` profile, then a normal (not `--factory-startup`) background launch.
- The extension is enabled as `bl_ext.user_default.character_dna` from `<profile>/extensions/user_default/character_dna`, and the bindings load from `.../bindings/<os>/<arch>/py313` inside it.
- The pyufbx wheel installs its `ufbx` module (not `pyufbx`) into `<profile>/extensions/.local/lib/python3.13/site-packages`.
- 25 operators register; round trip and jawOpen 0/0.5/1 give 0/12.5/25.
- **No path hacks:** no `sys.path` entries into the checkout (apart from Blender itself, which sits in the CI workspace), no bare `dna`/`riglogic` in `sys.modules`, and no Blender extension-policy warnings (`addon_utils._extensions_warnings_get`). The check fails when a `sys.path` insert plus a top-level import is planted in the installed extension (mutation-tested locally).
- Dead end in my own check: the first CI version flagged Blender's own script paths, because the downloaded Blender lives inside the checkout. It now ignores paths under Blender's install root.

## GUI check of the inherited free base (2026-09-21), macOS, Blender 5.1.2
Setup: the CI-built `character_dna-0.13.7-macos_arm64.zip` (PR #3 artifact, sha256 `6d96a23b...`) installed with `extension install-file` into an empty `BLENDER_USER_RESOURCES` profile. Blender launched **windowed** (not `--background`) from that profile. Test data: UE 5.6 `ada/head.dna` (+ `body.dna` via the dialog's Include Body default) from `~/character-dna-addon`'s LFS files.

How it was driven: I can't move the macOS mouse, so a driver script (scratchpad `gui/gui_check.py`, not committed) ran in the GUI session with `--enable-event-simulate`. That sends mouse and keyboard events through Blender's real event loop:
- **Simulated keys:** Esc for the splash, N for the sidebar, a mouse click on the "Character DNA" sidebar tab, F3 menu search, Return on the "File > Import > MetaHuman DNA (.dna)" entry, and Return in the import file browser.
- **Set by script** (logged as such): the file browser's folder and filename, the viewport framing, choosing a face pose (the same property the pose dropdown sets), and the output folder.
- **Export:** called the export operator the way its button does (`INVOKE_DEFAULT`).

Screenshots came from `screen.screenshot`. Driver dead ends:
- `event_simulate` has no "TAP" value (send PRESS + RELEASE).
- Every event needs its own x/y (the default 0,0 sends keys to the bottom-left corner).
- A fresh profile shows the splash, which swallows the first key.
- `Region.active_panel_category` is read-only, and Ctrl+wheel didn't cycle the tabs, so the tab has to be clicked.
- `temp_override(screen=...)` is refused for the file browser's temporary window.
- The F3 search field looked empty in screenshots even though its top hit was the requested entry.

Results:
| Step | Result |
|---|---|
| Extension installs and enables in a clean profile | PASS |
| Character DNA sidebar tab | Present. **Before import it shows only a collapsed "Rig Instances" panel**, no import button or hint of what to do. |
| **Import as shipped** | **BROKEN: disabled.** "File > Import > MetaHuman DNA (.dna)" is greyed out and Return does nothing, with no message. `ImportCharacterDna.poll` → `utilities.dependencies_are_valid()` requires the **closed-source `_riglogic_blender` native runtime**, not just the dna/riglogic bindings. So the forked free base **cannot import at all**; previously we only knew live evaluation was blocked. The file handler (drag-and-drop) uses the same operator (VERIFY). |
| Import with the check overridden in memory (diagnostic only, no code change) | Works: head + body + face board in about 10 s (459 objects; instance "ada", `ada_head_lod0_mesh`, `ada_body_lod0_mesh`, rigs, `ada_face_gui`). The head looks correct from the front. **But the user then gets a full Python traceback popup** ("Native runtime unavailable: Native runtime is not installed in .../bindings/macos/arm64/py313"), because `ImportCharacterDna.execute` ends with `force_evaluate()` → `RigInstance.evaluate()` → `engine.install()` raising. |
| Facial pose | Picking "Dimpler_Jaw_Open" in the Face Board pose picker **moves 13 face-board controls** (e.g. `CTRL_C_jaw`, `CTRL_R_mouth_purseD`), **but the face mesh does not change**: 0.0 max vertex shift, 0 non-zero shape keys, and it looks visibly neutral. No error is shown for this; it silently does nothing. Same cause (no native runtime). |
| Animate / Bake | **Not exercised.** Keying the face board and baking weren't driven in this pass. The bake operators sample fcurves and call RigLogic from Python, so they may not need the native runtime (VERIFY in a later pass). |
| Export (Output panel, Head, method Calibrate, "Only Component" button equivalent) | **Writes `head.dna`**, then raises the same "Native runtime unavailable" error (from `force_evaluate()` after the write, `operators.py:1266`). A user would see an error even though the export succeeded. |
| Round trip (exported vs original UE 5.6 Ada head) | Not byte-identical (first difference at byte 87005; same size, 53,620,061 B). Blend shape channels 782/782, joints 870/870, meshes 50/50. **All 858 blend shape targets identical** (vertex indices and deltas, max diff 0), including `jaw_open` (19,068 verts), `eye_blink_L`, `mouth_cornerPull_left`, `brow_raiseIn_L`. Head LOD0 vertex positions max diff 4.6e-5 cm (float round-off through Blender); neutral joint translations identical. The pose was *not* baked into the export (nothing evaluated), so this is an unchanged-character round trip. |

UI problems noticed (documented, not fixed):
1. The import is greyed out with no explanation (no `poll_message_set`), and there's no import entry in the sidebar.
2. Raw Python tracebacks shown to users after import and export (the error report popup covers the viewport until the mouse moves).
3. The pose picker silently does nothing to the mesh.
4. **"Migrate Legacy Data — Legacy data detected. You must migrate your .blend file then save it"** is shown on a freshly imported, never-saved scene. Probably a false positive (VERIFY `MIGRATABLE_DATA_KEYS` detection).
5. Output panel: before a folder is set, "Only Component" / "MetaHuman Cr..." are disabled with a red "Must set an output folder" (OK). Button labels are truncated at the default sidebar width ("MetaHuman Cr...", output list names "car..."/"eye...").
6. Import leaves Blender in **Pose Mode on the face board**, which is surprising, and "Frame Selected" then frames the board rather than the head.
7. The import dialog's LOD list shows LOD0 ticked but greyed and LOD1-7 unticked, with no hint why LOD0 can't be unticked.

Root cause for 1-3 and the pose failure: `_riglogic_blender` (closed source, private repo). The decided fix is the Python-evaluation path (§4 option 1), which must also remove the native requirement from `dependencies_are_valid()` and from `force_evaluate()`/`engine.install()`.

## Python evaluation engine replaces the native runtime requirement (2026-09-21)

Branch `feature/python-evaluation-engine` (off `ci/macos-bindings-and-packaging` in `~/character-dna-addon`), not yet a PR. Resolves the root cause identified in the GUI check above: `runtime/engine.py`'s `install()`/`capability()` required Poly Hammer's closed-source `_riglogic_blender` native module, which we don't have and can't get. Replaced with our own evaluator built on `dna_core` and Epic's bindings directly (the approach chosen back in Q7, ~0.13 ms/frame per the Day-1 probe).

**This turned out to be a small, surgical patch, not a rewrite.** Upstream's own architecture already isolates "the native module" behind one indirection point: `bindings.load_native_runtime()` returns *a module object*, and `runtime/engine.py`, `runtime/frame.py` and `runtime/authoring.py` call a fixed set of functions on whatever that module is (`capabilities`, `load_model`, `create_session`, `describe`, `create_frame_plan`, `evaluate_frame`, `control_snapshot`, `transform_into`). None of `engine.py`, `frame.py`, `authoring.py`, `controller.py`, `rig_instance.py`, `operators.py`, or any UI file needed to change — they already only know about "the native module" through that narrow interface.

**Files touched (58 lines changed across 3 files, plus one new 448-line file):**
- **New: `runtime/python_evaluator.py`.** Implements the exact interface above in pure Python: numpy for the linear algebra, `dna_core.load()` + `dna_core._bindings.riglogic_module()` (new resolver, see below) for the DNA/RigLogic calls. No `bpy`/`mathutils`/`bmesh` imports (grep-confirmed), so it's testable outside Blender like `dna_core`. Key pieces:
  - `load_model`/`create_session`/`describe`: read the DNA via `dna_core`, build a `riglogic.RigLogic` with the same `Configuration()` upstream used pre-native (quaternion rotation for body, defaults for head), probe LOD0 once for output-array sizes.
  - Rotation math re-derived and verified against Blender's own conventions, checked empirically in Blender first (not assumed): `foreach_get("matrix", ...)` fills **column-major** 4x4s, and Blender's "XYZ" Euler order is **R = Rz @ Ry @ Rx**. `euler_xyz_to_matrix`/`matrix_to_euler_xyz`/`quaternion_to_matrix`/`matrix_to_quaternion`/`quaternion_multiply` implement exactly those conventions in numpy.
  - `transform_into`: same math as the old (pre-native, commit `c3827cb^`) `update_head_bone_transforms`/`update_body_bone_transforms` — rest pose + delta, then `rest_to_parent_inverse @ LocRotScale(...)` for the pose basis — but vectorized over all joints at once instead of per-bone Python loops.
  - `evaluate_frame`: reads GUI/raw controls from the captured RNA buffers (face board bone locations, driver-bone quaternions via `_local_quaternions`, eye-aim via `_eye_aim_controls` reimplementing the old `get_head_gui_control_values_from_eye_aim` trig), calls `rig_logic.calculate()`, and writes joint/shape/animated-map outputs into the shared SDK buffer at the same offsets `engine.py` already expects.
- **`bindings/__init__.py` (32 lines, all in `load_native_runtime()`):** replaced the SWIG `.pyd`/`.so` loader for `_riglogic_blender` with `return python_evaluator` (module object satisfying the same interface). Nothing else in the file changed (the `IsolatedModuleLoader`, DLL-directory and validator-hiding code stays, since `dna`/`riglogic` are still loaded that way).
- **`dna_core/_bindings.py` (+11 lines):** added `riglogic_module()`, mirroring the existing `dna_module()` resolver (isolated copy inside the addon, or bare `import riglogic` outside it).
- **`utilities/misc.py` (`dependencies_are_valid()`, ~11 lines):** now checks `runtime.engine.capability()[0]` (which calls our `load_native_runtime()` and validates its function set) instead of separately calling the old `load_native_runtime()` and catching exceptions. Behaviourally equivalent gate, new source.

**Verified, headless (real UE 5.6 Ada head, `~/character-dna-addon/tests/test_files/dna/ada/head.dna`):**
- `dependencies_are_valid()` → `True`; `engine.capability()` → `(True, 'Native runtime available')` (message string kept as-is; renaming it is cosmetic/out of scope).
- Import completes in ~10 s, `engine.active(instance)` is `True`, status `"Native"`, 3 carriers installed (`ada_head_native`, `ada_body_native`, `ada_switches_native`), **no exceptions**.
- Moving the face-board `CTRL_C_jaw` bone to `location.y = 1.0` and calling `view_layer.update()`: **head mesh vertices shift up to 3.04 cm** (was 0.0 cm before this change), `FACIAL_C_Jaw` pose-bone rotates to `(0.398, -0.008, 0.011)` rad.
- **RigLogic computation cross-checked against the Day-1 spike's direct-bindings reference call**: peeking at the live evaluation context's published output buffer showed blend-shape channel `jaw_open` (index 619) = `1.0`, matching a fresh `riglogic.RigLogic(...).calculate()` call with `jawOpen=1.0` set directly on the same DNA (`1.0`, exact match). Confirms the evaluator's numeric path (not just "something moved") is correct.
- Per-frame cost with both head and body live-evaluating: **~18-19 ms** per `view_layer.update()` (includes Blender's own dependency-graph overhead, not just RigLogic's ~0.13 ms `calculate()`).
- Export (`character_dna.export_selected_component`) now returns `{'FINISHED'}` with **no exception** (previously crashed with "Native runtime unavailable" from the post-write `force_evaluate()`).
- **Dead end while diagnosing "0 shape keys moved":** the mesh vertex shift (3 cm) is real, but reading `head.data.shape_keys.key_blocks[...].value` (the *undriven* datablock, via plain `bpy.data`) always shows 0 regardless of evaluation — driven shape-key values only exist on the *evaluated* copy (`head.evaluated_get(depsgraph).data.shape_keys...value`), same pattern as evaluated mesh coordinates needing `to_mesh()`. Not a bug in the new evaluator; my first diagnostic script was reading the wrong copy.
- **Separate, pre-existing finding (not caused by this change, not fixed):** blend shapes are never actually imported into the Blender scene in this fork's current state. `properties.py`'s `import_shape_keys` checkbox defaults to `False`, and even set to `True` explicitly nothing changes — `dna_io/misc.py:create_shape_key()` and `dna_io/importer.py`'s `set_shape_key()` have **zero callers** anywhere in the package (`grep` confirmed). So `head_shape_key_blocks` always reports "did not cache 816 shape key blocks... they are not in the scene" and no shape-key output drivers ever get installed, independent of which evaluator is behind `engine.py`. The RigLogic *computation* of blend-shape values is correct (verified above); only the Blender-side "create a ShapeKey block and drive its value" wiring is missing/dead. Flagging for a future pass; out of scope here (the task was the evaluation engine, not shape-key import).

**Verified, GUI (`--enable-event-simulate` driver, same technique as the earlier GUI-check pass, fresh throwaway profile, freshly-packaged zip including `python_evaluator.py`, real Blender 5.1.2 windowed):**
- `dependencies_are_valid() = True` logged before import; **Import DNA is no longer greyed out**, no diagnostic override needed this time.
- Import completes (13.7 s, 462 objects) with **no error popup** (screenshot: clean viewport, Output panel visible, no traceback).
- Picking "Dimpler_Jaw_Open" in the Face Board pose picker: **max vertex shift 2.66 cm**, and the screenshot **visibly shows the jaw open with the mouth cavity/tongue exposed**, versus the closed neutral mouth in the pre-pose screenshot. This is the same check that showed 0.0 cm / a static closed mouth before this change.
- Export via the Output panel (`export_selected_component`, `INVOKE_DEFAULT`) returns `{'FINISHED'}`, **no exception**, "Only Component" / "MetaHuman Cr..." buttons are enabled post-export, `export/head.dna` written.
- Round-trip sanity check (exported vs. original `ada/head.dna`, `head_lod0_mesh` vertex positions via `dna_core`): identical up to float round-off (max diff 4.6e-5 cm, same magnitude as the earlier byte-for-byte comparison), **by design**: the "Calibrate" export captures the mesh's *rest/bind-pose* geometry (skin-cluster basis), not a baked snapshot of the currently-posed viewport shape, so posing the jaw via bones and then exporting is expected to leave `vertexPositions` unchanged — this matches DNA semantics (pose lives in joint transforms/blend-shape *deltas* applied at runtime, not in the exported rest mesh) and is consistent with what the pre-native-fix GUI check already found and correctly described as "unchanged-character round trip." Because blend-shape import/drive is the separate dead-code gap noted above, there was no driven shape-key value available to sanity-check on this particular DNA/pose combination; the meaningful check here is that RigLogic's computed blend-shape output matches the reference bindings call (done, headless, see above) and that export completes cleanly with the posed rig instead of crashing.

**Remaining UI issues from the earlier GUI-check pass that this change does *not* touch** (still open, still just documented): the "Migrate Legacy Data" false positive on a fresh scene, truncated Output-panel button labels, Pose-Mode-on-face-board after import, the LOD0-locked-on import dialog row, and (now less relevant) raw-Python-traceback error popups — none appeared in this pass since nothing raised, but the underlying `report_error`-vs-bare-exception UI pattern elsewhere in the addon is unchanged.

**Not yet exercised:** bake-to-action (`BakeFaceBoardAnimation`/`BakeComponentAnimation`, `runtime/authoring.py`'s `sample()`/`bone_transforms()`/`evaluate_once()` paths) and the body rig's live evaluation via GUI (only headless-checked, via the `ada_body_native` carrier being present and `active()`/`errors()` clean — no visual/GUI pass on the body specifically). Both should route through the same `python_evaluator` interface with no additional engine-side work, since `authoring.py` calls the identical `engine.native_module()` functions, but haven't been clicked through yet.

### PR #3 merged, evaluator PR #4 opened (2026-09-22)
- PR #3 (macOS bindings, per-platform zips, clean install) merged as `73a63f3` after all 11 checks passed on its head `6394880`.
- `feature/python-evaluation-engine` rebased onto `73a63f3` (one commit, `e02a336`, no conflicts). Opened as highlighthousefc-ai/character-dna-addon#4 against `main`; **not merged**, pending a manual look at `ada_jaw_open_pose.blend`.
- PR #4 CI run 35784023776: **all 11 jobs pass**. `dna_core` 9/9 on both OSes, with no skips.
- **Coverage gap:** CI only proves the new evaluator *loads*, not that it *evaluates*.
  - The register jobs do reach it: `controller.register()` calls `engine.capability()`, which imports `runtime/python_evaluator.py` and checks its function set. This passes on Windows + macOS with bpy 5.1 and 5.2.
  - Packaging and the clean install ship the file.
  - No CI job runs a frame through `evaluate_frame`/`transform_into`, or the import operator. `bindings_in_addon.py` and `installed_extension_check.py` call `riglogic` directly.
  - The actual evaluation (mesh moves, `jaw_open` = 1.0, export succeeds) is verified only by the local headless and GUI runs. Next step: a `tests_core` test that drives the synthetic jaw rig through `create_frame_plan`/`evaluate_frame`/`transform_into`.
- **Coverage gap closed (2026-09-22):** commit `48d8f8d` on PR #4 adds `tests_core/test_python_evaluator.py`.
  - It drives the synthetic jaw rig through the evaluator as the face board does:
    - the rig now optionally has a `CTRL_C_jaw.ty` GUI control mapped 1:1 onto `jawOpen`;
    - the test runs `create_frame_plan`, `evaluate_frame` and `transform_into`;
    - the buffers are shaped like `frame.prepare`/`capture` output.
  - What it checks for jaw 0 / 0.5 / 1.0:
    - raw `jawOpen` follows the GUI control;
    - RigLogic's jaw X rotation is 0 / 12.5 / 25°;
    - the pose-bone Euler X is the same in radians, with location and scale unchanged.
  - It also checks the engine API surface and repeatability.
  - Mutation check: removing the degrees-to-radians conversion fails the 12.5 and 25° cases.
  - CI's `dna_core` job now installs numpy, and ruff lint is enforced on `python_evaluator.py`.
  - Run 35785313249: all 11 jobs pass; `tests_core` 14/14 on both macOS and Windows, the 5 new tests run, not skipped.
- Import-path note: the evaluator imports cleanly in `tests_core` only because pytest has already imported the stdlib `typing` before `conftest` puts `src/addons/character_dna` (which has its own `typing.py`) on `sys.path`. A bare `python -c` with that path first fails with a circular `typing` import (seen while prototyping). This is fragile but fine under pytest.

## Report: "jaw not open in saved file, sliders do nothing" (2026-09-22). Root cause: addon not installed in the user's Blender
Investigated before any merge. PR #4 is untouched (no code change needed).

**Cause of both symptoms:** `character_dna` is not installed in any of the user's Blender profiles.
- Checked read-only: `~/Library/Application Support/Blender/{4.2,5.1,5.2}`. 5.1's `user_default` has only `amh2b`, `higgsfield_blender` and `retarget_bvh`. An `api_portal_polyhammer_com` repo is configured but empty.
- The user's auto-run Python pref is ON, so that wasn't a blocker.
- Live evaluation is driver-based: each carrier's `["epoch"]` driver calls `character_dna_native_solve_v1(self, depsgraph)`, which the addon registers in `bpy.app.driver_namespace`.
- Without the addon, that function doesn't exist, so the driver is invalid and every driven jaw/shape output stays at its neutral value. Face-board bones become inert armature bones, and there's no sidebar at all.

**Saved-file check** (`ada_jaw_open_live_drag.blend`, windowed Blender 5.1.2, auto-run ON). The file stores `CTRL_C_jaw.location = (0, 1, 0)` either way.
- **Clean profile without the addon:** the solver is missing from the namespace, the head carrier's `["epoch"]` driver is invalid, and `FACIAL_C_Jaw` stays at (0, 0, 0). The mouth looks closed. This reproduces the user's report.
- **Profile with the addon installed:** the solver is present, the driver is valid, `engine.active=True`, `FACIAL_C_Jaw` is (0.398, -0.008, 0.011) and there are no errors. The mouth is open on load.
- Side-by-side: `~/Desktop/MetaHuman-DNA-Addon/verification/reopen_with_and_without_addon.png`.

**Live interactive drag.** My earlier GUI pass only set the pose picker property from script; this time it was a real modal drag.
- Setup: fresh addon zip from PR #4 head `48d8f8d`, throwaway profile, real import via F3 → file browser → Return.
- In pose mode on the face board, `CTRL_C_jaw` was selected by script. Then, all as simulated input: G, then Y, Y (local-Y axis lock), then mouse moves 1 px at a time.
- Measured each step during the modal `TRANSFORM_OT_translate`:

  | Control Y | `FACIAL_C_Jaw` X | Head mesh moved |
  |---|---|---|
  | 0.099 | 0.039 rad | 0.32 cm |
  | 0.494 | 0.197 rad | 1.57 cm |
  | 0.988 | 0.393 rad | 3.01 cm |
  | 1.0 (clamped by the Limit Location constraint) | 0.398 rad | 3.04 cm |

- The response is linear. The evaluator's solve-call counter rose by 2 on every mouse move, so evaluation is live, not on demand.
- Dragging back up went through 0.901 → 0.506 (mesh 2.77 → 1.61 cm). Dragging down again returned to 1.0. `engine.errors()` stayed empty.
- Screenshots show Blender's modal header ("D: … along local Y") and the mouth opening progressively. Face crops: `verification/jaw_drag_sequence.png`.

**Driver dead ends** (from building the drag test; none were addon bugs):
- Blender 5.1 moved selection from `Bone.select` to `PoseBone.select`.
- An unconstrained grab moved local X (jaw sideways) instead of Y.
- This control opens the jaw when dragged **down**; up hits the 0 limit.
- My pixels-per-unit estimate from `location_3d_to_region_2d` was about 50x off; the empirical figure is about 0.1 unit per px at that zoom.

**Still not click-verified:** the sidebar Face Board pose picker. In the earlier pass its property was set by script, which does drive the jaw, but its thumbnail popup has not been clicked. **Also noted:** a file saved with this addon silently shows a neutral face when the addon isn't installed (an invalid driver, no user-facing message). That's inherent to the driver design; a future improvement could be a visible warning.

## Slider freeze investigation and fix (2026-09-22)
The addon is now installed in the user's real Blender 5.1 profile (`user_default/character_dna`, enabled, `dependencies_are_valid()` True). It was reinstalled with the fixed build below.

**The "froze at 0.034" drag was a test artifact, not an addon bug.** It was the unconstrained grab with 592 px steps: it moved local **X** (jaw sideways, `x ∈ [-1,1]`) and later mouse events fell outside the window. Re-checked live in a windowed session:
- **Direct property set** of `CTRL_C_jaw.location.y` to 0.034 → 0.5 → 1.0 → 0.5 → 0.034 → 0 tracks exactly. The evaluator reads the same value, the jaw bone goes 0.0135 / 0.199 / 0.398 rad, and the mesh moves 0.11 / 1.59 / 3.04 cm. The solve count rises by 1 per change.
- **Runtime `LIMIT_LOCATION` on `CTRL_C_jaw`:** x = [-1, 1], y = [0, 1], z = [0, 0], LOCAL space, `use_transform_limit` on. Nothing clamps near 0.034.
- **Unconstrained grab in 3 px steps:** moves continuously on both axes and in both directions (y 0 → 0.314, x -0.627 ↔ +0.627). Cancelling restores 0.
- **No feedback loop:** nothing in `python_evaluator.py` or `engine.py` writes to face-board control locations. The only face-board targets are switch constraint influence and aim-bone visibility. The only location writers are the pose picker and the explicit "Map Raw to GUI Controls" operator.

**Real bug found and fixed (commit `41f779f` on PR #4): the L/R eye controls were frozen.**
- The imported face board has tiny rest offsets. `CTRL_C_eye` is `(4e-6, -3.1e-5, 0)`, and several other controls sit around 1e-5.
- The evaluator's "non-zero centre eye overrides `CTRL_L_eye`/`CTRL_R_eye`" rule used `1e-6`, so this noise counted as "moved". The centre eye then permanently overrode both side eyes.
  - Live before-fix drag: `CTRL_L_eye.x` went -0.98 → +0.98 on the control, but reached RigLogic as 0.0, with zero mesh and bone change.
- The original Python path used `constants.FLOATING_POINT_PRECISION = 1e-4` for this rule and for the eye-aim checks. `python_evaluator.CONTROL_EPSILON = 1e-4` now mirrors it, because `constants.py` imports `bpy`.
- **Why my own sweep didn't catch it at first:**
  - its reference used the same 1e-6;
  - its tracking check skipped the L/R eyes;
  - `np.asarray` on the evaluator's reused `array('d')` buffer aliased successive samples, so every step looked unchanged.
  All three are fixed in the sweep script.
- Regression test: `test_centre_control_only_overrides_when_actually_moved`, with 4 cases. It fails without the fix.

**All-controls verification with the fixed build** (windowed Blender 5.1.2, clean profile, Ada UE 5.6 head):
- **Sweep of all 174 face-board GUI controls,** set via the property: 0 → max → min → 0.
  - Every control reaches RigLogic with exactly the value set, eyes included.
  - Outputs match an independent RigLogic reference built from the same DNA with the original rules exactly (max diff 0).
  - Every `LIMIT_LOCATION` range equals the DNA's GUI→raw input range: 104 controls use [0, 1] and 70 use [-1, 1]. No control's constraint is narrower than its DNA range.
  - Outputs change on every step where the value changes, for all controls except 9 correctives, covered next.
- **9 corrective controls are inert on their own, identically in the reference (RigLogic by design).** They are `lipsTogetherU/D` L/R, `jaw_openExtreme`, `nose_wrinkleUpper` L/R and `mouth_stretchLipsClose` L/R.
  - With their partner active (jaw, nose, or mouth_stretch = 1) they respond on 9/9 steps.
  - They match the reference exactly.
- **Real axis-locked drags** (G, axis, axis, mouse moves; about 20 steps, full range, both directions, a screenshot each step): jaw.y, L_eye.x, L_eye.y, L_eye_blink.y, L_brow_raiseIn.y, L_mouth_cornerPull.y, C_mouth.x.
  - The evaluator's GUI value equals the control value at every step, with 0 frozen steps.
  - Solve calls rise every step, and the mesh follows proportionally. For example: jaw 0.34 → 3.02 cm and back; mouth X ±2.45 cm.
  - The `FACIAL_L_Eye` bone rotates +41.6° / -36.9° (x) and -29.1° / +39.2° (y), and returns to 0.
  - Evidence: `~/Desktop/MetaHuman-DNA-Addon/verification/all-controls-drag/` (grid image, per-step logs, the before-fix eye log, and the 174-control sweep JSON).
- **CI run 35805743553 on `41f779f`:** all 11 jobs pass; `tests_core` 18/18 on macOS and Windows.

**Limits of the claim:** "identical to Poly Hammer's original" is checked against Epic's RigLogic plus the original Python rules (pre-native `c3827cb^`), not against their closed native runtime, which we don't have.

**Harness note:** one sweep attempt hung inside the scripted unconstrained grab; it didn't recur on rerun and doesn't affect the addon.

### PR #4 merged (2026-09-22)
PR #4 was merged into `main` as `ba1be15`, pinned to the reviewed head `41f779f`. It contains three commits: the Python evaluator, its end-to-end CI test, and the eye-control threshold fix. The post-merge CI run on `main` (35807547392) passes all 11 jobs. `main` now has no dependency on Poly Hammer's private native runtime.

## Blend-shape import, missing-add-on notice, pose picker / body GUI pass (2026-09-22)
Branch `feature/blend-shape-import` on the fork. Not pushed, not merged.

### Why blend-shape import was dead code
- **It was not a bug in the free code.** Upstream moved it out.
  - Up to `f426b81^`, free `components/head.py` had `import_shape_keys(commands_queue)`. It fed `dna_io.create_shape_key` through `GenericProgressQueueOperator`, behind an "Import Shape Keys" button.
  - In `f426b81` ("Raw control editor v2", 2026-06-18), Poly Hammer deleted that method and the operator, and made `editors/` a private submodule (the Pro Shape Key Editor).
  - Our fork keeps the free code only, so `create_shape_key`, `apply_blend_shape_deltas`, `importer.set_shape_key` and `importer.get_dna_shape_keys` were left with no caller.
  - The `import_shape_keys` property existed but was hidden and read by nothing.
- **`importer.get_dna_shape_keys` was also broken.** It read Z deltas with `getBlendShapeTargetDeltaYs` and indexed an empty list. It has been removed, along with the unused `set_shape_key`.
- **Only the free, pre-`f426b81` GPL code path was used as reference.** No `editors/` or Pro code was read.

### Second bug: 42 MetaHuman targets could never be driven
- `{mesh}__{channel}` exceeds Blender's 63-character name limit for 42 of Ada's 858 targets. Example: `head_lod0_mesh__Mfunnel_MupperLipRaise_MlowerLipDepress__funnelWide_UL`, 70 characters.
- Blender truncates these names and makes siblings collide. Upstream skipped them everywhere (`SHAPE_KEY_NAME_MAX_LENGTH` checks), so those correctives were never evaluated.
- The exporter wrote them as **empty targets** whenever shape keys were present. With import wired, exporting Ada would have wiped 42 correctives.
- **Fix:** `dna_core.shape_key_name(mesh, channel)` (bpy-free).
  - A long name keeps its first 54 bytes, then `~` and 8 hex digits of SHA-1.
  - The result is deterministic and unique.
  - It is used by the importer, the runtime plans (`head_shape_key_blocks` / `head_shape_key_apply_plan` / channel lookup), the exporter and the calibrator. The 63-character skips were removed.

### What changed
- **`dna_io.import_blend_shapes(mesh_object, reader, mesh_index, mesh_name, linear_modifier)`:**
  - clears existing keys and adds a Basis;
  - adds one key per DNA target, at value 0 and locked, in DNA target order;
  - reads the basis once;
  - vectorised scatter with a single `foreach_set` per key.
- **Import:** `CharacterComponentHead.import_shape_keys()` runs during `ingest` when the import option "Shape Keys" is on.
  - The option now defaults to on and appears in the import dialog (head only).
- **Existing characters:** new `character_dna.import_shape_keys` operator ("Import" / "Reimport" in Rig Instances → Head, with a key count).
  - It is wrapped in `native_scene_operation`, so the runtime bindings are released, the keys rebuilt, and the bindings reinstalled with the new key drivers.
- **Speed:** exporter and calibrator shape-key deltas vectorised (numpy + `foreach_get`).
  - The per-vertex loops made an Ada export with keys take 21 s. It now takes about 8 s, against 5.7 s without keys.

### Verified on the real Ada head (Blender 5.1.2, headless unless noted)
- **Structure:**
  - 858 targets across 5 LOD0 meshes (head 737, teeth 41, cartilage 76, eyes 2+2); 782 channels.
  - Every key is present, in DNA order, uniquely named.
  - The runtime plan resolves 858/858 keys covering 782/782 channels. Before the naming fix it was 816/858.
- **Geometry:**
  - basis equals the DNA neutral positions within 8e-8 m;
  - every key's `(key - basis)` equals the DNA delta (rotated +90° X, cm→m) within 6e-8 m.
- **Hand-set values** (drivers released): value w moves the evaluated mesh by exactly w × delta within 6e-8 m. Checked for jaw_open, brow_raiseIn_R and two long-named funnelWide keys.
- **Face board, end to end:** random and targeted GUI poses were compared with an independent RigLogic instance built from the same DNA.
  - Evaluated key values match exactly (0.0 difference).
  - The mesh with skinning off equals neutral + Σ w × delta within 9e-7 m.
  - The funnel pose drives 12 long-named correctives.
- **Export round trip:**
  - all 858 targets are re-exported from the scene keys within 6e-6 cm of the source, and none are emptied;
  - editing one vertex of `jaw_open` by +1 mm Z exports as +0.1 cm DNA Y on exactly that vertex.
- **GUI** (windowed, clean profile):
  - the Shape Keys list shows real, driven, locked keys;
  - the Head panel row reads "737 shape keys | Reimport";
  - clicking Reimport reports "Imported 858 shape keys", rebuilds 737 drivers, and jaw=1 drives `jaw_open` to 1.0.
- **Cost:** import with keys takes about 11 s (head plus body). The .blend is 66 MB.
- **CI:**
  - `tests_core/test_blend_shapes.py`: naming and a synthetic blend-shape DNA (one of its names is 70 characters);
  - `installed_extension_check.py` imports that DNA's blend shapes, twice, in the installed extension inside real Blender and checks every delta.

### Missing add-on notice (the silent neutral face)
- **Without the add-on nothing of ours runs,** so the file itself has to carry the warning.
- **What it is:** each character gets a red 3D text object above its head: "Character DNA add-on is not enabled. '<name>' stays in its neutral pose and the face board does nothing. Install and enable the add-on, then reopen this file."
  - `save_pre` shows it and `save_post` hides it again, so it is visible in the saved file.
  - `load_post` and add-on registration hide it; unregistering shows it again.
  - It is `hide_render`, `hide_select` and `show_in_front`.
  - It is recreated on save if deleted, and removed with its character.
- **Verified by opening the same saved file (jaw saved fully open):**
  - **Clean profile, no add-on:** the notice is visible. Blender's own auto-run dialog names the driver only if auto-run is off. The face is neutral: jaw rotation 0, `jaw_open` 0.
  - **Profile with the add-on:** the notice is hidden, the jaw is open, and `jaw_open` is 1.0.
  - **Add-on installed but auto-run off (the default):** also evaluates, notice hidden, no dialog.
- **Bugs caught while testing:**
  - Blender 5.1 rejected `inputs["Surface"]`; the handler's guard kept the save working, but the notice was left half-built.
  - `node is not output` compares RNA wrappers, which never compare equal, so the loop deleted the Material Output.
  - Both are fixed: sockets by index, tree rebuilt explicitly. The CI check asserts the Emission → Output tree.

### GUI pass: pose picker and body controls (report only, nothing fixed)
Windowed Blender 5.1.2, driven by real simulated events, screenshots in `~/Desktop/MetaHuman-DNA-Addon/verification/blend-shapes-notice-gui-pass/`.
- **Pose picker, working:**
  - The Face Board panel's thumbnail opens the popup grid (156 poses, labelled).
  - Clicking "Fear-03 Fear" moves 38 face-board controls, drives 51 shape keys, and the face matches the thumbnail.
  - The search button opens a search popup; typing "joy" + Enter applies "Joy-03 Joy".
  - The tag popover (Match All/Any; MH1, MH12, MH50, eyes, jaw_open, neck, tongue) filters: ticking jaw_open narrows 156 → 10.
- **Pose picker, issue:** changing the tag filter **replaces the current face pose.** With Joy-03 selected, ticking jaw_open switched the pose to "Dimpler Jaw Open", the first match, and applied it to the face board. Filtering a list should not overwrite the user's pose.
- **Pose picker, cosmetic:** the thumbnails are pre-rendered on a generic head, not the loaded character.
- **Body controls, working:**
  - View Options → Body Bones shows the hidden body rig.
  - In pose mode, a real R → 70 → Enter on `upperarm_l` sets raw controls equal to the bone's quaternion exactly.
  - 7 of 251 written body joints respond (upperarm correctiveRoot/out/bck/fwd/in, twist_01/02).
  - All 3,420 body joint outputs match an independent RigLogic instance with the body configuration exactly.
  - Cmd+Z restores the arm, and every corrective returns to rest with no engine errors.
- **Body controls, not present:** "Control Rig" stays empty on import. Only legacy migration fills it, so there is no separate body control rig in this fork.
- **Harness notes, not add-on bugs:**
  - My first reference used RigLogic's default config and showed a false 34.9 difference; the body config fixed it.
  - Under `--enable-event-simulate`, the first click after the pointer enters a new region is swallowed. The sidebar also collapsed once after simulated clicks at its edge; toggling it restored it.

### Corrective (PSD) structure in Ada's head DNA (probe for the Shape Key Editor)
- **Controls:** 263 raw controls and 545 PSD controls, with 1,430 PSD entries. PSD rows are output indices ≥ the raw count, so control index = raw + PSD index. There are no ML controls.
- **Channel mapping:** 782 channel entries (`getBlendShapeChannelInputIndices` / `OutputIndices`), one input per channel. 219 channels are driven by a raw control and 563 by a PSD.
  - Example, basic: `jaw_open` ← raw `CTRL_expressions.jawOpen`.
  - Example, corrective: `Mfunnel_MupperLipRaise_MlowerLipDepress__funnelWide_UL` ← PSD 412 = product of `mouthUpperLipRaiseL`, `mouthLowerLipDepressL` and `mouthFunnelUL`, each with weight 1.
- **PSDs nest:** 48 PSD inputs are themselves PSDs, so a dependency chain must be expanded recursively.
- **Arity:** 2 inputs: 301; 3: 166; 4: 62; 5: 14; 6: 2.
- **Weights:** all are 1.0 except six entries of 4.0. The exact PSD formula (product × weight, clamping) is still to VERIFY against RigLogic before building on it.

## Known issues (logged, not fixed)
- **KI-1: changing the pose picker's tag filter replaces the current face pose.** (Found 2026-09-22 in the GUI pass; not blocking.)
  - Repro: in Face Board, pick "Joy-03 Joy". Open the filter popover and tick `jaw_open`.
  - Expected: the pose list narrows (156 → 10) and the face keeps Joy-03.
  - Actual: the list narrows, and the face switches to "Dimpler Jaw Open", the first match, which is applied to the face board.
  - Likely cause, unverified: `face_pose_previews` is a dynamic enum. When the current item leaves the filtered list, Blender falls back to the first item, and the property's update callback applies it as a pose. The fix should filter the display without writing the pose.
  - Evidence: `~/Desktop/MetaHuman-DNA-Addon/verification/blend-shapes-notice-gui-pass/10_tag_filter_replaced_pose.png`.

## PR #5 and the Shape Key Editor scope (2026-09-23)
- **PR #5:** `feature/blend-shape-import` (`880c7d7`) was pushed and opened as highlighthousefc-ai/character-dna-addon#5. Not merged; waiting for review.
- **Installed for you:** the same build (zip sha256 prefix `2efa718e`) is installed and enabled in the real Blender 5.1 profile and copied to `~/Desktop/MetaHuman-DNA-Addon/addon/`. A background check confirmed it: enabled, the notice module present, `import_shape_keys` registered, Shape Keys on by default, dependencies valid.
- **Editor scope, decided by you:**
  - **v1 is Edit → Commit → Revert only.** Commit writes the head DNA in place, after writing a timestamped backup of the previous file.
  - **Deferred to v1.1:** Generate Neutral and Mirror/Flip.
  - **Build order:**
    1. `dna_core/psd.py` and `dna_core/blend_shapes.py` (no bpy, unit-tested);
    2. the `shape_key_editor` package;
    3. wiring into `engine.py` and the panel.
  - No editor code until you confirm Reimport works for you. Interactive proof is needed before calling it done, and it stops for your review before merge.

## Shape Key Editor v1 (Edit → Commit → Revert), 2026-09-23
Branch `feature/shape-key-editor`, stacked on `feature/blend-shape-import` (PR #5). Not merged.

### Verified facts the design rests on
- **Correction to the earlier probe:** PSDs never read other PSDs. The 48 "nested" PSD inputs I reported are **RBF pose controls**. The control layout is `[raw 263 | PSD 545 | ML 0 | RBF pose 18]`; the ML/RBF order is unverified because Ada has no ML controls.
- **PSD value:** `clamp(Π(input × weight), 0, 1)`. Max difference against RigLogic is 7.4e-8 over 149,100 random samples. The only weights other than 1 are six `jawOpen × 4`.
- **Ada's channels by driver:**
  - 219 by a single raw control;
  - 497 by a PSD of raw controls;
  - 48 by a PSD that includes a neck RBF pose;
  - 18 by an RBF pose directly.
- **Activation:** setting every raw leaf to 1 switches each of the 716 face-driven channels to exactly 1.0 in RigLogic. The 66 RBF-involved channels activate only by posing the neck, so v1 lists them locked with the reason; that is v1.1.
- **Ada is Maya Y-up, in centimetres.** A `setFrom` round trip is byte-identical.
- **Target vertex indices are not stored sorted.** Re-sorting them alone changes the file's bytes, so `merge()` keeps the stored order and appends new vertices after it.
- **Sculpting on an armature-deformed mesh with other keys mixed:** Blender stores the stroke in the key's rest space. After commit, the evaluated face under the same activation equals what was on screen while sculpting, within 0.0009 mm.

### Code
- **`dna_core/psd.py`:** `ControlGraph` (kinds, names, dependency tree, activation, formula).
- **`dna_core/blend_shapes.py`:**
  - target lookup and deltas;
  - `merge()`, which keeps unedited vertices bit-for-bit and in stored order;
  - `commit_target()`: timestamped backup in `backups/` next to the DNA, write to a temp file, then `Path.replace`. It loads and releases its own reader for Windows' file locks.
  - Both modules are bpy-free, with 12 new tests (37 in `tests_core` in total).
- **`runtime/engine.py`:** `preview_raw(instance, raw_values, shape_overrides)` publishes the pose through the existing preview mechanism (neck quaternions kept, other expressions at 0). `clear_preview()` drops it.
- **`shape_key_editor/`** (`properties`, `session`, `operators`, `ui`): a sidebar panel at the reserved `PanelOrder.SHAPE_KEY_EDITOR`.
  - **List:** mesh selector; filters for name (matched on the DNA channel name), side, non-zero, has-deltas, sort by value, Freeze.
  - **Edit:** activation preview, the dependency list with eye toggles, only the edited key unlocked, Sculpt / Edit Mode buttons.
  - **Commit:** merge, backup and in-place write; rebuild the runtime; set the key from the new DNA.
  - **Revert:** set the key from the DNA; the file is never touched.
  - **Undo:** the DNA is only written by Commit, never by undo.

### Interactive proof (windowed Blender 5.1.2, clean profile, working copy of Ada, real simulated input)
1. **Found and edited a long-named corrective through the UI.**
   - Opened Shape Key Editor, then filtered to "funnelWide". This caught a bug: the filter originally matched hashed Blender names and missed these keys; fixed.
   - Clicked Edit on `Mfunnel_MupperLipRaise_MlowerLipDepress__funnelWide_UL`.
   - The face showed its context: `mouthUpperLipRaiseL`, `mouthLowerLipDepressL` and `mouthFunnelUL` at 1, and six locked dependencies at 1.00. The edited key evaluated at 1.000 and was the only unlocked key.
2. **Eye toggle:** hiding `mouth_lowerLipDepress_left` set its evaluated weight to 0.000 while the edited key stayed at 1.000.
3. **Sculpt:** the Sculpt button put `ada_head_lod0_mesh` in Sculpt mode with the edited key active (Draw brush). A real press-drag-release stroke on the left upper lip changed the key on 1,896 vertices (max 2.917 mm); the evaluated face moved up to 2.951 mm.
4. **Commit button:** "1861 vertices changed", with a backup written.
   - On disk, the backup is identical to the original.
   - Exactly one target changed (`…funnelWide_UL`) on 1,861 vertices, max 0.2917 cm; it grew from 1,488 to 2,903 vertices.
   - Joints, vertex counts, raw controls and PSD values are unchanged.
5. **Re-edit:** the face equals the sculpted view within 0.0009 mm, against 2.951 mm from the pre-stroke face.
6. **Revert button** after a second real stroke (2.805 mm): the key returned exactly to the committed version (0.00000 mm), locked again, with the DNA file hash unchanged.
7. **Persistence across sessions:** quit Blender, started a new session, and imported the committed DNA into an empty scene. Editing the key reproduces the session-1 sculpted face within 0.0009 mm.
8. **Final labels:** long names are elided at the start (`Mfu…funnelWide_UL/UR/DL/DR`); dependency rows read `mou…LipRaise_left`, `mouth_funnel_UL`.
- **Headless smoke** (`editor_smoke.py`), all on a copy of Ada:
  - a no-op commit of `jaw_open` is byte-identical;
  - an RBF key is refused ("needs headTurnUpU, which come from bone rotations…");
  - Reimport from the DNA reproduces the sculpted key exactly.
- **Evidence:** `~/Desktop/MetaHuman-DNA-Addon/verification/shape-key-editor/`.

### Known limits / follow-ups
- **v1.1:** editing the 66 neck-RBF channels (activate by posing the neck bones), plus Generate Neutral and Mirror/Flip, as agreed.
- **Windows:** the in-place commit is covered by `tests_core` on Windows CI. The full Blender session hasn't been run on Windows.
- **Lower LODs:** Ada's are unaffected because only LOD0 carries targets. Recheck on the UE 5.6/5.8 exports.
- **List values (unverified):** list rows read the original key-block values. I did not check whether they follow driven changes during a preview; the non-zero filter depends on them.
- **Harness note:** the first click after the pointer enters a new region is swallowed under `--enable-event-simulate`, so clicks were repeated. This is a test-tool artifact.

## "848 shape keys" report investigated (2026-09-23), not reproduced
You reported "848" in the status bar after File > Import > MetaHuman DNA on `head.dna` with the PR #5 build. Checked:
- **The DNA files:** both head DNAs on this machine (`test-dna/ada`, `test-dna/default`, byte-identical to the repo fixtures) hold 858 targets and 782 channels. Per mesh: head 737, teeth 41, cartilage 76, eyes 2+2.
- **Your saved scene** `blend-files/Untitled.blend` (saved 08:14), opened read-only without the add-on: 858 keys, head 737.
- **A real File > Import through the file browser,** same PR #5 zip, clean profile, default options (Shape Keys on, LOD0 only, Include Body on). Blender's full Info report log shows only `Imported "body.dna" successfully!` and `Imported "head.dna" successfully!`, with no count; 858 keys in the scene.
- **The only count-bearing message in the add-on** is the Head panel's Import/Reimport button. Run in the same session, it reports `Imported 858 shape keys`.
- **Blender's status-bar scene statistics** are off in your real preferences, so no Blender statistic could have shown a bare 848. With them on, the pose-mode stat reads `Bones:0/435`.
- **Conclusion:** no path of that build produces 848 for these files. Open: a screenshot of the message would pin it down.

## PR #6 build installed for you (2026-09-23)
- The build from `acf96dc` (zip sha256 prefix `52a7580a`) is installed and enabled in the real Blender 5.1 profile and copied to `addon/`. A background check confirmed the editor panel and its operators are registered.
- **Sandbox for trying the editor:** `~/Desktop/MetaHuman-DNA-Addon/editor-sandbox/ada-copy/head.dna`, plus `body.dna`, both copies of the fixture. `pristine/head.dna` is there for resetting, and `README.txt` explains the folder.
- Both PRs stay unmerged until you've tried Edit → sculpt → Commit → Revert.

## Commit/Revert verified by hand-style GUI test on the sandbox copy (2026-09-23)
All on `editor-sandbox/ada-copy/head.dna`, in windowed Blender with real simulated input (click to select, G Z 0.5 Enter, panel buttons).
1. **Edit Mode on `…funnelWide_UL`** via the panel's Edit, then Edit Mode. Pass.
2. **v12207, top-lip centre,** selected by click and moved +0.5 on Z with G, Z, 0.5, Enter (0.5612 → 2.0612 in Blender; 2.0568 evaluated). Pass.
3. **Screenshots** before and after the move, still uncommitted; the DNA file was confirmed unchanged at that point. Pass.
4. **Commit button:** "1 vertices changed. Backup: head.20260923-173633.dna". Pass.
5. **On disk:**
   - funnelWide_UL target 233 changed on exactly v12207, by **(0, +50.000, 0) cm**, which is +0.5 m Blender Z = +50 cm DNA Y;
   - no other target changed;
   - the backup is byte-identical to `pristine/head.dna`.
   - Note: backups are `backups/head.<timestamp>.dna`, not `.bak`, as built.
6. **Persistence:** quit Blender, started a new process and imported the file. The rebuilt key has v12207 (key − basis) = (0, 0, 0.5) m, and Edit shows the spike. Repeated in a third process. Pass.
7. **Revert on a different vertex:** a mouth-corner vertex moved +0.5 Z, then Revert.
   - **First attempt: FAIL, real bug.** A Ctrl+Z earlier in the edit had released the character's DNA reader (`utilities.pre_undo` → `destroy_head`), and Revert errored "The character's head DNA is not loaded".
   - **Fixed in `836c293`:** the editor reads the unit and LOD0 meshes from the DNA file.
   - **Retest on the fixed build,** with a Ctrl+Z deliberately done mid-edit: Revert restored the key to its pre-edit state (3.7e-8 m) and left the committed spike intact. The DNA file stayed byte-identical (sha256 `0c36a8cc…`): same modification time, no new backup, no temp files. Pass.
   - Headless: Commit and Revert after `destroy_head` both work.
8. **Final screenshots:** front view and mouth close-up with the committed edit visible (a sliver rising from the top-lip centre, rebuilt from the file). Pass.
- **Second bug found and fixed in `836c293`:** Commit made `head.dna` owner-only (0600), because of `tempfile.mkstemp`. The mode is now copied from the original, with a regression test (38 tests in `tests_core`). The sandbox file's mode was restored to 0644.
- **Installed:** the fixed build (zip sha256 prefix `c6084d06`) is in the real profile and in `addon/`.
- **Evidence:** `verification/commit-revert-check/`.

## PR #5 and PR #6 merged (2026-09-23)
- **PR #5** (blend-shape import + missing-add-on notice) merged as `49ca873`, pinned to `880c7d7`. Main CI run 35932172815: 11/11 green.
- **PR #6** (Shape Key Editor v1) was retargeted from PR #5's branch to `main`, which doesn't re-trigger PR checks. Before merging I confirmed the merge result's tree (`18b8ffe`) is identical to the tree CI run 35930739985 passed 11/11 on. Merged as `2b67a88`, pinned to `836c293`. Main CI run 35932742622: 11/11 green.
- **Sandbox reset:** `editor-sandbox/ada-copy/head.dna` was copied back from `pristine/` (identical to the fixture; mode 0644). The old backup from the test commit is still in `ada-copy/backups/`.
- **Install:** your Blender profile already had the `836c293` build, the same code as `main`.

## KI-1 fixed (PR #7) and Shape Key Editor v1.1 Mirror/Flip (PR #8), 2026-09-24
- **KI-1 fixed in PR #7** (`213c6a2`, CI 11/11).
  - **Cause:** `update_face_pose_filter` deliberately re-selected the first matching pose when the current pose was filtered out, and assigning the selection applies the pose.
  - **Fix:** filters only rebuild the list, and the selected pose always stays listed, so the dynamic enum never goes blank.
  - **Regression test:** `scripts/ci/pose_picker_check.py`, in the Register job, which ran on all 4 platform and bpy combinations. It fails on the old code.
  - **Interactive check:** Joy-03, then tick jaw_open changed 0 controls and 0 shape keys; picking from the filtered grid still applies; unticking keeps the pose.
- **Mirror/Flip in PR #8** (`ce2a946`, CI 11/11).
  - **Naming:** Ada has 352 L/R channel pairs and 78 centre channels. Direction words mirror too (`eye_lookLeft_L` ↔ `eye_lookRight_R`), and the eyes mirror between the two eye meshes.
  - **Geometry:** Ada is not symmetric; nearest-vertex partners disagree for 5% of head vertices. Pairing grown along edges from the centre line gives an exact involution on the head (99.93% of edges preserved). The teeth fall back to nearest vertices.
  - **Correction to an earlier guess:** Epic's own L/R targets are **not** mirror images of each other. brow_down_L mirrored against brow_down_R has cosine 0.70, and some correctives have cosine 0.05. So the default "Mirror Edit" mirrors only the change; "Copy Whole Mirrored Shape" is the explicit symmetric option.
  - **Interactive check:** a +2 cm raise on one vertex of brow_down_L mirrored to exactly one vertex of brow_down_R. Commit wrote both targets with one backup. Flip followed by Revert left the file byte-identical, and a centre key shows "No Opposite".
- **Harness notes:**
  - The simulated clicks can't open popovers (the tags popover was opened with `call_panel`, the same panel), and first clicks are sometimes swallowed.
  - A command occasionally ran without its output reaching the log, and was re-sent.

## PR #7 and PR #8 merged (2026-09-25)
- **PR #7** (KI-1 fix) merged as `3a7fea8`, pinned to `213c6a2`. Main CI run 36189278140: 11/11 green.
- **PR #8** (Mirror/Flip) merged as `73dd3ca`, pinned to `ce2a946`. Before merging I checked it shares no files with #7 and merges cleanly.
- **Main CI run 36190124686: 11/11 green on the combined code.**
  - The pose-picker check passed on all 4 platform and bpy combinations.
  - `tests_core`: 66 passed on macOS; 65 passed and 1 skipped on Windows (the POSIX-permission test).
- **Test data:**
  - The project folder has moved from `~/Desktop/MetaHuman-DNA-Addon` to `~/Downloads/Personal./MetaHuman-DNA-Addon`. Paths in earlier notes refer to the old location.
  - Every Ada copy there (`editor-sandbox/ada-copy`, `pristine`, `test-dna/ada`) is byte-identical to the fixture. So is `test-dna/default`. The repo fixtures are unmodified.
  - This round's testing only used scratch copies, which have now been deleted.
- **KI-1 is closed.**

## Character Assembly scoping spike (2026-09-25): research only, no code
### Licensing (verified)
- **Poly Hammer Interchange** (Unreal plugin) is **closed-source freeware on Fab**. The listing is free and shows no custom license terms, so the **Fab Standard License** applies: use and modify in your own projects; no reselling or standalone redistribution. It is not open source, and there is no public repo.
  - poly-hammer's 5 public repos: `character-dna-addon` (GPL-3.0), `poly-hammer-docs` (MIT), `BlenderTools` (MIT), `ufbx-python`, `poly-hammer-workflows`.
- **Character Assembly** (the Blender addon) and **Character Control Rig** are **private** repos. The public docs site pulls their pages in at build time with a token (`poly-hammer-docs/scripts/sync_docs.py`, `pyproject.toml [tool.poly-hammer-docs]`).
- **The free GPL Character DNA addon** already has a read-only hook for Assembly's saved data: `Scene.character_assembly.rig_instance_proxies`, whose entries carry `rig_instance_name`, `manifest_path` and `components[].source_path` (`utilities/reference.py`, `resources/scripts/save_rig_instance_data.py`). This is GPL code, so we can reuse it.
- **MetaHuman assets outside Unreal:** since Epic's June 2025 licence change, MetaHuman characters (including grooms and clothing) may be used in other DCCs and engines, Blender included. A real export is still Epic-derived character data and must stay out of git, as with the DNAs.
- **Community PR poly-hammer/character-dna-addon#328** ("Feature/groom export": custom `.cdgr` format and an Unreal commandlet) was **closed 2026-09-11 without merging**, after Interchange shipped Alembic groom export. It's a design reference only; its author calls it AI-written and unfinished.

### The export package (verified from Poly Hammer's own public docs, Fab listing and demo video; no field names)
- **In Unreal:** Interchange adds an **"Export Character For DCC"** action on a MetaHuman Blueprint. It needs **UE 5.8+** and is editor-only; it depends on the HairStrands, PythonScriptPlugin and RigLogic plugins. It also has a Python API (`ph_interchange`) and an RPC server.
- **Folder layout** (demo video, character "Grace"):
  - `Clothing/`, `Grooms/`, `Maps/`;
  - `body.dna`, `head.dna`;
  - `ExportManifest.json`;
  - `CharacterAssemblyManifest.json`.
  - The Fab listing says it's "laid out the same way MetaHuman Creator's own DCC export is". Textures are baked during export (the demo shows a progress bar "MI_Body_Baked_VT").
- **Grooms are written as Alembic `.abc`**, not a custom format.
- **`ExportManifest.json`** (MetaHuman Creator's own) is tiny: `metaHumanName`, `exportPluginVersion`, `exportEngineVersion`, `exportedAt`. It's in both of our fixtures.
- **`CharacterAssemblyManifest.json`** is Interchange's own format. Its field names are **unknown**; no sample exists publicly or on this machine. The docs mention schema **V1 and V2**; V2 "keeps each Unreal hair group's simulation settings and component overrides".
- **Assembly import options** (docs): Hair, Clothing, Materials, Lighting (bundled HDRIs), Camera, hair Collision Source (Body+Head+Outfit / Body+Head / Head Only), Skin Culling masks, Scene/Render (a Cycles template). It requires **Blender 5.2+** and UE 5.8+. Hair strands over "the validated 16-point limit" are clamped.

### Engine and format facts (verified)
- **Stock UE 5.8 can't export grooms at all.** It can *import* Alembic grooms (`AlembicHairImporter`); USD has a groom translator but no exporter. Epic's MetaHuman "Groom Exporter" is Maya → Unreal only. So getting MetaHuman hair out of Unreal needs Interchange or an exporter of our own.
- **Epic's public "Alembic for Grooms" schema:** `ICurves` plus `groom_version_major/minor`, `groom_group_id`, `groom_guide`, `groom_root_uv`, `groom_width`, `groom_color`, `groom_id`, `groom_closest_guides` and `groom_guide_weights`. A reader can target this public spec rather than Interchange internals.
- **Blender 5.1.2 Alembic round trip:** curves come back as a `Curves` object with `position`, `radius` and `resolution`. **Custom `groom_*` attributes were lost.** It's not yet known whether the exporter or the importer dropped them. VERIFY with a real Interchange `.abc`: root UVs and group IDs may need our own Alembic reading.
- **XPBD:** Blender 5.1 has no XPBD node. **Blender 5.2 LTS** (July 2026) adds the XPBD Solver node plus Hair/Cloth Dynamics node-group assets, still marked *experimental*.

## Character Assembly Slice 0 (2026-09-25): a real Interchange export, inspected
The source is the user's own character, exported with Poly Hammer Interchange's "Export Character For DCC".
- **Location:** `~/Downloads/NewMetaHumanCharacter/`, 539 MB, the only export `mdfind` finds.
- **Outside git:** it is outside both repos.
- **Never committed:** `character-dna-addon/.gitignore` now blocks `*.abc`, `*.dna` (the Ada and Default fixtures stay tracked), `CharacterAssemblyManifest.json`, `ExportPlan.json` and `tests/assembly_exports/`. Checked with `git check-ignore`.
- **Reading tools:** Alembic was read with Homebrew `alembic` 1.8.12 (BSD-3), plus two small C++ readers in the session scratchpad. `usd-core` has no Alembic plugin and PyAlembic isn't on PyPI. To remove the Homebrew package: `brew uninstall alembic`.

### Inventory
| Path | Size | Notes |
|---|---|---|
| `head.dna` / `body.dna` | 49.6 / 4.4 MB | |
| `CharacterAssemblyManifest.json` | 92.5 KB | schema_version 2 |
| `ExportManifest.json` | 2 KB | plugin 0.2.1, UE 5.8.3; `exportedAt` is **empty** |
| `ExportPlan.json` | 179 KB | **unexpected**: the Unreal-side plan (Blueprint classes, sockets, used slots) |
| `Geometry/head.json`, `body.json` | 14.3 / 9.0 MB | **unexpected**: per-mesh faces, uvs, source_slots, `visible_triangles` (the skin-culling mask) |
| `Grooms/` | 6 `.abc`, 104 MB | beard, eyebrows, eyelashes, fuzz, hair (82 MB), mustache |
| `Clothing/outfits.fbx` | 1.7 MB | all garments in one file |
| `Maps/` | 38 PNG, 360 MB | Head 12, Body 5, Eyes 6, Teeth 4, Shirt 6, Short 5, Hair 1 |
| `Meshes/` | empty | **unexpected** |

### Manifest schema (v2), verified
- Top-level keys: `schema_version` (2), `name`, `dna{head,body}`, `dna_geometry[]`, `rigs{}`, `components[]`, `materials[]`, `required_capabilities[]`, `diagnostics[]`, `source{blueprint, rule_version}`. Every path is relative with `/`.
- **`dna_geometry[]`:** `{id, role, origin "dna", path "Geometry/<role>.json", geometry_sha256, dna_sha256, occlusion, preserve_source_visibility, dependencies[], meshes[]}`.
  - Each mesh: `{mesh_index, lod, skin, material{source_index, slot "<dna>_shader_shader", name "mat_<hash>", slot_name_override, profile "creator"|"hidden", type, occlusion}}`.
  - Both SHA-256 values **match** the files on disk.
- **`rigs`:** `{head|body: {source "dna", geometry "dna", capabilities{valid, joints, meshes, lods}}}`, which gives head 870 / 50 / 8 and body 342 / 4 / 4.
- **`materials[]`** (18): `{name, type, slot, display_name (MI_…), profile, source_path, textures[]{role, path, color_space, recovery_source?}, skin?{show_top_underwear}, fabric?{…}, hair_color?{melanin, redness, tint, white_amount, roughness, color, ramps{root_to_tip, variation, white_strands}}}`.
  - Hidden: saliva (M_Hide), cartilage (M_Hide), and the eyelash card mesh (the groom replaces it).
  - Texture roles: base_color, normal, detail_normal, scatter, srmf, base_color_animated_cm1-3, normal_animated_wm1-3, teeth_mask_001/002, sclera/iris base_color and normal, veins, dust, ambient_occlusion, stitch_mask, micro_height, micro_normal, macro_variation, highlight_mask.
  - Oddities: CM1-3 are tagged **Non-Color** although they are colour maps. `recovery_source` appears on SRMF only and points at the Unreal asset.
- **`components[]`** (7): outfits (fbx, attach_to body, binding auto) and 6 grooms (alembic, attach_to head, binding surface). All transforms are identity.
  - Grooms carry `groom{width, root_scale, tip_scale, shadow_density, …}` and `groom_groups[]{group_id, physics{simulate (all false), sub_steps 5, iteration_count 5, strands_size 8, air_drag 0.1, bend_damping, bend_stiffness, collision_radius 0.1, …}, source{solver "ANGULAR_SPRINGS", gravity_cm_s2 [0, 0, −981], …}}`.
  - The "beard" component is the Goatee_S_ChinStrap asset.
- **`required_capabilities`:** semantic_components, source_slots, retained_rigs, surface_materials, section_filter, dna_provenance, skin_visibility, slot_aliases, groom_physics_groups.

### DNAs through our `dna_core.load`: both clean
| | LODs | joints | meshes | BS channels / targets | raw / GUI controls | PSD | RBF solvers | anim maps | LOD0 verts |
|---|---|---|---|---|---|---|---|---|---|
| head (MH.6) | 8 | 870 | 50 | 782 / 858 | 263 / 174 | 545 | 1 | 82 | 24,049 |
| body (MHB.1) | 4 | 342 | 4 | 0 / 0 | 176 / 0 | 0 | 72 | 0 | 30,455 |

Both files are file-format generation 2, version 8, with translation unit 0 (cm). Everything agrees with the manifest's `rigs.capabilities`, and the Geometry JSON vertex counts match the DNA.

### Grooms (Alembic)
- **Layout:** `/Groom` (Xform) contains `/Groom/Curves`, an `ICurves` with linear, non-periodic curves.
- **Geometry fields:**
  - `P` and `width` per point;
  - `uv` per strand: **the root UV. There is no `groom_root_uv`**; Interchange uses the standard parameter.
- **arbGeomParams:**
  - per strand: `groom_guide`, `groom_group_id` (always 0), `groom_id`, `groom_sim_curve_a/b`, `groom_sim_weight_a/b`;
  - per point: `groom_sim_vertex_a/b`, `groom_sim_lerp_a/b`;
  - hair only: `groom_color` per point (channel 2 is always 0);
  - eyebrows and mustache only: `groom_group_name` ('0');
  - hair and beard only: `groom_basis_type` / `groom_curve_type`.
- **Version tags:** `groom_version_major 1 / minor 4` and `groom_tool 'Maya 2018'` are on eyebrows, eyelashes, fuzz and mustache; hair and beard have none.

| attribute | scope | type | values in this export | in which grooms | after Blender 5.1 import |
|---|---|---|---|---|---|
| `P` | per point | float32×3 | cm, Z-up; hair Z 158-182 | all | `position` (axes changed to (x, −z, y), no scale) |
| `nVertices` | per strand | int32 | 4-45 points | all | kept (curve sizes) |
| `curveBasisAndType` | constant | uint8×4 | `1 0 0 0` = linear, non-periodic | all | `curve_type` |
| `width` | per point | float32 | hair 0.001-0.020; beard −0.0005-0.013 | all | `radius` = width / 2 (negatives kept) |
| `uv` (root UV) | per strand | float32×2 | 0-1, head LOD0 layout, no V flip | all | **dropped** |
| `groom_guide` | per strand | int32 | 0/1 | all | **dropped** (guides become ordinary strands) |
| `groom_group_id` | per strand | int32 | always 0 | all | **dropped** |
| `groom_id` | per strand | int32 | 0 … strands−1; guides share 0 | all | **dropped** |
| `groom_sim_curve_a/b` | per strand | int32 | guide index, −1 on guides | all | **dropped** |
| `groom_sim_weight_a/b` | per strand | float32 | 0-0.97 | all | **dropped** |
| `groom_sim_vertex_a/b` | per point | int32 | 0-8 (point on the guide) | all | **dropped** |
| `groom_sim_lerp_a/b` | per point | float32 | 0-1 | all | **dropped** |
| `groom_color` | per point | float32×3 | channels 0-1 in 0-1; channel 2 always 0 | hair | **dropped** |
| `groom_group_name` | per strand | string | '0' | eyebrows, mustache | **dropped** |
| `groom_basis_type` / `groom_curve_type` | per strand | string | 'NoBasis' / 'Linear' | hair, beard | **dropped** |
| `groom_version_major/minor`, `groom_tool`, `groom_properties` | xform user property | int32 / string | 1 / 4, 'Maya 2018', 'AbcExport …' | eyebrows, eyelashes, fuzz, mustache | **dropped** |

Re-checked 2026-09-25: Blender 5.1.2 imports all six files in under 30 ms each. Each result is a CURVES object whose only attributes are `position`, `curve_type` and `radius`; it has no surface, no UV map and no modifiers.

| groom | strands | points | pts/strand | guides |
|---|---|---|---|---|
| beard | 16,793 | 188,545 | 4-21 | 268 |
| eyebrows | 4,881 | 67,806 | 5-15 | 613 |
| eyelashes | 610 | 6,380 | 4-12 | 289 (all at the origin) |
| fuzz | 75,737 | 407,335 | 4-14 | 31,187 (all at the origin) |
| hair | 112,776 | 1,721,726 | 4-25 | 987 |
| mustache | 1,476 | 58,971 | 6-45 | 191 |

- **Anomalies:**
  - Guide strands in eyelashes and fuzz are collapsed to (0, 0, 0), so they must be filtered on `groom_guide`.
  - 67 beard render strands have **negative widths** (min −0.0005).
  - Guide widths are 0 or 0.001.
- **Blender 5.1.2 `wm.alembic_import`:**
  - Result: each file becomes a CURVES object named "Groom".
  - Kept: `position`, `curve_type` and `radius` (= width / 2 exactly; negative values kept).
  - **Dropped:** `uv`, `groom_guide`, `groom_group_id`, `groom_id`, `groom_color`, `groom_group_name`, `groom_basis/curve_type`, all `groom_sim_*` and the version properties. Guides import as ordinary strands, and no surface or UV map is set.
  - This settles the scoping spike's open question: **the importer drops them**, since the file has them.
- **Axes and scale:** the file is Z-up cm. Blender's importer maps a file point (x, y, z) to (x, −z, y) with no scaling. The correct placement against head.dna (converted to Blender as (x, −z, y)) is **(x, −y, z) / 100 m**.
  - Median distance to the head surface: eyebrows 0.16 cm, eyelashes 0.13, mustache 0.14, beard 0.26, hair 0.62.
  - Mirror or 180° turn? Point distance alone couldn't tell (the head is too symmetric: mean X asymmetry 0.22 cm).
  - **Root UVs settle it.** For each strand, find the head LOD0 vertex with the nearest UV and compare positions:
    - mirror (x, −y, z): median 0.05-0.30 cm;
    - rotation (−x, −y, z): 3.3-8.9 cm.
  - The UVs also map onto the head's LOD0 layout **without a V flip** (flipping gives 2.6-17 cm).

### Clothing FBX (Blender 5.1.2 FBX import)
- One skinned mesh (13,894 verts, 57 vertex groups, UV `DiffuseUV`) under an empty.
- Its own armature has 341 bones rooted at `pelvis`.
- It has 8 material slots (`…_Short`, `…_Shirt`, `…_Short_2` … `…_Shirt_7`) against 2 manifest materials. These are probably LOD copies; not verified.

### Existing importer against this export
- The importer looks for `Maps/` next to the .dna, so it would find: Head base, normal, CM1-3 and WM1-3; Body base and normal; Teeth colour and normal (through the `ALTERNATE_…` table and .png extension).
- **Eyes find nothing.** `materials.blend` expects `eyes_color_map` / `Eyes_Color` and `Eyes_Normal`, but the export has Sclera/Iris Basecolor and Normal, Veins and Dust. That is the likely cause of the "eyes import without textures" pain point.
- `Eyelashes_Color` doesn't exist either: lashes are a groom.
- Not wired anywhere: SRMF, Scatter, DetailNormal, teeth masks, clothing maps and the hair highlights mask.

### Decision recorded
- The spec and FINDINGS live in `~/metahuman-addon`, a separate git repo with no commits so far, not in the GPL addon repo.
- The Slice 0 doc commit is therefore split across **two branches named `docs/assembly-slice0`**:
  - in `character-dna-addon`: `.gitignore` only;
  - in `metahuman-addon`: `specs/08-character-assembly.md` and `docs/FINDINGS.md` only.
- Neither branch is merged. This is reversible: the files can be copied into the addon repo instead if wanted.
- `specs/08-character-assembly.md` was rewritten against the real data. Main changes:
  - the manifest is the entry point;
  - hair is in the export;
  - a custom Alembic reader is needed;
  - the eye texture names differ;
  - clothing is FBX;
  - a slice table was added.
- **Update (2026-09-25):** approved. Both documents now live in this repo, as `dev-docs/FINDINGS.md` and `dev-docs/specs/08-character-assembly.md`. The two-branch split above is superseded, and the copies in `~/metahuman-addon` were removed there in a commit.

### Slice 0 decisions (user, 2026-09-25)
1. Docs move to this repo (`dev-docs/`).
2. Slice 1 includes the eye-texture fix (by manifest role) and hiding meshes whose material profile is `"hidden"`.
3. Alembic reader: decide at the start of Slice 2.
   - First, timebox about 1 day on a minimal numpy Ogawa reader (P, width, uv, groom_guide, groom_color) and benchmark it on the 1.72M-point hair.
   - Fall back to a native library only if that is clearly too slow.
   - Keep the Homebrew alembic tools for validation.
4. Minimum Blender stays 5.1. Hair physics is gated to 5.2+ and disabled with a clear message on 5.1.
5. Body-under-clothes hiding goes in Slice 3, with clothing.
6. SRMF channels: work them out from the images, and state confidence per channel.
7. Fuzz: import it hidden in the viewport, enabled for render, with a one-click toggle.

## Character Assembly Slice 1 (2026-09-25): import from the manifest, textures by role
Branch `feature/assembly-import`. **File > Import > MetaHuman Assembly (CharacterAssemblyManifest.json)** does four things:
- imports head and body through the existing DNA importer, via the new shared `operators.import_character`, into one rig instance;
- wires every texture of the DNA meshes' materials by **manifest role and colour space**, never by file name;
- hides the meshes whose material profile is `"hidden"`;
- writes a report to the Text datablock `<instance>_assembly_report`.

Code layout:
- `dna_core/assembly.py` (no bpy): manifest reader, path safety and the texture plan.
- `assembly/materials.py`: node building.
- `assembly/importer.py` and `assembly/operators.py`: the pipeline and the operator.

### Result on the user's export (real data, Blender 5.1.2)
- **Textures:** 28 connected, 4 loaded but not connected (teeth masks ×2, eye dust ×2), 12 deferred (clothing: Slice 3; hair highlight mask: Slice 2). 0 missing, 0 failed.
- **Hidden:** with the default LOD0 import, `saliva_lod0`, `eyelashes_lod0` and `cartilage_lod0` are hidden in viewport and render, and tagged `character_dna_assembly_hidden`. The LOD switch now skips tagged objects; it used to show `eyelashes_lodN` again.
- **Integrity:** DNA SHA-256 matches the manifest. The head's Texture Logic node and its 41 wrinkle-mask drivers are intact.
- **Timing:** 11.7 s in background mode; 12.9 s for the first import of a fresh GUI session; 15.6 s for a repeat import.
  - One outlier, not reproduced: 210 s on the very first GUI launch of a brand-new sandbox profile. The profile showed the assembly step itself is about 0.6 s; the rest is the existing DNA import. Cause unknown (first-run GPU shader compilation is a guess, not verified).
- **GUI screenshots** (sandbox profile, packaged build): face close-up, eyes close-up, full body, head skin node tree (overview and detail).

### Eye shader (the "eyes import without textures" fix)
- **Layout, measured:**
  - In the eye mesh's UVs the front of the eye is at (0.5, 0.5).
  - A UV radius of 0.15-0.175 is 0.585-0.68 cm from the eye's axis. The human limbus is at about 0.59 cm.
  - `Eyes_ScleraBasecolor` is plain grey inside a radius of about 0.15 (low saturation, 0.02-0.03), where the iris goes.
  - `Eyes_IrisBasecolor` / `Eyes_IrisNormal` fill their whole 0-1 square: the pupil reaches a radius of about 0.11, and the iris-normal detail reaches about 0.48.
- **So:** the iris maps are scaled into the disc of **radius 0.155** at the UV centre, blended across a 0.012-wide smoothstep limbus. Both values are labelled Value nodes you can tune.
  - Veins multiply the sclera. The sclera map already contains some veins, so the default multiply may darken them.
  - Dust is loaded but not connected, because how Unreal applies it isn't verified.
- **Verified visually:** iris fibres, pupil and veined sclera in EEVEE renders and in Material Preview (screenshots).

### Normal maps are DirectX style (verified by curl)
- **Method:** a real tangent-space normal map is the gradient of a height field, so its curl is about 0 only when read with the right green-channel sign.
- **Results** (curl read as OpenGL / as DirectX; lower is the right convention):

| Map | OpenGL | DirectX |
|---|---|---|
| Head_DetailNormal | 0.107 | **0.031** |
| Eyes_IrisNormal | 0.031 | **0.006** |
| Eyes_ScleraNormal | 0.014 | **0.003** |
| Teeth_Normal | 0.079 | **0.060** (weak) |
| Head_Normal (8K, subsampled) | 0.021 | **0.018** (weak) |
| Body_Normal (8K, subsampled) | 0.020 | **0.017** (weak) |

- **Conclusion:** all DirectX, consistent with the existing Texture Logic's DirectX→OpenGL flip. The new eye and teeth normals are flipped the same way.

### SRMF, worked out from the images (Head_SRMF and Body_SRMF: 8K, RGBA)
| Channel | Reading | Confidence | Wired to |
|---|---|---|---|
| R | Specular. A pore and cavity pattern, darker in creases; mean 0.60 (head) / 0.60 (body). Unreal's Specular 0.5 means F0 4%, the same scale as Blender's Specular IOR Level. | medium-high | Principled Specular IOR Level |
| G | Roughness. Regional: lower on the nose, higher on the lips and the stubble area above the lip; mean 0.66 / 0.69, typical skin values. | medium-high | Principled Roughness |
| B | Metallic. Exactly 0 everywhere, as expected for skin. | high | Principled Metallic |
| A | Probably a fuzz (peach-fuzz / sheen) mask: white on the skin, black on the lips and inside the eyes. Could also be a cavity or flush mask. | low-medium | **not connected** |

`Head_Scatter` / `Body_Scatter` are greyscale (R = G = B); head 0.53-0.65, body 0-0.64. They're wired to Subsurface Weight, as sRGB (the manifest's tag).
- Subsurface Scale is 0.003 m and Radius (1, 0.35, 0.2). These are starting values, not measured.
- Medium confidence.

`Head_DetailNormal` and `Body_DetailNormal` have identical statistics: they're one tiling pore map. It's whiteout-blended into the main normal (tiling 16, strength 0.35). **Unreal's tiling isn't in the export; low confidence.** Both values are tunable nodes.

Teeth masks, loaded but not connected; the channel meanings are guesses:
- `Mask001`: R = teeth vs gums, G = mostly white with darker tooth tips, B = tongue speckle, A = tongue mask.
- `Mask002`: R = depth / occlusion gradient, G/B = gum-line and tooth-edge outlines.

### Mismatch with the spec: this export's wrinkle maps are DELTA maps
- **Stats:**
  - `Head_Basecolor_Animated_CM1-3` (512²) average 0.495 in every channel (sd 0.01-0.02).
  - `Head_Normal_Animated_WM1` (1024²) averages 0.497-0.498 in R, G **and B**. A real tangent normal map has B ≈ 1, like `Head_Normal`'s 0.999.
- **So:** these are offsets from the base maps, and the manifest's `Non-Color` tag on CM1-3 is correct.
- **The problem:** the inherited Texture Logic (`MergeMaps`) *mixes towards* each wrinkle map as its mask rises. With delta maps an active wrinkle turns the skin flat grey or teal.
  - Reproduced: with all 41 mask inputs forced to 1, the face renders dark teal (`6_wrinkle_masks_off_vs_all_on.png`).
  - At rest (all masks 0) the look is right.
  - This also affects the plain DNA import of such exports (it loads the same files), so it isn't new in Slice 1. But the spec's "wrinkle maps already work" is **false for this export format**. Open question for the user.

### Tests and proof
- **`tests_core/test_assembly.py`:** 20 tests on a synthetic v2 manifest (`tests_core/synthetic_assembly.py`, no Epic data). They cover:
  - schema versions;
  - path escapes (absolute, `..`, drive letters);
  - colour space from the manifest, not the file name;
  - the eye roles;
  - missing files, hidden meshes, deferred components and unknown roles;
  - report contents;
  - SHA mismatch.
  - Full suite: 86 passed with the bindings required.
- **`scripts/ci/assembly_materials_check.py`** (CI register job, bpy 5.1 and 5.2, macOS and Windows): the real wiring code against the add-on's own material templates. 32 checks, including eyes, skin, teeth, colour spaces, hidden meshes and hidden meshes surviving an LOD switch.
- **Mutation checks** (each fix reverted, then restored byte-identical):
  1. Eye wiring removed: the CI check exits 1.
  2. Eye roles dropped from the plan: 3 pytest failures, including `test_eye_textures_are_connected_by_role`.
  3. LOD switch ignoring the hidden tag: the CI check fails with "LOD 0 switch keeps the eyelash card hidden".

### Dead ends and gotchas
- **Test-helper hazard, found and fixed before commit:** the synthetic-export writer first created a stand-in file at *every* manifest path, including the deliberately escaping ones. The `/etc/passwd` case failed only on permissions, and nothing was modified (checked). It now writes only inside the export folder.
- **GUI harness:**
  - `bpy.ops.screen.screenshot` doesn't capture popup menus.
  - `wm.call_menu` from a timer doesn't show a menu.
  - Node-editor `view_selected` from a timer only takes effect on the next real event. A simulated NUMPAD_PERIOD key over the editor works.
- **Hiding the eyelash card mesh leaves the character without lashes until Slice 2** imports the eyelash groom.

## Character Assembly Slice 2 (2026-09-26): grooms
Branch `feature/assembly-grooms`. The assembly import now also brings in every `alembic` component as a Blender hair Curves object attached to the head. An import option, **Grooms**, is on by default.

Code layout:
- `dna_core/alembic.py`: a minimal numpy Ogawa reader.
- `dna_core/grooms.py`: reading a groom and converting it for Blender. No bpy.
- `assembly/grooms.py`: the Blender side.
- `assembly/ui.py`: the Grooms sidebar panel.

### Reader: numpy Ogawa, no native library needed
- **Layout source:** the Alembic reference implementation (BSD-3; `lib/Alembic/Ogawa`, `AbcCoreOgawa/ReadUtil.cpp`). The layout, in brief:
  - a 16-byte header, then groups of `uint64` child offsets, where bit 63 marks a data block;
  - archive root: [2] the top object, [5] the indexed metadata;
  - object: [0] its properties, children, [last] the headers;
  - compound: one group per property, [last] the headers (bit-packed `info`);
  - array sample: [2i] 16-byte key plus values, [2i+1] dimensions.
- **Correctness:** on all six real grooms, P, nVertices, width, uv and groom_guide are **identical** to the dumps made with the reference C++ library in Slice 0.
- **Speed** (file cached, including reading the file into memory):

| Groom | Read time |
|---|---|
| hair (1,721,726 points) | **52 ms** |
| fuzz | 11 ms |
| beard | 5 ms |
| the other three | under 2 ms each |

- This was well inside the 1-day timebox, so the native-library fallback wasn't needed.
- **Test fixture:** `tests_core/fixtures/synthetic_groom.abc` (2.2 KB), written by the reference library from `fixtures/make_synthetic_groom.cpp`. It has 4 strands, one of them a guide at the origin, and one negative width. It's the only `.abc` that `.gitignore` allows.

### Import on the user's export (Blender 5.1.2)
- **Timing:** 12.1 s for the whole import in the background, 12.0 s in the GUI. The grooms' own share is about 0.2 s; hair takes 0.14-0.19 s to read, convert and build.

| Groom | In the file | Guides | Imported | Points | Notes |
|---|---|---|---|---|---|
| hair (scalp) | 112,776 | 987 | **111,789** | 1,713,051 | |
| fuzz | 75,737 | 31,187 | **44,550** | 267,300 | hidden in the viewport, renders |
| beard | 16,793 | 268 | **16,525** | 186,659 | 67 negative widths clamped |
| eyebrows | 4,881 | 613 | **4,268** | 64,020 | |
| mustache | 1,476 | 191 | **1,285** | 57,825 | |
| eyelashes | 610 | 289 | **321** | 3,852 | |

- **Conversion:** file (x, y, z) cm → Blender (x, −y, z) / 100 m. Radius = width / 2, in metres, with negatives clamped to 0. Curve type POLY, since the file says linear.
- **Extra data:** `groom_color` is kept as a point attribute (hair only).
- **Transform:** positions go into the head's space; the head sits at identity on import.
- **Root UVs** match the head's `DiffuseUV` as-is, with no V flip: the median distance from a root to the skin is 1.0 mm, against 138 mm with V flipped.

### Surface attachment
- **Setup, per groom:**
  - `curves.surface = head_lod0_mesh`, with `surface_uv_map` set;
  - a `surface_uv_coordinate` (FLOAT2, per curve) attribute holding the root UVs;
  - a Geometry Nodes modifier running **Deform Curves on Surface** (shared node group "Character DNA Attach To Surface");
  - the curves object parented to the head.
- **Needed:** the head needs **`add_rest_position_attribute = True`**. Without it the node warns `Evaluated surface missing attribute: "rest_position"` and doesn't deform.
- **Verified on the real rig**, in background Blender with `--enable-autoexec` so the rig's Python drivers run: brows raised (brow_raiseIn/Out L and R = 1) and eyes widened (eye_blink L and R = −1).

| Groom | Roots | Skin under roots moved (median) | Roots moved (median) | Median gap | 95th pct gap |
|---|---|---|---|---|---|
| eyebrows | 4,268 | 10.40 mm | 10.39 mm | 0.175 mm | 0.47 mm |
| eyelashes | 321 | 2.95 mm | 3.00 mm | 0.055 mm | 0.16 mm |

  The gap is the nearest-vertex measurement's own error.
- **Also verified:** rotating the body rig's `head` bone moves the skin a median 50.6 mm and the brow roots 50.7 mm.
- **Gotcha, not a bug:** in Blender 5.1, `Object.shape_key_add()` creates the new key at **value 1.0**. A test that adds a "lift" key and reads the "before" state is therefore already lifted. I first misread this as Deform Curves on Surface failing on shape-key-only surfaces; that was wrong, and it works.

### Hair material
- **Principled Hair BSDF** (Chiang model, melanin parametrisation) with Melanin, Melanin Redness, Tint and Roughness as exported, on a **Cycles** output.
- **Not mapped:** `white_amount` and the colour `ramps`, which have no input on Blender's hair shader. The report lists them.
- **EEVEE mismatch:** EEVEE rendered the hair ginger-brown, then red-brown. Superseded; see "Slice 2 follow-up: EEVEE and widths" below for the real cause and the fix.
  - The resolved colour is also the material's viewport display colour.
- **Hair highlight mask** (`Hair_HighlightsMask`): loaded into the hair material, not connected, since Principled Hair has no input for it.

### Fuzz, eyelash card, panel
- **Peach fuzz:** `hide_viewport = True`, `hide_render = False`.
  - The **Grooms** sidebar panel lists each groom with its strand count and one-click viewport and render toggles. A real click was tested in the GUI.
  - **EEVEE renders:** EEVEE draws strands at least 1 px wide, so the 0.02 mm fuzz becomes a pale frost over the face. Cycles renders it correctly.
- **Eyelash card mesh:** hidden only when the eyelash groom imported; otherwise it stays visible and the report says why. This changes Slice 1's behaviour, where it was hidden whenever the manifest said so.

### Not done / open
- **Unreal's groom overrides** aren't applied: `groom.width` (for example hair 0.012 cm, brows 0.018 cm) and the root/tip scale (tip 0.45-0.75). The file's own widths are used, as specified.
- **Physics** stays off, and the `groom_groups` physics settings are ignored.
- **Wrinkle maps:** the brow-raise screenshot shows the known delta wrinkle-map problem (white forehead). That's the next task after Slice 2.

### Tests and proof
- **`tests_core/test_grooms.py`:** 7 tests on the fixture: the archive tree, values as written, the axis and units, guide dropping, radius and clamping, not-an-Alembic, and the hair-shader mapping.
- **`test_assembly.py`:** updated for groom components (region, hair_color); the full suite is **94 passed**.
- **`scripts/ci/assembly_grooms_check.py`** (CI register job, macOS and Windows, bpy 5.1 and 5.2): 27 checks against a UV grid standing in for the head. Among them: roots follow a +0.1 m shape-key lift exactly, and the eyelash card rule.
- **Mutation checks** (restored byte-identical afterwards):
  - **A. Axis conversion replaced by Blender's own Alembic mapping (x, −z, y), unscaled:** `test_blender_frame_is_x_minus_y_z_in_metres` fails.
  - **B. Guides kept:** `test_guides_are_dropped` fails, and the CI grooms check exits 1 with "3 strands, 8 points (the guide dropped)".

### Slice 2 follow-up (2026-09-26): EEVEE and widths
- **Cause of the EEVEE hair colour:** in Blender 5.1, EEVEE doesn't shade hair at all. `gpu_shader_material_hair.glsl` (v5.1.2) implements both `node_bsdf_hair` and `node_bsdf_hair_principled` as a placeholder `ClosureDiffuse` of the node's **Color** input; melanin, roughness, coat and IOR are ignored.
  - In **melanin** mode EEVEE therefore used the Color socket's unused default (a brown), which rendered ginger.
  - In **colour** mode it used Unreal's resolved colour as a flat diffuse, with no specular. That colour, linear (0.006, 0.0014, 0.0003), is near-black but strongly red. Under the dim Material Preview HDRI it reads black (scalp about 0.01 in every channel); under a bright key light the red shows (scalp 0.106, 0.031, 0.010).
- **The EEVEE output was in effect all along:** `get_output_node("EEVEE")` returns it, and a render with it forced to pure green came out green.
- **Fix:** EEVEE's output is now a **Principled BSDF**: base = resolved colour, roughness = exported roughness, IOR 1.55. Its specular highlight is what makes near-black hair read neutral, as Cycles' hair lobes do.
  - Mean scalp colour: EEVEE (0.278, 0.246, 0.238) against Cycles (0.264, 0.236, 0.231). Before the fix, EEVEE was (0.106, 0.031, 0.010).
- **Strand shape:** `scene.render.hair_type` defaults to **STRAND**, which draws every strand at least 1 px wide, so the beard and brows looked heavy and the fuzz frosted. The import now sets **STRIP** (real widths); the report notes it. With Strip the fuzz frost is gone, at 0.75 m and at a 0.28 m close-up, so the fuzz stays visible to EEVEE.
- **Match Unreal Widths** (import option, **off** by default):
  - replaces the file's widths with the component's `groom.width` (cm), tapered linearly by point index from `root_scale` to `tip_scale`;
  - for example hair is 0.012 cm, tip at ×0.45; brows 0.018 cm, tip at ×0.75;
  - in Cycles, brows come out much fuller and darker, and hair slightly denser.
- **Slice 1 status check:**
  - **Disabling the wrinkle maps for delta-format exports did *not* land.** It was an open question, never implemented. The wrinkle-map fix PR covers it.
  - **The test-helper path guard did land in PR #10.** `synthetic_assembly.write_export` only writes inside the export folder. A regression assertion now checks no file is created outside it.

## Wrinkle offsets (2026-09-26): wrinkle maps stored as offsets now blend as offsets
Branch `feature/wrinkle-offsets`. This fixes the Slice 1 finding that the export's CM/WM wrinkle maps are **offsets centred on 0.5**. The inherited Texture Logic mixes *towards* each map, which turns active wrinkles white or grey. (Disabling the wrinkle maps for this format never landed in Slice 1; this replaces that idea.)

### How the inherited logic works (materials.blend)
- Each of the 41 region masks is a region of the `combined_masks` atlas, times its rig value (a driver writing to the Texture Logic node's input **by index**, `inputs[27]` and so on).
- The masks are summed per wrinkle map into three weights: WM1 (plus lips), WM2 and WM3 (plus lips).
- `MergeMaps` then mixes the base towards CM*n* / WM*n* by those weights, for colour and normal. A third instance makes the mask preview.
- The inner group `head_shader_logic.004` is **shared by every character** in the file.

### The fix (`dna_core/wrinkles.py`, `assembly/wrinkles.py`)
- **Detection**, from the images: the CM1 mean is within 0.05 of 0.5 in every channel, and the WM1 blue mean is within 0.1 of 0.5 (full normal maps have about 1).
  - On this export: CM1 is (0.496, 0.495, 0.496) and WM1 is (0.498, 0.498, 0.497), so it's detected.
  - Full maps (older exports) keep the inherited mix untouched.
- **What switching does:**
  - the character gets its own copy of the inner group, `<instance>_head_shader_logic_offsets`;
  - its colour and normal `MergeMaps` become offset merges: `base + Σ weight_i (map_i − 0.5) × gain`, clamped at 0;
  - the CM/WM images are set to Non-Color.
- **Colour offsets are summed in sRGB space:** base^(1/2.2), plus the offsets, then ^2.2. Summed in linear space, the CM1 crease offsets (about −0.09 in every channel) collapse green and blue on skin: linear G 0.155 → 0.065 (−58%) against R −27%. The creases of a brow raise rendered as **orange lines**. Summed in sRGB, the drops are −21% / −15%: a natural darkening.
  - Evidence: renders "linear vs sRGB", and a CM1 offset visualisation (dark creases with a slight flush between them).
- **Normal offsets** are added in their encoded 0–1 form. The Texture Logic's DirectX flip and Normal Map node follow as before.
- **Per-area strength:** each region mask is multiplied by the strength of its facial area:

| Area | Masks |
|---|---|
| Brows | raise inner/outer, down, lateral |
| Eyes | blink, squint |
| Nose | wrinkler |
| Cheeks | cheek raise inner/outer/upper, smile |
| Mouth | purse, lips, mouth stretch |
| Chin & Jaw | chin raise, jaw open |
| Neck | neck stretch |

  - All 41 masks map to an area.
  - The strengths and one **Wrinkle Gain** are appended **at the end** of the Texture Logic node's inputs, so every driver index stays valid (checked), and all default to 1.
  - A **Wrinkles** sidebar panel shows them for a character in offset mode.
  - **Gotcha:** a socket added to a node group's interface appears on existing nodes with value 0, not the socket's default. Left alone, all strengths would have been 0 and the wrinkles silently off. The code sets each new input to 1.
- **Where it applies:** the assembly import (the report notes it), and also the plain DNA import (`components/base.import_materials` for the head), so an Unreal 5.6+ folder imported through Import DNA gets it too.
- **Scale:** Unreal's exact wrinkle scale isn't in the export. Strength 1 and gain 1 are starting values; the results look natural but subtle.

### Proof
- **Before/after renders** of the user's character, EEVEE and Cycles, the same pose through the real rig (`--enable-autoexec`):
  - brow raise: brow_raiseIn/Out;
  - smile: mouth_cornerPull plus eye_cheekRaise;
  - squint: eye_squintInner plus eye_cheekRaise 0.6.
  - Before: white and black patches. After: forehead lines, crow's feet and smile lines, no artefacts.
- **`tests_core/test_wrinkles.py`:** 7 tests: every mask has an area, detection (the real stats, full maps, mixed cases), the blend maths, and sRGB against linear (channel spread under 1.3 in sRGB, over 2 in linear).
- **`scripts/ci/wrinkle_offsets_check.py`** (CI register job): 13 checks on the add-on's own head material with synthetic maps. Full maps are untouched; offsets switch; driver indices are kept; strengths are appended and equal 1; the per-character group copy; the other character keeps the shared mixing group; 41 masks are scaled; the images are Non-Color.
  - It also runs a **Cycles bake of both merge groups**, compared with the numpy reference: colour (0.21397, 0.08182, 0.05754) and normal (0.62, 0.40, 1.0) match to five decimals.
- **Mutation checks** (restored byte-identical):
  1. The sRGB step removed: the bake check fails, with baked (0.222, 0.047, 0.022) against reference (0.214, 0.082, 0.058).
  2. Masks not scaled by area strength: the CI check fails.
  3. Detection disabled: `test_offset_detection` fails, and the CI check fails.

### Crown specks (2026-09-26): malformed strand points, repaired on import
- **The symptom:** orange and white specks on the crown in Cycles. They stayed put from 64 to 1024 samples, so they're geometry, not fireflies.
  - Zoomed in at 6000 px, they were **flat fins** several millimetres wide: far wider than any strand's radius (hair at most 0.1 mm, fuzz 0.011 mm).
  - Hiding the fuzz removed the biggest (orange) fin; the hair produced the rest.
- **Ruled out** by scanning every strand of all six grooms: NaN or infinite values, zero-length strands, segment spikes, width spikes, far-flung roots or tips, and bad surface attachment. The last check compares every evaluated strand with the original: 0.00 mm movement, length ratio exactly 1.
  - **Gotcha:** a groom hidden in the viewport (the fuzz) isn't evaluated by the viewport depsgraph, so `evaluated_get` returns the original. Unhide it before checking what the attach modifier does to it.
- **Cause:** per-segment defects that Cycles' ribbon hair can't orient.
  - The hair has **43,300 repeated consecutive points** (zero-length segments) in 21,534 strands.
  - Several grooms contain single-point **hairpin spikes**, where consecutive segments turn more than 120°. Real curls here turn about 25° per segment.
- **Fix:** `dna_core.grooms.repair_strands`, run on import.
  - It merges consecutive points closer than 20 µm (under every groom's strand width) and drops interior points that turn more than 120°. It repeats until clean, and never touches a strand's root.
  - A strand left with fewer than 2 points is dropped.

| Groom | Repeated points | Spike points | Strands dropped |
|---|---|---|---|
| hair | 43,835 | 1,081 | 0 |
| beard | 783 | 2,569 | 36 (16,525 → 16,489) |
| mustache | 16 | 150 | 0 |
| fuzz | 91 | 94 | 0 |
| eyebrows | 0 | 1 | 0 |
| eyelashes | 0 | 0 | 0 |

  - The hair's repair takes about 0.3 s.
  - The counts are in the import report.
- **Result:** the fins are gone in both the crown crop and the zoom. The beard looks unchanged, before against after. One faint glint remains: an ordinary highlight on a strand tip.
- **Also this round:** Match Unreal Widths is now **on by default**, still an import option. Specs 07 and 09 are reworded neutrally.
