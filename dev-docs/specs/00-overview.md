# MetaHuman DNA Blender Addon: Planned Features

**Audience:** Claude Code (and the human driving it).
**Goal:** Build a Blender addon that imports MetaHuman `.dna` files, evaluates the face/body rig in real time, lets the user edit the DNA, and writes it back for Unreal Engine / MetaHuman Creator. The planned editors (specs `02` to `07`) cover backups, shape keys, raw controls, bone matching, RBF poses and mesh conversion.

These specs are written from public sources: Epic's documentation and repositories, public documentation of existing MetaHuman tools, and public GitHub activity. Anything marked **VERIFY** is an assumption to confirm against real data or docs before relying on it. Put what you learn in `dev-docs/FINDINGS.md` so later sessions don't rediscover it.

## Decision 0: fork the free addon, or build clean-room? (Human decides before coding)

| | Fork Poly Hammer's free base | Clean-room from Epic's libraries |
|---|---|---|
| Speed | Months faster: import, face board, evaluation, animation, export already exist | You rebuild all of it (see `01` and `09`) |
| License | The base is **GPL v3**. Anything derived from it must be distributed under GPL v3 with source. GPL doesn't forbid selling, but recipients get the same rights, so it can't be closed-source | Your choice, provided you comply with the MIT terms of Epic's libraries |
| Risk | You inherit their architecture and bugs; only the published GPL code is available to build on | More work, more bugs, but you own the design |
| Editors (`02` to `07`) | Written from scratch either way, from the behavior these specs describe | Same |

The human should decide this first, and if unsure, get legal advice: nobody here is a lawyer. **Recommendation:** if you're comfortable with GPL v3, fork the free base and spend your effort on the editors. If you want a closed-source or differently licensed product, go clean-room and follow `01` and `09` closely.

## Ground rules (read first)

1. **Clean-room for the editors.** Implement from the behavior described in these specs. Do not copy, decompile, or reverse-engineer any closed-source code, and do not circumvent any licensing. Use your own operator, panel, and preference names and your own branding.
2. **Check licenses before reusing anything:** the free base addon (GPL v3), Epic's OpenRigLogic (MIT), and the MetaHuman DNA Calibration repo (**VERIFY** its license before bundling).
3. **Check Epic's MetaHuman terms** before distributing anything, especially DNA/demo data. Don't commit Epic assets or a user's MetaHuman data to a public repo without checking.
4. **Never assume an API.** Write small probe scripts that call the real library and record results in `dev-docs/FINDINGS.md`.

## Verified facts about the foundations (from public sources)

- **OpenRigLogic** (github.com/EpicGames/OpenRigLogic, MIT): contains the **DNA library** (read/write DNA) and **RigLogic** (real-time rig evaluation). Both are native C++ with **Python bindings**, built with CMake (flags exist for AVX, half-float storage, and language bindings).
- **MetaHuman-DNA-Calibration** (github.com/EpicGames/MetaHuman-DNA-Calibration): the DNA library plus **DNACalib**, a set of editing commands with a Python wrapper. Its README says prebuilt Python wrappers cover only **Python 3.7 and 3.9 on 64-bit Windows and Linux**; any other Python needs a recompile. **Epic's README states this repo has not been updated for characters made in Unreal 5.6 or later.** It stays compatible with 5.5 and earlier, and Epic points 5.6+ users to its MetaHuman for Maya plugin. Treat DNACalib as legacy: use it for API shape and for old test DNAs (Epic's demo characters **Ada** and **Taro**), but do real work on 5.6 to 5.8 DNAs through OpenRigLogic's `dna` module (reader/writer with setters) and expect to reimplement calibration-style operations yourself.
- **Bindings have been built once already (unverified by the author of this overview).** Files that appeared in this folder from another session, `BUILD-BINDINGS.md` and `spikes/`, describe building OpenRigLogic's `dna` and `riglogic` Python modules and running read/evaluate/round-trip spikes. They report success on **Python 3.12 / Linux x86_64, OpenRigLogic 13.2.9, with a UE 5.5-era head DNA**. That is *not* Blender's Python, not Windows/macOS, and not a 5.6 to 5.8 DNA, so the Day-1 gate in `01` still applies. Re-run the spikes yourself before trusting them.
- **Poly Hammer's free addon** supports DNAs from Unreal 5.6 to 5.8, Blender 4.5 and later, and bundles Epic's libraries.
- **Poly Hammer's own performance history** is a useful roadmap: they shipped Python-side evaluation first, optimized it, then re-designed it around a native C++ rig instance for a ~3.7x speedup.

