"""Pure-Python RigLogic frame evaluator (numpy + Epic's OpenRigLogic bindings).

This module implements the evaluator API that ``runtime/engine.py``, ``runtime/frame.py`` and
``runtime/authoring.py`` call on the "native module" (``capabilities``, ``load_model``,
``create_session``, ``describe``, ``create_frame_plan``, ``evaluate_frame``, ``control_snapshot``,
``transform_into``), so the driver-based engine runs unchanged without a compiled runtime.

It must not import ``bpy`` or ``mathutils``: all maths is numpy, which keeps it testable with plain
CPython (``tests_core``). DNA files are read through ``dna_core``.

Conventions (verified in Blender 5.1):
- Matrix buffers filled with ``foreach_get`` are column-major 4x4 (16 floats per matrix).
- Blender's "XYZ" Euler rotation matrix is ``Rz @ Ry @ Rx``.
- RigLogic head joint outputs are 9 values per joint (translation cm, rotation degrees, scale),
  deltas from the neutral pose. Body joints (quaternion rotation) are 10 values:
  translation(3), quaternion x, y, z, w, scale(3).
"""

from __future__ import annotations

import math

from array import array
from dataclasses import dataclass, field
from typing import Any

import numpy as np


try:
    from ..dna_core import load as load_dna
    from ..dna_core._bindings import riglogic_module
except ImportError:  # imported as a top-level package outside Blender (tests)
    from dna_core import load as load_dna  # pyright: ignore[reportMissingImports]
    from dna_core._bindings import riglogic_module  # pyright: ignore[reportMissingImports]


API_VERSION = 1
SCALE_FACTOR = 100.0  # DNA centimetres -> Blender metres
PLAN_STRIDE = 27  # joint, flag, rest location(3), rest rotation(3), rest scale(3), rest-to-parent inverse(16)
HEAD_JOINT_STRIDE = 9
BODY_JOINT_STRIDE = 10
EPSILON = 1e-6
EYE_YAW_RANGE = math.radians(60.0)
EYE_PITCH_RANGE = math.radians(30.0)


def capabilities() -> dict[str, Any]:
    return {"api_version": API_VERSION, "private_blender_api": False, "implementation": "python"}


# --------------------------------------------------------------------------------------------
# Models and sessions
# --------------------------------------------------------------------------------------------
@dataclass
class Model:
    path: str
    body: bool
    reader: Any
    rig_logic: Any
    info: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    model: Model
    instance: Any


def _configuration(riglogic: Any, body: bool) -> Any:
    """Same RigLogic configuration as ``RigInstance.head_initialize`` / ``body_initialize``."""
    config = riglogic.Configuration()
    if body:
        config.calculationType = riglogic.CalculationType_AnyVector
        config.loadJoints = True
        config.loadBlendShapes = True
        config.loadAnimatedMaps = True
        config.loadMachineLearnedBehavior = True
        config.loadRBFBehavior = True
        config.loadTwistSwingBehavior = True
        config.translationType = riglogic.TranslationType_Vector
        config.rotationType = riglogic.RotationType_Quaternions
        config.scaleType = riglogic.ScaleType_Vector
    return config


def load_model(path: str, body: bool, _load_all: bool = True) -> Model:
    """Read a DNA file and build a RigLogic model for it."""
    riglogic = riglogic_module()
    reader = load_dna(path)
    rig_logic = riglogic.RigLogic(reader, _configuration(riglogic, body), None)
    model = Model(path=path, body=body, reader=reader, rig_logic=rig_logic)
    probe = riglogic.RigInstance(rigLogic=rig_logic, memRes=None)
    probe.setLOD(0)
    model.info = {
        "lod_count": int(rig_logic.getLODCount()),
        "output_counts": [
            len(probe.getJointOutputs()),
            len(probe.getBlendShapeOutputs()),
            len(probe.getAnimatedMapOutputs()),
        ],
        "raw_control_count": int(reader.getRawControlCount()),
        "gui_control_count": int(reader.getGUIControlCount()),
    }
    return model


def create_session(model: Model) -> Session:
    riglogic = riglogic_module()
    return Session(model=model, instance=riglogic.RigInstance(rigLogic=model.rig_logic, memRes=None))


def describe(session: Session) -> dict[str, Any]:
    return dict(session.model.info)


def control_snapshot(session: Session) -> dict[str, array]:
    """Current raw and GUI control values of a session (after its last evaluation)."""
    instance = session.instance
    info = session.model.info
    return {
        "raw": array("f", (instance.getRawControl(index) for index in range(info["raw_control_count"]))),
        "gui": array("f", (instance.getGUIControl(index) for index in range(info["gui_control_count"]))),
    }


