# 03: Shape Key Editor

**Depends on:** 01. Backup hooks (02) recommended.

## Purpose
Edit the blend shapes (shape keys) that the DNA drives, by sculpting directly on one active shape key while all others are locked.

## Key concept
A basic shape key (e.g. `jaw_open`) sits on a single raw control (`jawOpen`) plus its posed bones. **Corrective** shape keys (e.g. long names like `MCornerDepress_NSwrinkle_Jopen_R`) only appear when *other* raw controls or shape keys are also active (PSDs). So editing one key means first activating everything it depends on, so the user sculpts against the real evaluated face.

## Behavior

### Import Shape Keys
- After importing a MetaHuman, an explicit **Import Shape Keys** operator loads them from the DNA into the Blender scene.
- Option **Generate Neutral**: auto-generate neutral shapes on import for a clean slate.

### Shape key list
Filter and sort by: mesh (scope to a LOD0 mesh), name search, non-zero only, value sort, side (L/R/Center), **has deltas** (hide keys with no vertex offsets from the basis), and a **Freeze** toggle that locks list order/filtering so rows don't reshuffle while values are scrubbed.

### Editing with dependencies
1. User selects a channel and clicks **Edit**.
2. Compute the **dependency chain** backward from the selected key (which raw controls/keys must be active, at what values).
3. Activate the dependencies; show a **dependency list**. Dependencies are **locked** (read-only context); the edited key is **unlocked**.
4. Per-dependency visibility toggles let the user diff their sculpt against what's underneath.
5. User works in Sculpt or Edit mode with Mirror / Flip / Reset tools.
6. **Commit** writes the change into the DNA; **Revert** discards.

## Implementation notes
- The dependency graph comes from the DNA's PSD/corrective data (VERIFY how conditions and input weights are stored, and how the evaluated combination is computed).
- The stored delta for the edited key must account for what the dependencies already contribute. Decide and document whether Blender shape keys hold absolute positions or deltas, and convert carefully on commit. Verify by round-tripping an unedited key (must be a no-op).
- Use the edit-session pattern from 01.

## Acceptance criteria
- Editing and committing a *basic* key changes only that key's deltas in the DNA.
- Editing a *corrective* key shows the right dependency chain and, when evaluated with those controls active, the result matches the user's sculpt.
- Round-trip with no edits produces bit-identical (or tolerance-equal) deltas.
- Mirror/Flip work across sides using the mesh's symmetry.
- Revert leaves the DNA untouched.

## Likely building blocks (VERIFY)
- Epic's DNACalib exposes `SetBlendShapeTargetDeltasCommand` for writing per-target deltas (see `01-foundation.md`). DNACalib isn't updated for 5.6+ characters, so check whether the `dna` writer has a direct equivalent for your commit path.
- Lower LODs are separate meshes; decide whether committing LOD0 also needs `CalculateMeshLowerLODsCommand` (see `09`).
