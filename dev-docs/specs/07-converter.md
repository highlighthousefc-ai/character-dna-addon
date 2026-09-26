# 07: Converter (Fit MetaHuman DNA to Custom Meshes)

**Depends on:** 01, 04 (mesh transfer utilities), ideally 03/05. **Hardest feature; do last.**

## Purpose
Re-fit a **base MetaHuman DNA** onto the user's own head and body meshes and produce a **new `.dna`** calibrated to that geometry, comparable to the output of MetaHuman Creator's DCC export process.

## Inputs
| Field | Purpose |
|---|---|
| Base DNA | Source `.dna` to convert from |
| Name | Filename of the new DNA |
| Output | Folder to write to |
| Head | User's head mesh |
| Body | User's body mesh |

**Advanced:**
- **Extra meshes**: other base-DNA meshes (eyes, teeth, etc.) to fit; each with a **Wrap** or **Relative** fit method; optional maps folder used when fitting them.
- **Constrain Head to Body**: align overlapping head/body bones to avoid a seam.
- **Zero Shape Deltas**: reset shape key deltas during conversion.
- **Validate UVs** with a **tolerance**: check UV consistency before fitting.

## Core algorithm (UV-based auto-fit)
- The user's mesh must share the **base MetaHuman UV layout**: no overlapping or extra UV islands. Validate this and fail with a clear message.
- Use UV correspondence to map base-DNA vertices to positions on the user's surface, then **relocate the DNA's bones and shapes** to match (joint positions, neutral pose, blend shape deltas transformed into the new geometry).
- **LOD calibration:** derive lower LODs from the user's LOD0 automatically during conversion so all levels stay in sync. Epic's DNACalib includes a `CalculateMeshLowerLODsCommand` that looks like the intended tool (**VERIFY**, and note DNACalib isn't updated for 5.6+ characters, so you may have to implement lower-LOD calculation yourself); the same capability backs the *Update LODs* export option in `09-import-export-animation.md`, so build it once and share it.
- **Note:** propagating LOD0 edits to lower LODs is also an *export* option in the reference addon ("Update LODs", Pro). Build it once as a shared routine (see `01-foundation.md`, section E) and call it from both the exporter and the converter.
- Write the new head/body DNAs via `dna_io`.

## Related workflow (document, and ideally support)
**Mesh wrapping:** a way for users to produce a compatible mesh by wrapping the base MetaHuman topology onto their own sculpt so UVs are preserved. Provide at least documentation; a helper operator is a bonus.

## Implementation notes
- Start with the simplest path: head only, no extra meshes, LOD0 only. Then add body, LODs, extra meshes, head-to-body constraint.
- Decide how to transform shape deltas and joint orientations under the new geometry (local frames, not just positions). Test with a *deliberately small* deformation first (e.g. slight uniform scale), where the expected result is analytically known.
- Validate outputs by loading the new DNA back through the foundation's importer and evaluating several expressions for artifacts.

## Acceptance criteria
- Identity test: converting the base DNA onto its own unmodified meshes reproduces the base DNA within tolerance.
- Scaled/stretched-head test: joints and shapes scale plausibly; no exploded expressions on reference controls.
- Invalid-UV input is rejected with an actionable error.
- Output DNA imports back into the addon and evaluates in real time; LOD1+ are consistent with LOD0.
