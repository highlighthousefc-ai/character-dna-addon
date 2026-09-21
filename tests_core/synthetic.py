"""Tiny synthetic DNA files for tests, so CI never needs Epic-owned DNA data.

Only uses the ``dna`` module passed in, so it works with bare bindings on ``sys.path`` and with
the addon's isolated copy inside Blender.
"""

from pathlib import Path
from types import ModuleType


JAW_OPEN_CONTROL = "CTRL_expressions.jawOpen"
JAW_JOINT = "FACIAL_C_Jaw"
JAW_OPEN_DEGREES = 25.0
# RigLogic joint outputs are 9 values per joint: translation xyz, rotation xyz, scale xyz.
JOINT_ATTRIBUTE_COUNT = 9
ROTATION_X = 3


def write_jaw_rig(dna: ModuleType, path: Path) -> Path:
    """Write a two-joint rig where ``jawOpen`` = 1 rotates the jaw joint by 25 degrees about X."""
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
