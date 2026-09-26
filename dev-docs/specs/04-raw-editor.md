# 04: Raw Editor

**Depends on:** 01. Backup hooks (02) recommended. Solver is a separate spec (05).

## Purpose
Edit the **raw controls**, specifically *where* bones are posed when a raw control is set to 1, plus the neutral rest pose.

## Behavior

### Choosing a raw control
List every raw control, plus a top row **Rest Pose** (`default`) for editing the neutral shape. Filters: mesh (LOD0 mesh), name, non-zero only, value sort, side (L/R/Center), **Freeze** list order.
Note: some controls are correctives (e.g. `jawOpenExtreme` activates `jawOpen` too), so entering an edit should activate what it builds on.

### Edit session
User picks **Edit** on a control and works in one of two modes:
- **Target mesh mode** (LOD0 sculpt targets): Mirror, Flip, Reset to Neutral, Reset to DNA, Transfer shape from a selected mesh, and (rest pose only) Transfer to Head. A **Strength** slider blends the result of an operation.
- **Pose bone mode**: Mirror/Flip bones, Reset to Rest Pose, Reset to DNA, Mirror/Flip selection, and (rest pose only) **Snap Bones to Surface**.

Finish with **Commit** (write to DNA) or **Revert**. Options: mirror on commit; for rest-pose edits, update the mesh and auto-update LODs.

### Rest pose edits
Changing the neutral pose affects everything downstream (bind pose, other LODs, deltas). Document exactly what must be recomputed and test it.

## Implementation notes
- Distinguish absolute bone transforms from **deltas relative to neutral** in the DNA (VERIFY the representation and units; the solver spec assumes this).
- Reuse the edit-session pattern and the mirror utilities across editors (put symmetry/mirror maps in a shared module).
- Bone matching ("Match Bones to Mesh") is specified separately in `05-bone-matching-solver.md`; leave a clean hook for it.

## Acceptance criteria
- Committing a bone-pose edit changes only that control's joint deltas in the DNA; an unedited commit is a no-op.
- Mirror/Flip work on both meshes and bones.
- Rest-pose commit updates mesh and LODs consistently; the evaluated neutral face matches the edited pose.
- Revert leaves the DNA untouched.

## Likely building blocks (VERIFY)
- DNACalib has `SetNeutralJointTranslationsCommand`/`SetNeutralJointRotationsCommand`-style commands for the *neutral* (rest) pose. Per-raw-control joint deltas live in the DNA's joint group / behavior data; confirm in the DNA library's writer interface how to update them, since DNACalib may not have a dedicated command.
- Never remove or rename `neck_01`, `neck_02`, `FACIAL_C_FacialRoot`.
