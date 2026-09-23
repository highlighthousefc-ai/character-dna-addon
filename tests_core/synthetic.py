"""Tiny synthetic DNA files for tests, so CI never needs Epic-owned DNA data.

Only uses the ``dna`` module passed in, so it works with bare bindings on ``sys.path`` and with
the addon's isolated copy inside Blender.
"""

from pathlib import Path
from types import ModuleType


JAW_OPEN_CONTROL = "CTRL_expressions.jawOpen"
# Face-board GUI control (bone ``CTRL_C_jaw``, Y translation), mapped 1:1 onto ``jawOpen``.
JAW_GUI_CONTROL = "CTRL_C_jaw.ty"
JAW_GUI_BONE = "CTRL_C_jaw"
JAW_JOINT = "FACIAL_C_Jaw"
JAW_OPEN_DEGREES = 25.0
# RigLogic joint outputs are 9 values per joint: translation xyz, rotation xyz, scale xyz.
JOINT_ATTRIBUTE_COUNT = 9
ROTATION_X = 3


def write_jaw_rig(dna: ModuleType, path: Path, *, gui_control: bool = False) -> Path:
    """Write a two-joint rig where ``jawOpen`` = 1 rotates the jaw joint by 25 degrees about X.

    With ``gui_control`` the rig also gets the face-board GUI control ``CTRL_C_jaw.ty``, mapped
    1:1 onto ``jawOpen`` over [0, 1], so tests can drive it the way the face board does.
    """
    stream = dna.FileStream(str(path), dna.FileStream.AccessMode_Write, dna.FileStream.OpenMode_Binary)
    writer = dna.BinaryStreamWriter(stream)
    writer.setName("synthetic_jaw")
    writer.setMetaData("source", "tests_core")
    writer.setLODCount(1)
    writer.setDBMaxLOD(0)

    writer.setJointName(0, "root")
    writer.setJointName(1, JAW_JOINT)
    writer.setJointHierarchy([0, 0])
    writer.setJointIndices(0, [0, 1])
    writer.setLODJointMapping(0, 0)
    writer.setNeutralJointTranslations([[0.0, 0.0, 0.0], [0.0, 10.0, 2.0]])
    writer.setNeutralJointRotations([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])

    writer.setRawControlName(0, JAW_OPEN_CONTROL)
    if gui_control:
        writer.setGUIControlName(0, JAW_GUI_CONTROL)
        writer.setGUIToRawInputIndices([0])
        writer.setGUIToRawOutputIndices([0])
        writer.setGUIToRawFromValues([0.0])
        writer.setGUIToRawToValues([1.0])
        writer.setGUIToRawSlopeValues([1.0])
        writer.setGUIToRawCutValues([0.0])
    writer.setJointRowCount(2 * JOINT_ATTRIBUTE_COUNT)
    writer.setJointColumnCount(1)
    writer.setJointGroupLODs(0, [1])
    writer.setJointGroupInputIndices(0, [0])
    writer.setJointGroupOutputIndices(0, [1 * JOINT_ATTRIBUTE_COUNT + ROTATION_X])
    writer.setJointGroupValues(0, [JAW_OPEN_DEGREES])
    writer.setJointGroupJointIndices(0, [1])

    writer.write()
    if not dna.Status.isOk():
        raise RuntimeError(f"Could not write synthetic DNA: {dna.Status.get().message}")
    del writer, stream
    return path


def jaw_rotation_x(riglogic: ModuleType, reader: object, jaw_open: float) -> float:
    """Evaluate the rig with ``jawOpen`` set and return the jaw joint's X rotation output."""
    rig_logic = riglogic.RigLogic(reader)
    instance = riglogic.RigInstance(rig_logic)
    instance.setRawControl(0, jaw_open)
    rig_logic.calculate(instance)
    outputs = list(instance.getJointOutputs())
    return outputs[1 * JOINT_ATTRIBUTE_COUNT + ROTATION_X]


BLEND_SHAPE_MESH = "head_lod0_mesh"
# Vertex positions in DNA space (Y-up, centimetres).
BLEND_SHAPE_VERTICES = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))
# Channel name -> {vertex index: delta}. The second name makes ``{mesh}__{channel}`` 70 characters
# long, over Blender's 63-character limit, like MetaHuman's funnelWide correctives.
BLEND_SHAPE_TARGETS = {
    "jaw_open": {2: (0.0, -0.5, 0.25)},
    "Mfunnel_MupperLipRaise_MlowerLipDepress__funnelWide_UL": {0: (0.1, 0.2, 0.3), 1: (0.0, 0.0, -1.0)},
}