## Top risks, in the order they'll bite

1. **Native library packaging.** You must build the Python bindings against *Blender's* Python (per OS, per Blender version) and ship them as wheels in the extension. If this doesn't work, nothing else does, so it is the first gate (see `01`, Day-1 spike).
2. **DNA version drift.** Epic says DNACalib hasn't been updated for UE 5.6+ characters, and the demo DNAs (Ada, Taro) predate that. Test on a fresh 5.6 to 5.8 export and prefer OpenRigLogic's `dna` module.
3. **Real-time evaluation speed and stability** in Blender (depsgraph, drivers, undo, render).
4. **Blender extension packaging.** Blender's extension validator forbids top-level modules, but the SWIG wrappers import each other by bare name (`dna`, `riglogic`). `BUILD-BINDINGS.md` says Poly Hammer's free addon works around this with a custom isolated module loader (**VERIFY**), so budget time for an equivalent.
5. **The Converter** (`07`) is genuinely hard research-grade work.
6. **You are the tester.** Claude Code cannot see the Blender viewport.

## Files and build order

| Order | File | Difficulty |
|---|---|---|
| 0 | `CLAUDE.md`: copy to your repo root. Also see `BUILD-BINDINGS.md` and `spikes/` (from another session; re-verify) | n/a |
| 1 | `01-foundation.md`: Day-1 spike, DNA I/O, rig instance, edit-session pattern | required first |
| 2 | `09-import-export-animation.md`: free-tier parity (import, export, animation, bake). Skip parts you get from a fork | required for a usable addon |
| 3 | `10-testing-and-validation.md`: build the test harness alongside 01 and 09, not after | required |
| 4 | `02-backup-manager.md` | easy |
| 5 | `03-shape-key-editor.md` | medium |
| 6 | `04-raw-editor.md` | medium-hard |
| 7 | `05-bone-matching-solver.md` | hard (separate subsystem) |
| 8 | `06-rbf-editor.md` | medium-hard |
| 9 | `07-converter.md` | hardest |
| 10 | `08-character-assembly.md`: materials, hair, lighting, physics (optional, low-confidence spec) | medium, unclear |

## Terminology

- **DNA**: proprietary 3Lateral file describing a character's full rig and geometry.
- **RigLogic**: evaluator with one input driving three outputs. Input: face-board GUI controls ("raw controls"/expressions). Outputs: bone (joint) transforms, shape key (blend shape) values, wrinkle map masks.
- **PSD / corrective**: shapes or poses that activate only when combinations of other controls are active.
- **LOD0..n**: levels of detail. Edits happen on LOD0 and propagate to the others.
- **Rig Instance**: one imported character in the Blender scene.

## Working agreement for each spec

1. Read the spec and the relevant library code, then **write a short plan and list your VERIFY items** before coding.
2. Implement in small, testable steps. Prefer headless tests (`blender --background --python ...`) for anything that doesn't need the GUI.
3. Ask the human to run GUI checks in Blender and paste back console output/tracebacks.
4. Treat **undo/redo and file save/load** as first-class risks. A related Poly Hammer addon has user-reported Ctrl+Z crashes.
5. Each spec ends with **Acceptance criteria**. Don't call a feature done until those pass, and say plainly which criteria you could not verify yourself.
