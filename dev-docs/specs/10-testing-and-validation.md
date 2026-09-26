# 10: Testing and Validation

Build the harness **with** `01` and `09`, not at the end. This is what lets Claude Code work reliably despite not seeing the viewport.

## Test data
- Epic's MetaHuman DNA Calibration repo ships two demo DNA files, **Ada** and **Taro** (Epic's first presets), stored with Git LFS. They predate Unreal 5.6, so they cannot test 5.6 to 5.8 compatibility. **VERIFY** the license before committing copies; prefer referencing them or fetching in CI.
- A fresh **DCC Export** of a default MetaHuman from Unreal (5.6 to 5.8), head and body. The human supplies this; never commit it to a public repo without checking terms.
- Keep one *tiny* synthetic case where the expected output is known analytically (e.g. move one joint by a fixed offset, or scale a mesh by 1.1).

## Test layers
1. **Pure-Python unit tests** for `dna_io`: load/save round trip, field-level equality with tolerances, error handling for bad files.
2. **Headless Blender integration tests** (`blender --background --python` running pytest): import, evaluate, edit, commit, export, reload. This is how Poly Hammer tests their addon in CI.
3. **Numerical parity tests:** evaluate the same raw control values through standalone RigLogic and through the Blender scene; joint transforms and shape key values must match within tolerance.
4. **Round-trip tests:** unedited export equals input; a single known edit changes only the targeted data.
5. **Robustness tests:** undo/redo spam, save/reload, delete rig instance, open a session then close Blender, low-memory FBX import.
6. **Performance benchmarks:** frames per second scrubbing the face board for head only and head+body; record numbers in `docs/FINDINGS.md` and watch for regressions.
7. **Visual/Unreal parity (manual):** a checklist of ~10 reference expressions; the human compares Blender vs. Unreal screenshots. Have Claude Code generate the checklist and results table.

## CI
- Matrix over OS and the Blender versions you support.
- Build the native wheels in CI so the Day-1 packaging gate is checked on every change.
- Lint/type-check (ruff, pyright) and spell-check as Poly Hammer does, if you like.

## Rules for Claude Code
- Never say a feature works unless a test ran and passed. If a criterion can only be checked visually, say **"needs human verification"** and give the exact steps.
- When a test fails because of a wrong assumption about a library, record the correct behavior in `docs/FINDINGS.md`.
- Keep test data paths configurable through environment variables.

## Acceptance criteria
- One command runs unit and headless integration tests locally and in CI.
- Parity and round-trip tests exist for every feature that touches the DNA.
- The manual visual checklist exists and has been run at least once per release.
