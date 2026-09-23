"""The control graph behind blend shape channels, checked against RigLogic on a synthetic rig."""

import itertools

from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, ClassVar

import pytest
import synthetic

from dna_core import load
from dna_core.psd import PSD, RAW, ControlGraph, NotActivatableError


@pytest.fixture
def graph_and_reader(dna: ModuleType, tmp_path: Path) -> tuple[ControlGraph, Any]:
    reader = load(synthetic.write_corrective_rig(dna, tmp_path / "correctives.dna"))
    return ControlGraph(reader), reader


def test_control_kinds_and_names(graph_and_reader: tuple[ControlGraph, Any]):
    graph, _ = graph_and_reader
    assert [graph.kind(control) for control in range(5)] == [RAW, RAW, RAW, PSD, PSD]
    assert graph.name(0) == "CTRL_expressions.jawOpen"
    assert graph.name(3) == "PSD 0"
    with pytest.raises(IndexError):
        graph.kind(5)


def test_channels_read_their_driving_control(graph_and_reader: tuple[ControlGraph, Any]):
    graph, _ = graph_and_reader
    assert [graph.channel_control(channel) for channel in range(3)] == [0, 3, 4]
    assert graph.leaves(1) == {0: RAW, 1: RAW}
    tree = graph.dependency_tree(2)
    assert (tree.kind, tree.name) == (PSD, "PSD 1")
    assert [(child.name, child.weight) for child in tree.inputs] == [
        ("CTRL_expressions.jawOpen", 4.0),
        ("CTRL_expressions.browRaiseL", 1.0),
    ]


def test_activation_switches_each_channel_fully_on(graph_and_reader: tuple[ControlGraph, Any], riglogic: ModuleType):
    graph, reader = graph_and_reader
    rig_logic = riglogic.RigLogic(reader)
    instance = riglogic.RigInstance(rig_logic)
    for channel in range(3):
        activation = graph.activation(channel)
        assert set(activation.values()) == {1.0}
        for control in range(reader.getRawControlCount()):
            instance.setRawControl(control, activation.get(control, 0.0))
        rig_logic.calculate(instance)
        assert list(instance.getBlendShapeOutputs())[channel] == pytest.approx(1.0)


def test_psd_formula_matches_riglogic(graph_and_reader: tuple[ControlGraph, Any], riglogic: ModuleType):
    graph, reader = graph_and_reader
    rig_logic = riglogic.RigLogic(reader)
    instance = riglogic.RigInstance(rig_logic)
    for values in itertools.product((0.0, 0.1, 0.3, 0.5, 1.0), repeat=3):
        raw = dict(enumerate(values))
        for control, value in raw.items():
            instance.setRawControl(control, value)
        rig_logic.calculate(instance)
        outputs = list(instance.getBlendShapeOutputs())
        assert [graph.channel_value(channel, raw) for channel in range(3)] == pytest.approx(outputs, abs=1e-6)


class _StubReader:
    """A control structure with an RBF pose control feeding a PSD, which no synthetic DNA has."""

    _VALUES: ClassVar[dict[str, object]] = {
        "getRawControlCount": 1,
        "getPSDCount": 1,
        "getMLControlCount": 0,
        "getRBFPoseControlCount": 1,
        "getRawControlName": "CTRL_expressions.jawOpen",
        "getRBFPoseControlName": "neck_rbf_pose",
        "getMLControlName": "",
        "getPSDRowIndices": [1, 1],
        "getPSDColumnIndices": [0, 2],
        "getPSDValues": [1.0, 1.0],
        "getBlendShapeChannelCount": 2,
        "getBlendShapeChannelInputIndices": [1, 2],
        "getBlendShapeChannelOutputIndices": [0, 1],
    }

    def __getattr__(self, name: str) -> Callable[..., object]:
        if name == "getBlendShapeChannelName":
            return ("neck_corrective", "neck_pose").__getitem__
        value = self._VALUES[name]
        return lambda *_args: value


def test_channels_needing_rbf_poses_are_not_activatable():
    graph = ControlGraph(_StubReader())
    assert graph.kind(2) == "rbf"
    for channel in (0, 1):
        assert not graph.activatable(channel)
        with pytest.raises(NotActivatableError, match="bone rotations"):
            graph.activation(channel)
