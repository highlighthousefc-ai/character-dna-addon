# 01: Foundation: Libraries, DNA I/O, Rig Instance, Edit Sessions

Everything else depends on this. **Do the Day-1 spike first, and stop and report if it fails.**

## Verified facts to build on (see `00-overview.md`)
- Epic's **OpenRigLogic** (MIT) provides the DNA library and RigLogic, both C++ with Python bindings.
- Epic's **DNA Calibration** repo provides **DNACalib**: editing commands with a Python wrapper. **Caveat:** Epic's README says the repo has not been updated for characters made in Unreal 5.6 or later (it remains compatible with 5.5 and earlier). Use it as a reference for API shape and for old-format test DNAs like Ada and Taro, and do the real work through OpenRigLogic's `dna` module. Documented usage pattern:
  - Read: `FileStream(path, AccessMode_Read, OpenMode_Binary)` then `BinaryStreamReader(stream, DataLayer_All)`, `reader.read()`, then check `Status.isOk()` / `Status.get()`.
  - Write: `BinaryStreamWriter(stream)`, `writer.setFrom(reader)`, `writer.write()`, then check status.
  - Edit: wrap a reader in `DNACalibDNAReader`, run commands (e.g. `SetVertexPositionsCommand`, `SetBlendShapeTargetDeltasCommand`, `SetNeutralJointRotationsCommand`, `RenameJointCommand`, `RemoveJointCommand`, `ScaleCommand`, `SetLODsCommand`, `CalculateMeshLowerLODsCommand`), optionally batched in a `CommandSequence`.
  - Do not remove or rename the joints `neck_01`, `neck_02`, `FACIAL_C_FacialRoot` (they connect head to body).
- Exact function names above come from Epic's examples. **VERIFY** them against the current versions you build.
- The scripts in `spikes/` (written by another session; **not run by the author of this spec**) show the direct `dna`/`riglogic` API in use: `dna.FileStream`, `dna.BinaryStreamReader`, `reader.getCoordinateSystem()`, `riglogic.RigLogic(reader)`, `riglogic.RigInstance(rl)`, `ri.setRawControl(i, v)`, `rl.calculate(ri)`, `ri.getJointOutputs()` / `getBlendShapeOutputs()` / `getAnimatedMapOutputs()`, and on the write side `dna.BinaryStreamWriter.setFrom(reader)` followed by setters such as `setVertexPositions(mesh, [[x, y, z], ...])`. That suggests many edits can be written through the DNA writer directly, **without DNACalib**, so treat DNACalib as optional and check which route is more robust for 5.6 to 5.8 DNAs.

## Day-1 spike (gate: all must pass before anything else)

1. **Build/obtain bindings** (start from `BUILD-BINDINGS.md`, including its SWIG version and Python-matching pitfalls; it was written by another session and reports a Linux/Python 3.12 build) for the `dna` and RigLogic Python modules against **Blender's own Python** (check `sys.version` inside Blender; do this per OS and per Blender version you'll support). Note: Epic's DNACalib prebuilt binaries only cover Python 3.7/3.9, so expect to compile with CMake (`PYTHON3_EXACT_VERSION`-style settings; read the repo docs).
2. **Import them inside Blender** (`blender --background --python spike.py`), on the OS you develop on.
3. **Load a real `head.dna`**. Start with Epic's demo `Ada.dna` (from the DNA Calibration repo's `data/dna_files/`; it is UE 5.5-era or older, and needs `git-lfs` to download), then repeat with a current DCC Export. Print: joint count, mesh count per LOD, blend shape target count, raw control count.
4. **Round trip:** write it back unchanged, reload, and compare programmatically (counts, neutral joints, mesh vertices, blend shape deltas).
5. **Evaluate RigLogic:** set one raw control (e.g. jaw open) and read back joint and blend shape outputs.
6. **Bundle as an extension:** package the built libraries as per-platform **wheels** in a Blender extension (`blender_manifest.toml` with `wheels`/`platforms`; **VERIFY** the current manifest schema) and confirm they import after installing the extension on a clean Blender.
7. Test with DNAs from a **current** Unreal version (5.6 to 5.8) and note any DNACalib/DNA-version problems in `docs/FINDINGS.md`. The other session's spikes only touched a UE 5.5-era DNA, so this step is still open.
8. Re-run `spikes/spike_read_evaluate.py` and `spikes/spike_roundtrip_write.py` on your machine and record the timings (the read script prints ms/frame for `calculate()` and for copying outputs), which sets your evaluation-speed baseline.

If step 1 or 6 fails on your setup, report it before writing further code. It changes the plan (for example, forking the free addon and reusing its bundled build pipeline).

## Deliverables

### A. Architecture note (`ARCHITECTURE.md`, before feature code)
Cover: how a DNA loads and what data it exposes (meshes per LOD, joints, blend shapes, raw controls, PSDs, joint groups, RBF solvers on the body, wrinkle-map data); how RigLogic is invoked and its outputs applied to Blender bones, shape keys, and materials; how changes are written back; and the **fork vs. clean-room** decision from `00-overview.md`.

### B. `dna_io` module
A thin wrapper isolating Epic's libraries from the rest of the addon:
- `load(path) -> handle` / `write(handle, path)` with proper `Status` error handling
- Read/write: neutral joint transforms; per-raw-control joint deltas; blend shape deltas per mesh/LOD; RBF solver definitions and poses (body); mesh vertex positions
- Pure Python + Epic's libs; **no `bpy` imports**, so it can be tested outside Blender

### C. Rig instance and evaluation
- Data structure tying together: DNA file path(s), Blender armature/mesh objects, evaluation state, face board.
- **Evaluation performance ladder** (measure at each rung, stop when fast enough):
  1. Simple: on frame change / control change, call RigLogic from Python and apply outputs.
  2. Batch and cache: avoid per-element Python calls, use numpy/`foreach_set`, skip unchanged outputs.
  3. Native/driver-based evaluation (only if needed).
- Coordinate systems: DNAs may be saved in different up/handedness conventions (Epic's docs mention Y-up vs Z-up variants). Convert on read and write, and test both.
- Release DNA handles/memory when instances are removed.

### D. Edit-session pattern (shared by all editors)
1. **Enter**: snapshot current state, lock/hide what shouldn't change, activate dependencies.
2. **Edit**: user sculpts/poses; the session tracks a dirty flag.
3. **Commit**: fire *pre-commit* hook, write changes via `dna_io`, fire *post-commit* hook, refresh the scene.
4. **Revert**: restore the snapshot; nothing touches the DNA.
Expose pre/post-commit as an internal hook system so Backup Manager can subscribe without editors knowing.

### E. Safety
Keep session state outside Blender's undo stack. Guard against undo/redo, file save, file load, and rig-instance deletion while a session is open (cancel or close gracefully).

## Acceptance criteria
- Day-1 spike steps 1 to 8 pass and are documented in `docs/FINDINGS.md`.
- A MetaHuman imports with a working face board whose expressions visibly match Unreal for a few reference expressions.
- Round trip with no edits reproduces the DNA within tolerance.
- `dna_io` unit tests run without Blender.
- Scripted stress test of undo/redo, save/reload, and instance delete doesn't crash Blender.
