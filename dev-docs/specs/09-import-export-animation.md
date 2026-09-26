# 09: Import, Export, Animation and Baking (Free-Tier Parity)

**Depends on:** 01. Pro is "everything in Free plus the editors", so a from-scratch build needs these. If you fork the free base, use this file as a checklist of what to verify instead of rebuild.

## A. Import
- `File > Import > MetaHuman DNA (.dna)` and drag-and-drop into the viewport. Selecting a `head.dna` looks for a `body.dna` in the same folder and offers **Include Body**.
- When head and body are both imported, set up constraints so the head follows the body's bones.
- If a `Maps` folder sits beside the `.dna`, link matching textures automatically; report missing ones instead of failing silently.
- **Append/Link from another `.blend`:** list the MetaHumans available in the chosen file and append or link them. This depends on consistent collection naming per character. For Link, offer an **editable rig** option so the controls are native to the current scene while other data stays linked. The RigLogic connection must survive both.
- Mesh normals: support import/export of custom normals; keep custom split normals **off by default** (users report dark-lighting artifacts on some characters).
- Handle coordinate-system differences on read (see `01`).

## B. Face board
- A viewport control rig whose bones map to the DNA's GUI controls. Import only the bones that actually affect GUI controls.
- Panels for scan reference poses and PSD-corrective target expressions.
- Toggles on the rig instance to enable/disable each RigLogic output (bones, shape keys, wrinkle masks) for debugging.
- A **Force Evaluate** operator that resets and re-caches evaluation if it gets stuck.

## C. Animation import
- **Face:** import face board animation curves from MetaHuman Animator onto the face board. (Delivery is via FBX; **VERIFY** the exact format. Poly Hammer's tooling uses an FBX loader, so plan for a robust FBX reader and handle large-file memory errors.)
- **Body:** import body animation exported from MetaHuman Animator or retargeted animation onto the skeleton.
- Known quirk to test: some control curves may fail to import when animation is authored elsewhere (a reported `Ctrl_C_eye` case).

## D. Baking
- Bake the RigLogic result (face board plus RBF-driven data) into **native Blender data** (bone and shape key animation) so it can be simulated, rendered elsewhere, or exported.
- Handle actions that contain channels other than pose bone transforms without failing.

## E. Export (the key path back to Unreal and MetaHuman Creator)
- **Component:** Head or Body; the asset list updates to match.
- **Method:**
  - **Calibrate (recommended):** requires vertex indices and bone names to match the original DNA. Applies your mesh and bone changes to a copy of the DNA using DNACalib-style commands (e.g. set vertex positions, neutral joint transforms, blend shape deltas). **VERIFY** the mapping. DNACalib isn't updated for 5.6+ characters, so expect to implement these edits through the `dna` writer's setters.
  - **Overwrite (experimental):** for when vertex indices or bone names differ; only when calibration isn't possible.
- **Asset list:** meshes, armatures, images to export, each toggleable and renameable. Mesh names must follow the MetaHuman **LOD naming convention** so each mesh maps to its LOD.
- **Options:** *Run Validations* before writing; *Update LODs* recalibrates lower LODs from your LOD0 edits (a Pro feature in Poly Hammer's product; **VERIFY** whether Epic's `CalculateMeshLowerLODsCommand` does the job); *Align Head and Body* aligns overlapping head/body bones to avoid a seam.
- **Output:** one folder holding `head.dna`, `body.dna`, and a `Maps` subfolder (support `//` blend-relative paths).
- **Buttons:** *Only Component* (one DNA, no textures) and *MetaHuman Creator* (head and body DNA plus textures in a format Creator accepts; **VERIFY** what manifest/JSON Creator expects by inspecting a real DCC Export).
- **Round-trip test:** export from Blender, then import the result into MetaHuman Creator (Epic supports bringing modified resources back). This is the true end-to-end test.

## Acceptance criteria
- Import (head only, head+body, append, link) works and the face board evaluates.
- Face animation and body animation import and play correctly on a sample.
- Bake produces native animation matching the live RigLogic result within tolerance.
- Export via Calibrate with no edits round-trips a DNA identically; with a small vertex edit, only that change appears (compare by script).
- The exported set loads back into the addon *and* into MetaHuman Creator.
- Validation fails clearly on renamed bones, wrong LOD names, and changed vertex counts.