# --------------------------------------------------------------------------------------------
# Rotation helpers (Blender conventions)
# --------------------------------------------------------------------------------------------
def euler_xyz_to_matrix(euler: np.ndarray) -> np.ndarray:
    """(n, 3) radians -> (n, 3, 3) rotation matrices, R = Rz @ Ry @ Rx."""
    x, y, z = euler[:, 0], euler[:, 1], euler[:, 2]
    cx, sx, cy, sy, cz, sz = np.cos(x), np.sin(x), np.cos(y), np.sin(y), np.cos(z), np.sin(z)
    matrix = np.empty((len(euler), 3, 3))
    matrix[:, 0, 0] = cy * cz
    matrix[:, 0, 1] = sx * sy * cz - cx * sz
    matrix[:, 0, 2] = cx * sy * cz + sx * sz
    matrix[:, 1, 0] = cy * sz
    matrix[:, 1, 1] = sx * sy * sz + cx * cz
    matrix[:, 1, 2] = cx * sy * sz - sx * cz
    matrix[:, 2, 0] = -sy
    matrix[:, 2, 1] = sx * cy
    matrix[:, 2, 2] = cx * cy
    return matrix


def matrix_to_euler_xyz(matrix: np.ndarray) -> np.ndarray:
    """(n, 3, 3) orthonormal -> (n, 3) XYZ Euler; picks Blender's smaller-magnitude solution."""
    cy = np.hypot(matrix[:, 0, 0], matrix[:, 1, 0])
    regular = cy > 16 * np.finfo(np.float32).eps
    first = np.stack(
        [
            np.arctan2(matrix[:, 2, 1], matrix[:, 2, 2]),
            np.arctan2(-matrix[:, 2, 0], cy),
            np.arctan2(matrix[:, 1, 0], matrix[:, 0, 0]),
        ],
        axis=1,
    )
    second = np.stack(
        [
            np.arctan2(-matrix[:, 2, 1], -matrix[:, 2, 2]),
            np.arctan2(-matrix[:, 2, 0], -cy),
            np.arctan2(-matrix[:, 1, 0], -matrix[:, 0, 0]),
        ],
        axis=1,
    )
    degenerate = np.stack(
        [np.arctan2(-matrix[:, 1, 2], matrix[:, 1, 1]), np.arctan2(-matrix[:, 2, 0], cy), np.zeros(len(matrix))],
        axis=1,
    )
    use_second = np.abs(first).sum(axis=1) > np.abs(second).sum(axis=1)
    result = np.where(use_second[:, None], second, first)
    return np.where(regular[:, None], result, degenerate)


