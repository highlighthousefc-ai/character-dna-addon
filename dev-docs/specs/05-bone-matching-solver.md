# 05: Bone Matching Solver

**Depends on:** 04 (hook point in the Raw Editor).

## Purpose
Given a sculpted target mesh, automatically solve the bone transforms that reproduce it, so the user doesn't have to pose bones by hand ("Match Bones to Mesh").

## Problem statement
For the active raw control, find joint transforms (translation, rotation; scale only if the DNA uses it. VERIFY) such that the skinned mesh best matches the target vertices. Skinning uses the mesh's existing bone weights.

Formulate as an optimization:
- Differentiable skinning forward pass: transforms, weights, rest vertices -> posed vertices.
- **Robust loss** (Huber, with configurable delta in cm) between posed and target vertices.
- **Regularization** on rotation and translation to keep the solve stable.
- Optimizer with **learning rate**, **iterations**, and **convergence tolerance** for early stopping.
- **Warm weighting** with a threshold (VERIFY intent; likely down/up-weighting vertices or bones by influence).
- Option **Reset Pose**: start from the DNA pose, or from the current Blender pose bones.

## Architecture
- Runs in a **separate Python subprocess** with its own virtual environment, so PyTorch never loads into Blender's Python.
- Inter-process format: write inputs (rest vertices, target vertices, weights, joint hierarchy, initial pose, hyperparameters) to `.npz`/JSON, run the solver, read back transforms. Report progress so the UI can show a progress bar and support cancel.
- Hardware selection: `CPU`, `CUDA`, `MPS` (Apple), or `AUTO`, which picks the best available.
- **One-time environment install** operator (downloads PyTorch for the chosen hardware). Preference for where venvs live (they can be several GB).
- Solver settings popover in the UI exposing: iterations, learning rate, rotation reg, translation reg, warm-weight threshold, Huber delta, convergence tolerance.

## Guidance for tuning (put in the UI tooltip/docs)
Start with defaults. If the fit undershoots, raise iterations or learning rate. If it becomes unstable or spiky, raise regularization.

## Acceptance criteria
- On a synthetic test (pose bones by a known transform, generate the target mesh from it), the solver recovers transforms within a small tolerance.
- Works on CPU with no GPU; uses CUDA/MPS when available and selected.
- Blender stays responsive during a solve; cancel works; failure surfaces a clear error, not a hang.
- Environment install is idempotent and can be re-run safely.
