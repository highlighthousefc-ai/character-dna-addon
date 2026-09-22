"""Drive the synthetic jaw rig through ``runtime/python_evaluator`` (the engine's frame evaluator).

This exercises the same path live face-board evaluation takes inside Blender, without Blender:
face-board GUI control -> ``mapGUIToRawControls`` -> RigLogic ``calculate`` -> SDK joint outputs ->
``transform_into`` -> pose-bone location / XYZ Euler / scale channels. The buffers passed in are
the ones ``runtime/frame.py`` builds from a real rig (column-major bone matrices, a packed
27-float transform plan per written joint, ``(gui_index, face_bone, axis, center)`` GUI entries).

``runtime/python_evaluator`` imports no ``bpy``, so this runs with plain CPython. It relies on
pytest having imported the stdlib ``typing`` before ``conftest`` puts the addon folder (which has
its own ``typing.py``) on ``sys.path``.
"""

import importlib
import math
import os

from array import array
from pathlib import Path
from types import ModuleType

import pytest
import synthetic


IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
RIG_BONES = 2  # root, FACIAL_C_Jaw
JAW_JOINT_INDEX = 1
Y_AXIS = 1


@pytest.fixture
def evaluator(riglogic: ModuleType) -> ModuleType:  # noqa: ARG001 (bindings must be loaded first)
    """``runtime.python_evaluator``; numpy is required when bindings are required (CI)."""
    if os.environ.get("CHARACTER_DNA_REQUIRE_BINDINGS") == "1":
        importlib.import_module("numpy")
    else:
        pytest.importorskip("numpy")
    return importlib.import_module("runtime.python_evaluator")


@pytest.fixture
def jaw_session(evaluator: ModuleType, dna: ModuleType, tmp_path: Path) -> tuple:
    """A head session and frame plan for the synthetic jaw rig with its face-board control."""
    path = synthetic.write_jaw_rig(dna, tmp_path / "jaw.dna", gui_control=True)
    model = evaluator.load_model(str(path), False)
    session = evaluator.create_session(model)
    # One written joint (the jaw): joint index, has-children flag, rest location / rotation /
    # scale, then the row-major rest-to-parent inverse, exactly as engine.transform_plan packs it.
    plan = array("f", [JAW_JOINT_INDEX, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, *IDENTITY])
    frame_plan = evaluator.create_frame_plan(
        session,
        plan,
        array("f", IDENTITY * RIG_BONES),  # rest matrices (column-major, as foreach_get fills them)
        array("i", [-1, 0]),  # parents
        array("i", [0, 0, Y_AXIS, -1]),  # GUI control 0 <- face bone 0 (CTRL_C_jaw) .y, no center eye
        array("i"),  # no quaternion raw-control driver bones
        array("i"),  # no eye-aim chain
        array("i"),  # no eyes
        1,  # face-board bone count
        False,  # head, not body
    )
    return model, session, frame_plan


def _evaluate(evaluator: ModuleType, jaw_session: tuple, jaw_gui: float) -> tuple[array, array, dict]:
    model, session, frame_plan = jaw_session
    face = array("f", [0.0, jaw_gui, 0.0])  # CTRL_C_jaw location xyz
    sdk = array("d", [0.0]) * sum(model.info["output_counts"])
    local = array("d", [0.0]) * 9
    evaluator.evaluate_frame(
        session,
        frame_plan,
        array("f", IDENTITY * RIG_BONES),  # evaluated pose matrices
        array("f", [0.0]) * (RIG_BONES * 16),  # pose bases (only used for eye aim)
        face,
        array("f", [0.0]) * 38,  # rig/face world matrices + eye targets
        sdk,
        local,
        0,  # LOD
        True,  # evaluate RBFs
        False,  # eye aim off
    )
    return sdk, local, evaluator.control_snapshot(session)


def test_evaluator_reports_the_engine_api(evaluator: ModuleType):
    info = evaluator.capabilities()
    assert info["api_version"] == 1
    assert info["private_blender_api"] is False
    for name in (
        "load_model",
        "create_session",
        "describe",
        "create_frame_plan",
        "evaluate_frame",
        "control_snapshot",
        "transform_into",
    ):
        assert callable(getattr(evaluator, name)), name


@pytest.mark.parametrize(("jaw_gui", "expected_degrees"), [(0.0, 0.0), (0.5, 12.5), (1.0, 25.0)])
def test_face_board_jaw_drives_jaw_bone(
    evaluator: ModuleType, jaw_session: tuple, jaw_gui: float, expected_degrees: float
):
    sdk, local, controls = _evaluate(evaluator, jaw_session, jaw_gui)

    # GUI -> raw mapping ran: the face-board control reached the raw jawOpen control.
    assert controls["gui"][0] == pytest.approx(jaw_gui)
    assert controls["raw"][0] == pytest.approx(jaw_gui)
    # RigLogic's joint output (degrees, delta from neutral) for the jaw's X rotation.
    jaw_rx = JAW_JOINT_INDEX * synthetic.JOINT_ATTRIBUTE_COUNT + synthetic.ROTATION_X
    assert sdk[jaw_rx] == pytest.approx(expected_degrees)
    # transform_into turned it into Blender pose-bone channels: location, XYZ Euler (radians), scale.
    assert list(local[0:3]) == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    assert list(local[3:6]) == pytest.approx([math.radians(expected_degrees), 0.0, 0.0], abs=1e-6)
    assert list(local[6:9]) == pytest.approx([1.0, 1.0, 1.0], abs=1e-6)


def test_evaluation_is_repeatable(evaluator: ModuleType, jaw_session: tuple):
    _, first, _ = _evaluate(evaluator, jaw_session, 0.7)
    _, reset, _ = _evaluate(evaluator, jaw_session, 0.0)
    _, second, _ = _evaluate(evaluator, jaw_session, 0.7)
    assert list(reset[3:6]) == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    assert list(first) == list(second)
