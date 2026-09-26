# 02: Fork of the free addon and the Windows build (plan for review)

Status: **plan only, nothing implemented.** Written 2026-09-21 after the Day-1 spike (`docs/FINDINGS.md`).

## Decisions recorded (from the human)
- **Approach:** fork `poly-hammer/character-dna-addon` (GPL-3.0). No clean-room rebuild of the base. Pro features are still clean-room (CLAUDE.md).
- **Platforms:** macOS arm64 (this machine) and Windows x64 only. No Linux, no Intel Mac.
- **Q1, Blender versions (decided 2026-09-21):** **5.x only** (Python 3.13). No 4.5 LTS for now, so the build matrix is 2 platforms x py313.
- **Q2, license (decided):** **GPL-3.0.**
- **Q7, evaluation (decided):** **Python evaluation** through Epic's `riglogic` bindings (spike: `calculate()` about 0.13 ms/frame). No native module for now.
- **Q6, test DNAs (decided, done):** git-lfs installed and the 4 UE 5.6/5.8 exports pulled into `~/character-dna-addon`. **Spike step 7 now passes** (FINDINGS "Step 7").
- **Epic issues:** both drafts approved as-is for filing (§6).

---

## 1. License check (done)

| Item | Result |
|---|---|
| Repo | `poly-hammer/meta-human-dna-addon` **was renamed** to [`poly-hammer/character-dna-addon`](https://github.com/poly-hammer/character-dna-addon) (the old URL redirects). Public, not archived, last push 2026-09-19. HEAD checked: `61525f6` (2026-09-16). |
| `LICENSE.md` | **GNU GPL v3, verbatim** (a diff against gnu.org's `gpl-3.0.txt` shows only markdown list renumbering). GitHub reports `GPL-3.0`. |
| README | "licensed under the GNU General Public License v3.0". Third-party parts: OpenRigLogic (MIT), Sentry SDK (MIT), ufbx (MIT). Includes an Epic trademark / nominative-use notice. |
| Inconsistency | `pyproject.toml` has the classifier `GNU Lesser General Public License v3 (LGPLv3)`. The LICENSE file and README both say GPL-3.0; treat the classifier as a stale mistake (the LICENSE file governs). |
| Fit with our plan | **Compatible with open / source-available only if "source-available" means GPL-3.0.** Our fork and everything derived from it must be distributed under GPL-3.0 with full corresponding source (including our clean-room Pro editors if they ship inside the same addon). We can sell it, but buyers get GPL rights and can redistribute. A more restrictive "source-available" license (e.g. no redistribution, non-commercial) is **not** allowed for a derivative of GPL code. **Q2:** confirm GPL-3.0 is what you mean; if not, forking is the wrong choice. |

## 2. Fork: created 2026-09-21

Public fork: https://github.com/highlighthousefc-ai/character-dna-addon (main branch only).


- `gh` is not installed and I have no GitHub credentials, so **I have not created the fork**. I cloned upstream read-only to `~/character-dna-addon`, with the remote named `upstream` (not `origin`), so a fork remote can be added cleanly.
- Needed from you (either option works):
  - **Option A (web, one click):** go to https://github.com/poly-hammer/character-dna-addon, click **Fork**, keep the name or rename it, and send me the fork URL.
  - **Option B (CLI):** `brew install gh`, then run `gh auth login` yourself (it asks for your GitHub login; I must not enter credentials). Then I run `gh repo fork poly-hammer/character-dna-addon --remote=false` and add it as `origin`.
- **Do not** clone with `--recurse-submodules`: see `editors` below.

## 3. Structure map vs. what the spike proved

Package `src/addons/character_dna/` (about 25k lines of Python; manifest id `character_dna`, version 0.13.7, `blender_version_min 4.5.0`, `max 5.3.0`).

| Area | Size | What it is | Relation to our spike / plan |
|---|---|---|---|
| `bindings/__init__.py` | 380 lines | Loader for OpenRigLogic SWIG bindings from `bindings/<os>/<arch>/<py311\|py313>/`. Registers an **`IsolatedModuleLoader`** on `sys.meta_path` (the hook Epic's generated `dna.py`/`riglogic.py` look for), loads `dna` then `riglogic`, **strips bare `dna`/`riglogic`/`_py3*` names from `sys.modules`** afterwards and nulls `__file__` so Blender's policy check stays quiet. Also `os.add_dll_directory` on Windows. | **This is the name-collision fix we need, already written and GPL.** Our staged files (`dna.py`, `riglogic.py`, `_py3dna13_2_9.so`, `_py3riglogic13_2_9.so`) match what it expects. See §3.1. |
| `bindings/<os>/…` folders | **absent** | The compiled bindings are **not in the public repo**. The manifest says "Platform-specific RigLogic bindings (available at polyhammer.com)". CI checks them out from **private** `poly-hammer/character-dna-bindings` (404 publicly) using a secret token. | We must supply our own. Our macOS arm64/py313 build from the spike drops straight in. Windows is §5. |
| `_riglogic_blender` native runtime | **absent, no source** | Loaded by `bindings.load_native_runtime()` and required by `runtime/engine.py` (`capability()` needs `load_model`, `create_session`, `create_frame_plan`, `evaluate_frame`, `control_snapshot`, `capabilities`). **Live auto-evaluation (driving bones/shape keys on frame change) refuses to run without it** (`controller.py` raises "Native runtime unavailable"). It ships in the same private bindings repo. | **Biggest finding.** Forking does *not* give us working real-time evaluation. The free code still builds plain `riglogic.RigLogic`/`RigInstance` objects for one-off authoring calculations (`rig_instance.py:1052`, `runtime/authoring.py`), which our bindings support. See §4. |
| `editors/` | git **submodule** → `poly-hammer/character-dna-addon-editors` (**private**, 404) | The Pro editors. "Pro" is decided only by whether `editors/__init__.py` exists (`utilities/misc.py: editors_available`, `pro_features_visible`). **No license-key check in the public code.** | Keep the submodule **uninitialised**, never fetch it, remove it from our fork's `.gitmodules`. Our clean-room editors go in a **differently named package** with our own registration API, not written to match the private module's interface. |
| `typing.py`, `properties.py`, `ui/*`, `rig_instance.py`, `dna_io/calibrator.py` | — | Hooks that call into `editors` (`register_property_groups`, `draw_preferences`, `is_pro` branches) plus `TYPE_CHECKING` imports naming private Pro modules. | Clean-room hazard: these names reveal parts of the Pro design. Plan: strip the Pro hooks in our fork and add our own extension points. Don't use their Pro-facing names as a spec. |
| `tests/` for Pro editors (`converter/`, `mesh_editor/`, `rbf_editor/`, `raw_control_editor/`, `shape_key_editor/`, `test_body_rbf_editor.py`, …) | — | Public GPL tests that exercise the private Pro code. | **Q3:** I recommend we **delete them from our fork without reading them**, to keep the Pro work clean-room (they describe Pro behavior at implementation level). Tests for the free base are fine to keep. |
| `dna_io/` (importer, exporter, calibrator, misc) | 2.7k lines | DNA → Blender import and Blender → DNA export/calibration. **Imports `bpy` in 4 of 5 files.** | Conflicts with our CLAUDE.md rule "`dna_io` must not import `bpy`". Proposal: leave theirs as the Blender-side layer (renamed, e.g. `blender_io`) and add our own pure layer `dna_core` (the spike's `load` / `write` / compare code, testable with plain CPython 3.13 per FINDINGS). **Q4.** |
| `runtime/` | 1.8k lines | Native-runtime controller, driver "carriers", frame evaluation, undo/load handling. | Depends on `_riglogic_blender`. Replacement point for §4. |
| `utilities/sentry.py`, `constants.SENTRY_DSN` | — | Consent-based error/perf reporting to **Poly Hammer's own server** (`sentry.poly-hammer.com`); consent operator `metrics_collection_consent`. | Must not ship pointing at their server. Remove Sentry (or add our own DSN later). Drop the `network` permission if nothing else needs it. |
| `wheels/` | 7 wheels | `sentry_sdk` (pure Python) and `pyufbx` for cp311/cp313 × win/mac/linux. | Keep `pyufbx` (MIT, FBX I/O) for win_amd64 + macosx arm64 only. Drop the Linux ones and Sentry. Rebuild or verify pyufbx provenance later. |
| `constants.ToolInfo.NAME = "character_dna"`, manifest id/name/maintainer, docs URLs, "Get Pro" links | — | Poly Hammer branding and naming prefix. | Rename to our own prefix and branding (CLAUDE.md). This touches operator `bl_idname`s, so do it early, in one mechanical pass. **Q5:** the project name/prefix to use. |
| `tests/test_files/dna/{ada,default}/{head,body}.dna` (git-lfs) | about 117 MB | `ada`: MetaHuman Creator export **UE 5.6.0** (2025-06-26); `default`: export **UE 5.8.0** (2026-06-08). Only LFS pointers are present locally (git-lfs isn't installed). | These are the **UE 5.6–5.8 DCC exports step 7 needs.** Epic-generated data, so keep them out of our repo's history and treat them as local test inputs only. **Q6:** OK to `brew install git-lfs` and pull these 4 files (about 117 MB) for local testing? |
| CI | `.github/workflows/*.yaml` call reusable workflows in public `poly-hammer/poly-hammer-workflows`. Tests run with the **`bpy` PyPI module** (`uv pip install bpy==5.2.*`), not a Blender binary, on windows-latest / macos-latest. Release packaging uses AWS + their portal (secrets). | Reuse the idea (bpy-module tests on GH-hosted Windows/macOS). We can't reuse their secrets, private checkouts or release job. |

### 3.1 Name-collision strategy (recommendation)

Blender 5.1 `addon_utils._extensions_warnings_get` (read in source): the "Policy violation with top level module" message is a **UI warning, not a load failure**. It fires only for non-namespaced `sys.modules` entries whose `__file__` lies **inside an extension's own folder**.

| Option | Collision-safe | Blender warning | Fits fork | Notes |
|---|---|---|---|---|
| A. Their loader + binaries in `bindings/<os>/<arch>/py313/` (per-platform extension zip) | yes (bare names stripped) | no (`__file__` nulled) | **yes, zero loader changes** | Must change their `paths_exclude_pattern`, which currently excludes `bindings/windows|macos|linux`, and build per-platform zips (`blender --command extension build --split-platforms`). |
| B. Our spike's wheel (top-level `dna`/`riglogic` in shared `.local/site-packages`) | **no**: collides with any other extension that installs a `dna` or `riglogic` top-level module | no | needs loader changes | Proven working, but only safe if nobody else uses those names. |
| C. Wheel containing a private package plus their loader pointed at it | yes | no | small loader change | Only worth it if we later want Blender's wheel install/uninstall handling. |

**Recommend A.** It's what the forked code already does, it needs no new loader code, and the spike's `stage_bindings_macos.sh` output drops in unchanged at `bindings/macos/arm64/py313/`. VERIFY step: their arch detection uses `platform.processor()` (returns `arm` on Apple Silicon) → `arm64`. Confirm under Blender 5.1.

## 4. The missing native runtime: options (decided: option 1, Python evaluation)

Without `_riglogic_blender`, the forked addon imports, but real-time face/body evaluation is disabled. Options, cheapest first:
1. **Python evaluation path** (spec 01's performance ladder, rungs 1–2): drive `riglogic.RigLogic.calculate()` from a frame-change handler and push outputs with numpy + `foreach_set`. Spike numbers: `calculate()` about 0.13 ms and output copy about 0.1 ms per frame, so the cost will be dominated by writing about 840 bones plus shape keys in Blender. Needs measuring. Lowest risk; no new native code.
2. **Our own native module** built on OpenRigLogic (MIT) that provides the functions `runtime/engine.py` calls. The interface is visible in their GPL Python, so implementing it is interoperability work. **Never** extract, decompile or redistribute their binary. More work: a C++ build per platform.
3. Ask Poly Hammer whether `_riglogic_blender`'s source is available under GPL, or its license terms. Legally cleanest if they say yes; don't block on it.

Recommendation: 1 first, measure, then decide on 2. Either way, their binary is **not** redistributable by us (unknown license, no source).

## 5. Windows build plan (Windows x64, Blender 5.x / Python 3.13)

### 5.1 What changes vs. the macOS steps

| macOS step (spike) | Windows equivalent | Notes / VERIFY |
|---|---|---|
| Apple clang | **MSVC** (VS 2022 Build Tools, x64 Native Tools prompt, or `ilammy/msvc-dev-cmd` in CI) + CMake + Ninja | Confirmed: OpenRigLogic's own CI (`cmake-multi-platform.yml`) builds on `windows-latest` with MSVC `cl`, though without the Python wrapper. VERIFY the SWIG wrappers compile cleanly under MSVC. |
| SWIG 4.2.1 from pip | Same (`pip install swig==4.2.1`) | VERIFY a win_amd64 wheel exists for 4.2.1; fallback `choco install swig --version 4.2.1`. |
| Headers from uv CPython 3.13.9 (Blender ships only `pyconfig.h` on mac) | python.org / `actions/setup-python` **3.13.x x64**: `include/` + `libs/python313.lib` | Windows **must link** the import library `python313.lib` (no `-undefined dynamic_lookup`). `Python3::Module` also links `python313.lib` on Windows, so our patch still works. VERIFY Blender Windows ships `python313.dll` under that exact name (the Blender download server blocks scripted fetches, so check it in CI or by hand). Not free-threaded (no `t` suffix). |
| Patch `Python3::Python` → `Python3::Module` | Harmless on Windows; keep one patch for both OSes | — |
| **Type-table patch** (`SWIG_TYPE_TABLE` without dots/quotes) | **Same bug, same patch** | Platform-independent. |
| `.dylib` → rename to `.so` | UseSWIG emits `_py3dna13_2_9.pyd` / `_py3riglogic13_2_9.pyd` directly | VERIFY the `VERSION`/`SOVERSION` target properties don't alter the `.pyd` name on Windows (they only affect symlinks on Unix). |
| `install_name_tool` rewrite `@rpath` → `@loader_path` | **Nothing to rewrite.** `_py3riglogic*.pyd` imports `_py3dna13_2_9.pyd` **by file name** through its import library. It resolves because (a) `dna` is loaded first and Windows reuses an already-loaded module with the same base name, and (b) Python 3.8+ loads extensions with `LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR`, and their loader also calls `os.add_dll_directory`. | VERIFY with `dumpbin /dependents _py3riglogic13_2_9.pyd`: expect `_py3dna13_2_9.pyd`, `python313.dll`, `KERNEL32.dll`, and **VCRUNTIME140/MSVCP140** unless statically linked. |
| `codesign --force -s -` | Not required to load. Optional Authenticode signing later to reduce SmartScreen/AV warnings. | — |
| C++ runtime | Blender for Windows bundles the VC++ runtime DLLs next to `blender.exe` (VERIFY). Safer: build with **`-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded`** (static `/MT`) so the `.pyd`s don't depend on MSVCP140. OpenRigLogic's CMake doesn't set it itself (grep found nothing), so the CMake 3.15+ variable should apply. VERIFY. | Mixing `/MT` modules is fine here because no C++ objects cross between `.pyd`s except via SWIG pointers. VERIFY riglogic ↔ dna object passing still works (step 5 test). |
| Stage script `stage_bindings_macos.sh` | New `stage_bindings_windows.ps1`: copy `dna.py`, `riglogic.py`, the two `.pyd`s into `bindings/windows/x64/py313/`, run a `dumpbin` check | — |
| Wheel tag `macosx_11_0_arm64` | `win_amd64` → Blender platform `windows-x64` (only needed for option B/C) | — |
| `--python-exit-code 1` | Same | — |

### 5.2 How to test it: do you need a Windows machine?

- **Cross-compiling from this Mac:** possible in theory (clang-cl + `xwin` for the MSVC SDK), but fragile with SWIG/CPython import libraries and legally fiddly (redistributing the MSVC SDK). **Not recommended.**
- **GitHub Actions `windows-latest` (recommended):** hosted Windows x64 with MSVC preinstalled. One job can (1) build the bindings, (2) download a portable Blender 5.x Windows zip (~400 MB; could be cached), (3) run the Day-1 scripts headless (`blender.exe --background --factory-startup --python-exit-code 1 --python ...`), and (4) upload the staged folder as an artifact. That covers spike steps 1–5, 6 (install into a clean profile via `BLENDER_USER_RESOURCES`) and 8. A macOS arm64 job (`macos-latest` is Apple Silicon) can rebuild the mac bindings in the same workflow so both are reproducible. Free for a public repo; a private repo uses Actions minutes, and Windows minutes count double.
  - **Test DNAs in CI:** we can't commit Epic DNAs to a public repo. Use (a) a tiny DNA generated at test time with `dna.BinaryStreamWriter` (as in the issue repro) for build smoke tests, and (b) a **private** artifact or repo secret holding the real test DNA for the full round-trip/evaluation checks, or run those locally only. **Q8.**
- **Local alternative:** a Windows 11 VM on this Mac (Parallels/UTM) runs **Windows on ARM**, and x64 Blender/`.pyd`s would run under emulation. OK for smoke tests, not for performance numbers or driver/GPU-related GUI behavior.
- **What still needs a real Windows x64 PC (yours or a tester's):** one GUI pass (install the extension zip, import a DNA, scrub the face board, save and reload the file, undo) and a performance baseline. No build tools are needed on that PC if CI produces the zip.

### 5.3 Proposed order (all done 2026-09-21: Windows bindings in PR #2 (merged), macOS bindings + per-platform zips + clean-install test in https://github.com/highlighthousefc-ai/character-dna-addon/pull/3, CI green; see FINDINGS)
1. You create the fork (§2) and answer Q1–Q8.
2. Commit the patch plus stage scripts into the fork under a `bindings-build/` folder, with a README noting OpenRigLogic's MIT license.
3. Add a GH Actions workflow: build `macos-arm64` + `windows-x64` for py313 (and py311 if Q1 says 4.5 LTS), run the spike scripts headless in Blender, and upload per-platform `bindings/<os>/<arch>/<py>/` artifacts.
4. Drop the artifacts into the fork's `bindings/` layout (option A) and confirm the forked addon registers on both OSes (no feature changes).
5. Only then: rebrand/strip pass (Sentry, Pro hooks, Pro tests, `editors` submodule, Linux wheels), then §4 evaluation work.

## 6. Epic issues (item 1): filed 2026-09-21
- **Type table:** https://github.com/EpicGames/OpenRigLogic/issues/3 (from `docs/drafts/openriglogic-issue-type-table.md`, filed first).
- **`None` crash:** https://github.com/EpicGames/OpenRigLogic/issues/4 (from `docs/drafts/openriglogic-issue-none-crash.md`).
- Both filed verbatim from the approved drafts, with the Bug Report template, from the human's account in the browser pane.
- Neither is a security issue under their `SECURITY.md` (in-process Python calls with bad arguments; no untrusted-input path).

## 7. Strip pass (done 2026-09-21: https://github.com/highlighthousefc-ai/character-dna-addon/pull/1, CI green)

Runs on a branch in the fork, one commit per bullet, so each is easy to review or revert. No feature changes.
1. **`editors` submodule:** `git submodule deinit -f` (it was never initialised), `git rm src/addons/character_dna/editors`, delete `.gitmodules`. Never fetch it.
2. **Pro hooks:** remove the `editors` imports and `is_pro` / `editors_available` / `pro_features_visible` branches in `dna_io/calibrator.py`, `rig_instance.py`, `runtime/engine.py`, `typing.py`, `ui/addon_preferences.py`, `ui/callbacks.py`, `ui/view_3d.py`, `utilities/{material,misc,reference}.py`, keeping the free-path behavior. Also remove "Get Pro" / polyhammer.com portal links. Our own extension point for Pro gets designed later from the specs, not from these hook names.
3. **Pro-editor tests (Q3):** `git rm` the directories and files listed in §3 **by path only**, without opening them.
4. **Sentry:** delete `utilities/sentry.py` and `constants.SENTRY_DSN`, the consent operator in `operators.py`, the init in `__init__.py` / `utilities/__init__.py`, the `sentry_sdk` wheels and manifest entries, and the `sentry-sdk` dependency in `pyproject.toml` / `uv.lock`. Drop the manifest's `network` permission if nothing else uses it. Remove the README Sentry mention.
5. **Private bindings repo:** remove `character-dna-bindings` usage in `tests/conftest.py`, `scripts/profiling_utils/ci_benchmark.py` and `.github/workflows/re-use-benchmark.yaml`; point them at our own `bindings/<os>/<arch>/py313/` build output instead. `bindings.load_native_runtime()` stays but always reports "unavailable" until §4 option 1 replaces the controller.
6. **CI:** replace the workflows that call `poly-hammer/poly-hammer-workflows` (and the AWS/portal release job) with our own lint + test workflow (§5.3). Their reusable workflows are public, but pinning to `@main` of someone else's repo is a supply-chain risk.
7. **Platforms:** drop Linux and Intel wheels (`pyufbx` linux, any `macos-x64`), set manifest `platforms = ["windows-x64", "macos-arm64"]`, and fix `paths_exclude_pattern` so `bindings/<os>/` ships in the matching per-platform zip. Set `blender_version_min = "5.0.0"` (VERIFY the lowest 5.x we test).
8. **`dna_core` (Q4):** add `src/addons/character_dna/dna_core/` with `__init__.py` and module stubs (`reader.py`: load a DNA to a reader; `writer.py`: write/round-trip; `compare.py`: structural compare, from the spike's `inspect_and_roundtrip.py`), importing only `dna`/`riglogic`/numpy, plus a pytest that runs under plain CPython 3.13 with our staged bindings on `PYTHONPATH` and a guard test asserting `bpy` is never imported. Their `dna_io` stays as the Blender-side layer; renaming it to `blender_io` happens with the rebrand (Q5) to avoid churning imports twice.
9. Rebrand (Q5) is **not** part of this pass.

Check after the pass: `git grep -niE "sentry|character-dna-bindings|addon-editors|editors_available|is_pro"` returns nothing, and the addon registers headless in Blender 5.1 with our macOS bindings dropped in (`--python-exit-code 1`).

## Answers to the open questions (defaults, 2026-09-21)

Items marked **BUSINESS** are your call on product, legal or money grounds. I've put a technical default so work isn't blocked, but please confirm them.

- **Q3 Pro-editor tests: delete unread. Default: yes.** Technical and clean-room hygiene: they test code we don't have and can't run, and reading them would leak Pro implementation detail into our Pro work. Deleting by path is enough; the GPL doesn't require keeping them.
- **Q4 `dna_core`: yes, as §7 item 8.** Technical. It gives us a layer testable with plain CPython in CI (fast, no Blender download) and satisfies the CLAUDE.md rule without rewriting their importer.
- **Q5 name and prefix: BUSINESS.** It's product branding and a trademark question. Technical constraints only: don't use "MetaHuman", "Epic" or "Unreal" in the product name (Epic trademarks; nominative use like "for MetaHuman DNA" in a description is what upstream does), don't reuse "character_dna"/Poly Hammer names, and the prefix must be a short lowercase Python identifier (e.g. `xyz_`), used for the manifest id, `bl_idname`s and property groups. Until you choose, the fork keeps `character_dna` and the rename is one mechanical commit later.
- **Q6 test DNAs: done** (decided above). Storage is Q8.
- **Q7: decided** (Python evaluation).
- **Q8 public or private fork, and where CI test DNAs live.**
  - **Public vs. private: BUSINESS, default public.** GPL doesn't force you to publish before you distribute, so private is legal while developing. But GitHub doesn't let you make a fork of a public repo private; a private copy means "duplicate" (a new repo plus mirror push) and losing the fork link. Public Actions minutes are free; private minutes are billed, with Windows at 2x. Default: **public fork.**
  - **Test DNAs: partly BUSINESS/legal.** The 4 exports are Epic-generated MetaHuman data. Upstream already hosts them in its public GPL repo, and a GitHub fork inherits those LFS pointers, but that doesn't mean Epic licensed them for redistribution by us. The MetaHuman EULA governs, and upstream's choice isn't our permission. Technical default: **don't add any Epic DNA to our history**. Leave upstream's existing LFS files untouched for now (flag for removal if you decide so), CI build smoke tests use a DNA generated at test time, and full round-trip/evaluation tests run locally or from a private store (a private repo or artifact fetched with a token secret) once you've checked the EULA. VERIFY: whether LFS objects of upstream are fetchable from our fork without re-uploading (GitHub counts fork LFS against the root repo's network; to be tested after the fork exists).
- **Also BUSINESS (new):** §4 option 3, asking Poly Hammer about `_riglogic_blender`'s license. It's moot now that Q7 picked Python evaluation, so I won't pursue it.