def quaternion_to_matrix(quaternion: np.ndarray) -> np.ndarray:
    """(n, 4) w, x, y, z -> (n, 3, 3)."""
    q = quaternion / np.linalg.norm(quaternion, axis=1, keepdims=True)
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    matrix = np.empty((len(q), 3, 3))
    matrix[:, 0, 0] = 1 - 2 * (y * y + z * z)
    matrix[:, 0, 1] = 2 * (x * y - w * z)
    matrix[:, 0, 2] = 2 * (x * z + w * y)
    matrix[:, 1, 0] = 2 * (x * y + w * z)
    matrix[:, 1, 1] = 1 - 2 * (x * x + z * z)
    matrix[:, 1, 2] = 2 * (y * z - w * x)
    matrix[:, 2, 0] = 2 * (x * z - w * y)
    matrix[:, 2, 1] = 2 * (y * z + w * x)
    matrix[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return matrix


def matrix_to_quaternion(matrix: np.ndarray) -> np.ndarray:
    """(3, 3) orthonormal -> (4,) w, x, y, z with w >= 0."""
    m = matrix
    trace = m[0, 0] + m[1, 1] + m[2, 2]
    if trace > 0:
        s = math.sqrt(trace + 1.0) * 2
        q = np.array([0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s])
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = np.array([(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s])
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = np.array([(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s])
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = np.array([(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s])
    q /= np.linalg.norm(q)
    return -q if q[0] < 0 else q


def quaternion_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product of (n, 4) w, x, y, z quaternions."""
    aw, ax, ay, az = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    bw, bx, by, bz = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    return np.stack(
        [
            aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
        ],
        axis=1,
    )


def euler_xyz_to_quaternion(euler: np.ndarray) -> np.ndarray:
    hx, hy, hz = euler[:, 0] / 2, euler[:, 1] / 2, euler[:, 2] / 2
    cx, sx, cy, sy, cz, sz = np.cos(hx), np.sin(hx), np.cos(hy), np.sin(hy), np.cos(hz), np.sin(hz)
    return np.stack(
        [
            cx * cy * cz + sx * sy * sz,
            sx * cy * cz - cx * sy * sz,
            cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz,
        ],
        axis=1,
    )


def _column_major(values: Any, count: int) -> np.ndarray:
    """``foreach_get`` matrix buffer -> (count, 4, 4) row-major numpy matrices."""
    return np.asarray(values, dtype=np.float64)[: count * 16].reshape(count, 4, 4).transpose(0, 2, 1)


# --------------------------------------------------------------------------------------------
# Joint outputs -> Blender pose-bone channels
# --------------------------------------------------------------------------------------------
def transform_into(plan: Any, joint_outputs: Any, out: Any, body: bool) -> None:
    """Convert RigLogic joint outputs to pose-bone location / XYZ Euler / scale per plan slot.

    Matches the pre-native Python path: the rest pose plus the delta gives the bone's
    parent-relative transform, and ``rest_to_parent_inverse @ LocRotScale`` is the pose basis.
    For head bones that have children the Euler rotation is the raw delta (as before).
    """
    items = np.asarray(plan, dtype=np.float64).reshape(-1, PLAN_STRIDE)
    count = len(items)
    result = np.frombuffer(out, dtype=np.float64)
    if count == 0:
        return
    joints = items[:, 0].astype(np.int64)
    has_children = items[:, 1] > 0.5
    rest_location, rest_rotation, rest_scale = items[:, 2:5], items[:, 5:8], items[:, 8:11]
    inverse = items[:, 11:27].reshape(count, 4, 4)
    outputs = np.asarray(joint_outputs, dtype=np.float64)
    stride = BODY_JOINT_STRIDE if body else HEAD_JOINT_STRIDE
    deltas = outputs.reshape(-1, stride)[joints]

    location = rest_location + deltas[:, 0:3] / SCALE_FACTOR
    if body:
        delta_quaternion = np.stack([deltas[:, 6], deltas[:, 3], deltas[:, 4], deltas[:, 5]], axis=1)
        rotation = quaternion_to_matrix(quaternion_multiply(euler_xyz_to_quaternion(rest_rotation), delta_quaternion))
        scale = rest_scale + deltas[:, 7:10]
        rotation_delta = None
    else:
        rotation_delta = np.radians(deltas[:, 3:6])
        rotation = euler_xyz_to_matrix(rest_rotation + rotation_delta)
        scale = rest_scale + deltas[:, 6:9]

    local = np.zeros((count, 4, 4))
    local[:, :3, :3] = rotation * scale[:, None, :]
    local[:, :3, 3] = location
    local[:, 3, 3] = 1.0
    basis = inverse @ local

    basis_scale = np.linalg.norm(basis[:, :3, :3], axis=1)
    safe_scale = np.where(basis_scale > EPSILON, basis_scale, 1.0)
    euler = matrix_to_euler_xyz(basis[:, :3, :3] / safe_scale[:, None, :])
    if rotation_delta is not None:
        euler = np.where(has_children[:, None], rotation_delta, euler)

    channels = np.concatenate([basis[:, :3, 3], euler, basis_scale], axis=1)
    result[: count * 9] = channels.reshape(-1)


# --------------------------------------------------------------------------------------------
# Frame plans and evaluation
# --------------------------------------------------------------------------------------------
@dataclass
class FramePlan:
    plan: np.ndarray
    rest: np.ndarray
    parents: np.ndarray
    gui: np.ndarray
    raw: np.ndarray
    chain: np.ndarray
    eyes: np.ndarray
    face_count: int
    body: bool
    raw_bones: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))


def create_frame_plan(
    _session: Session,
    plan: Any,
    rest: Any,
    parents: Any,
    gui: Any,
    raw: Any,
    chain: Any,
    eyes: Any,
    face_count: int,
    body: bool,
) -> FramePlan:
    parent_indices = np.asarray(parents, dtype=np.int64)
    raw_entries = np.asarray(raw, dtype=np.int64).reshape(-1, 3)
    return FramePlan(
        plan=np.asarray(plan, dtype=np.float64),
        rest=_column_major(rest, len(parent_indices)),
        parents=parent_indices,
        gui=np.asarray(gui, dtype=np.int64).reshape(-1, 4),
        raw=raw_entries,
        chain=np.asarray(chain, dtype=np.int64).reshape(-1, 4),
        eyes=np.asarray(eyes, dtype=np.int64).reshape(-1, 4),
        face_count=int(face_count),
        body=bool(body),
        raw_bones=np.unique(raw_entries[:, 1]) if len(raw_entries) else np.zeros(0, dtype=np.int64),
    )


def _local_quaternions(frame_plan: FramePlan, poses: np.ndarray) -> dict[int, np.ndarray]:
    """Parent-relative rotation of each raw-input bone, like ``get_pose_bone_local_quaternion``."""
    quaternions = {}
    rest = frame_plan.rest
    for bone in frame_plan.raw_bones:
        parent = frame_plan.parents[bone]
        if parent >= 0:
            basis = np.linalg.inv(rest[bone]) @ rest[parent] @ np.linalg.inv(poses[parent]) @ poses[bone]
        else:
            basis = np.linalg.inv(rest[bone]) @ poses[bone]
        rotation = basis[:3, :3] / np.linalg.norm(basis[:3, :3], axis=0)
        quaternions[int(bone)] = matrix_to_quaternion(rotation)
    return quaternions


def _eye_aim_controls(frame_plan: FramePlan, poses: np.ndarray, spatial: np.ndarray) -> dict[int, float]:
    """GUI eye control values that make each eye look at its aim target (pre-native maths)."""
    values: dict[int, float] = {}
    rig_world = spatial[0:16].reshape(4, 4).T
    face_world = spatial[16:32].reshape(4, 4).T
    for node, target_index, control_x, control_y in frame_plan.eyes:
        eye = int(frame_plan.chain[node][0])
        parent = frame_plan.parents[eye]
        if parent >= 0:
            relative = np.linalg.inv(frame_plan.rest[parent]) @ frame_plan.rest[eye]
            reference = rig_world @ poses[parent] @ relative
        else:
            reference = rig_world @ frame_plan.rest[eye]
        eye_position = (rig_world @ poses[eye][:, 3])[:3]
        target = np.append(spatial[32 + target_index * 3 : 35 + target_index * 3], 1.0)
        direction = (face_world @ target)[:3] - eye_position
        length = np.linalg.norm(direction)
        if length < EPSILON:
            continue
        local = np.linalg.inv(reference[:3, :3]) @ (direction / length)
        local /= np.linalg.norm(local)
        horizontal = math.hypot(local[0], local[2])
        yaw = math.asin(max(-1.0, min(1.0, local[0] / horizontal))) if horizontal > EPSILON else 0.0
        pitch = math.atan2(local[1], horizontal)
        if control_x >= 0:
            values[int(control_x)] = max(-1.0, min(1.0, yaw / EYE_YAW_RANGE))
        if control_y >= 0:
            values[int(control_y)] = max(-1.0, min(1.0, pitch / EYE_PITCH_RANGE))
    return values


def evaluate_frame(
    session: Session,
    frame_plan: FramePlan,
    poses: Any,
    _bases: Any,
    face: Any,
    spatial: Any,
    sdk: Any,
    local: Any,
    lod: int,
    evaluate_rbfs: bool,
    eye_aim: bool,
) -> None:
    """Read controls from captured RNA buffers, run RigLogic, write SDK outputs and bone channels."""
    instance = session.instance
    rig_logic = session.model.rig_logic
    bone_count = len(frame_plan.parents)
    pose_matrices = _column_major(poses, bone_count)
    spatial_values = np.asarray(spatial, dtype=np.float64)
    instance.setLOD(int(lod))

    if not frame_plan.body and len(frame_plan.gui):
        face_locations = np.asarray(face, dtype=np.float64).reshape(-1, 3)
        aim = _eye_aim_controls(frame_plan, pose_matrices, spatial_values) if eye_aim else {}
        for gui_index, face_bone, axis, center in frame_plan.gui:
            if face_bone < 0:
                continue
            value = face_locations[face_bone, axis]
            aimed = aim.get(int(gui_index))
            if aimed is not None:
                if abs(aimed) > EPSILON:
                    value = aimed
            elif center >= 0 and abs(face_locations[center, axis]) > EPSILON:
                value = face_locations[center, axis]
            instance.setGUIControl(int(gui_index), float(value))
        rig_logic.mapGUIToRawControls(instance)

    if len(frame_plan.raw):
        quaternions = _local_quaternions(frame_plan, pose_matrices) if evaluate_rbfs else {}
        for raw_index, bone, component in frame_plan.raw:
            quaternion = quaternions.get(int(bone))
            if quaternion is not None:
                value = quaternion[component]
            else:
                value = 1.0 if component == 0 else 0.0  # identity rotation when RBFs are off
            instance.setRawControl(int(raw_index), float(value))

    rig_logic.calculate(instance)

    joints = np.fromiter(instance.getJointOutputs(), dtype=np.float64)
    shapes = np.fromiter(instance.getBlendShapeOutputs(), dtype=np.float64)
    maps = np.fromiter(instance.getAnimatedMapOutputs(), dtype=np.float64)
    joint_count, shape_count, _map_count = session.model.info["output_counts"]
    target = np.frombuffer(sdk, dtype=np.float64)
    target[:] = 0.0
    target[: len(joints)] = joints
    target[joint_count : joint_count + len(shapes)] = shapes
    target[joint_count + shape_count : joint_count + shape_count + len(maps)] = maps

    full_joints = target[:joint_count]
    transform_into(frame_plan.plan, full_joints, local, frame_plan.body)