def write_blend_shape_mesh(dna: ModuleType, path: Path) -> Path:
    """Write a one-triangle mesh with the blend shape targets in ``BLEND_SHAPE_TARGETS``."""
    stream = dna.FileStream(str(path), dna.FileStream.AccessMode_Write, dna.FileStream.OpenMode_Binary)
    writer = dna.BinaryStreamWriter(stream)
    writer.setName("synthetic_blend_shapes")
    writer.setLODCount(1)
    writer.setDBMaxLOD(0)
    writer.setMeshName(0, BLEND_SHAPE_MESH)
    writer.setMeshIndices(0, [0])
    writer.setLODMeshMapping(0, 0)
    writer.setVertexPositions(0, [list(vertex) for vertex in BLEND_SHAPE_VERTICES])
    writer.setVertexLayouts(0, [[index, 0, 0] for index in range(len(BLEND_SHAPE_VERTICES))])
    writer.setFaceVertexLayoutIndices(0, 0, [0, 1, 2])

    channels = list(BLEND_SHAPE_TARGETS)
    for index, name in enumerate(channels):
        writer.setBlendShapeChannelName(index, name)
    writer.setBlendShapeChannelIndices(0, list(range(len(channels))))
    writer.setLODBlendShapeChannelMapping(0, 0)
    for target, name in enumerate(channels):
        deltas = BLEND_SHAPE_TARGETS[name]
        writer.setBlendShapeChannelIndex(0, target, target)
        writer.setBlendShapeTargetVertexIndices(0, target, list(deltas))
        writer.setBlendShapeTargetDeltas(0, target, [list(delta) for delta in deltas.values()])

    writer.write()
    if not dna.Status.isOk():
        raise RuntimeError(f"Could not write synthetic DNA: {dna.Status.get().message}")
    del writer, stream
    return path


CORRECTIVE_RAW_CONTROLS = ("CTRL_expressions.jawOpen", "CTRL_expressions.mouthFunnelUL", "CTRL_expressions.browRaiseL")
# (name, driving control): a raw control, a PSD of two raws, and a PSD with a weight-4 input.
CORRECTIVE_CHANNELS = (("jaw_open", 0), ("jaw_open_funnel_UL", 3), ("jaw_open_brow_raise_L", 4))
CORRECTIVE_PSDS = {3: ((0, 1.0), (1, 1.0)), 4: ((0, 4.0), (2, 1.0))}  # PSD control -> (input, weight)
CORRECTIVE_MESH = "head_lod0_mesh"
CORRECTIVE_VERTICES = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0))
# One target per channel, in channel order: vertex index -> delta (DNA space, cm).
CORRECTIVE_TARGETS = ({2: (0.0, -0.5, 0.25)}, {0: (0.1, 0.2, 0.3), 3: (0.0, 0.0, -1.0)}, {1: (0.5, 0.0, 0.0)})


def write_corrective_rig(dna: ModuleType, path: Path) -> Path:
    """Write a rig whose channels are driven by a raw control and two correctives (PSDs).

    One root joint (RigLogic needs a skeleton), three raw controls, PSD 3 = jawOpen x funnelUL and
    PSD 4 = clamp(4 * jawOpen x browRaiseL), and a four-vertex mesh with one target per channel.
    """
    stream = dna.FileStream(str(path), dna.FileStream.AccessMode_Write, dna.FileStream.OpenMode_Binary)
    writer = dna.BinaryStreamWriter(stream)
    writer.setName("synthetic_correctives")
    writer.setLODCount(1)
    writer.setDBMaxLOD(0)
    writer.setJointName(0, "root")
    writer.setJointHierarchy([0])
    writer.setJointIndices(0, [0])
    writer.setLODJointMapping(0, 0)
    writer.setNeutralJointTranslations([[0.0, 0.0, 0.0]])
    writer.setNeutralJointRotations([[0.0, 0.0, 0.0]])

    for index, name in enumerate(CORRECTIVE_RAW_CONTROLS):
        writer.setRawControlName(index, name)
    raw_count = len(CORRECTIVE_RAW_CONTROLS)
    rows, columns, values = [], [], []
    for control, inputs in CORRECTIVE_PSDS.items():
        for column, weight in inputs:
            rows.append(control)
            columns.append(column)
            values.append(weight)
    writer.setPSDCount(len(CORRECTIVE_PSDS))
    writer.setPSDRowIndices(rows)
    writer.setPSDColumnIndices(columns)
    writer.setPSDValues(values)
    assert min(CORRECTIVE_PSDS) == raw_count  # PSD controls follow the raw controls

    for channel, (name, _control) in enumerate(CORRECTIVE_CHANNELS):
        writer.setBlendShapeChannelName(channel, name)
    writer.setBlendShapeChannelIndices(0, list(range(len(CORRECTIVE_CHANNELS))))
    writer.setLODBlendShapeChannelMapping(0, 0)
    writer.setBlendShapeChannelLODs([len(CORRECTIVE_CHANNELS)])
    writer.setBlendShapeChannelInputIndices([control for _name, control in CORRECTIVE_CHANNELS])
    writer.setBlendShapeChannelOutputIndices(list(range(len(CORRECTIVE_CHANNELS))))

    writer.setMeshName(0, CORRECTIVE_MESH)
    writer.setMeshIndices(0, [0])
    writer.setLODMeshMapping(0, 0)
    writer.setVertexPositions(0, [list(vertex) for vertex in CORRECTIVE_VERTICES])
    writer.setVertexLayouts(0, [[index, 0, 0] for index in range(len(CORRECTIVE_VERTICES))])
    writer.setFaceVertexLayoutIndices(0, 0, [0, 1, 3, 2])
    for target, deltas in enumerate(CORRECTIVE_TARGETS):
        writer.setBlendShapeChannelIndex(0, target, target)
        writer.setBlendShapeTargetVertexIndices(0, target, list(deltas))
        writer.setBlendShapeTargetDeltas(0, target, [list(delta) for delta in deltas.values()])

    writer.write()
    if not dna.Status.isOk():
        raise RuntimeError(f"Could not write synthetic DNA: {dna.Status.get().message}")
    del writer, stream
    return path
