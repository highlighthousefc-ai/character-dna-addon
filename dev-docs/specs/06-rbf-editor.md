# 06: RBF Editor (Body Correctives)

**Depends on:** 01 (body DNA support). Backup hooks (02) recommended.

## Purpose
Modify, add, and delete **corrective bone poses on the MetaHuman body**. Correctives interpolate using **Radial Basis Functions**: as a `driver` bone moves, the `driven` corrective bones blend into position through a falloff function.

## Concepts
- **Solver**: one RBF solver on the body. It also defines the joints in a joint group in the DNA.
- **Pose**: a `driven` corrective bone pose belonging to a solver. A solver can have as many or as few poses as needed to interpolate to every desired corrective position.
- **Kernel / function type**: Gaussian, Linear, etc. (VERIFY the full list the DNA/RigLogic supports).

## Behavior
- **Solvers list** and **Poses list** (poses for the active solver).
- **Edit** a solver to enter a session. While editing: **Add**, **Remove**, **Mirror** solvers (mirroring maps driving bones left to right).
- **Settings** while editing: choose the function type with a **live curve preview** of the falloff.
- User poses the driven bones for a pose, then clicks **Apply Pose Transform Edits** to associate the changes with that pose *before switching to another pose*. These edits stay ephemeral until committed.
- **Commit** writes into the body DNA; **Revert** discards.

## Implementation notes
- Read Epic's OpenRigLogic docs for the RBF solver model: solver parameters (radius, weight threshold, distance metric, normalization, etc. VERIFY), pose scale factors, and how outputs are applied. Make the editor round-trip these fields unchanged unless the user edits them.
- The live curve preview should evaluate the same kernel math the runtime uses. Verify against RigLogic output for a few sample inputs.
- Mirroring needs a reliable left/right bone-name map for the body skeleton (shared mirror utilities from 04 if possible).
- Use the edit-session pattern from 01, and make "Apply Pose Transform Edits" impossible to forget (warn on switch/commit if unapplied edits exist).

## Epic's RBF data API (names confirmed from OpenRigLogic's public headers; not yet exercised on real data)
Read: `getRBFSolverCount`, `getRBFSolverName`, `getRBFSolverType`, `getRBFSolverFunctionType` (the kernel), `getRBFSolverRadius`, `getRBFSolverAutomaticRadius`, `getRBFSolverDistanceMethod`, `getRBFSolverNormalizeMethod`, `getRBFSolverWeightThreshold`, `getRBFSolverTwistAxis`, `getRBFSolverRawControlValues`, `getRBFSolverPoseIndices`, `getRBFPoseName`, `getRBFPoseScale`, `getRBFPoseControlName`, `getRBFPoseOutputControlWeights`, `getRBFPoseJointOutputValues`, `getRBFPoseJointOutputIndices`.
Write: the matching `setRBFSolver*` / `setRBFPose*` calls, plus `setRBFSolverIndices`, `setRBFSolverPoseIndices`, `setRBFSolverRawControlIndices`, `setRBFPoseInputControlIndices`, `setRBFPoseOutputControlIndices`, `setLODRBFSolverMapping`, and the `clearRBF*` calls.
So the whole model (solvers, kernel, radius, poses, driven outputs) is readable and writable through the same `dna` module as the rest of the addon. The sample head DNA had 0 RBF solvers, so the **first task** is to load a real *body* DNA from the user's MetaHuman and dump every solver and pose to JSON, then round-trip it unchanged through the writer before building any UI.

## Acceptance criteria
- Round trip with no edits leaves solver/pose data unchanged.
- Adding a pose and committing changes the body's evaluated result near that pose and nowhere else (within falloff).
- Mirroring a solver produces the mirrored driver/driven mapping.
- Curve preview matches runtime evaluation for sampled inputs.
