"""Blend shape naming and the synthetic blend-shape DNA the in-Blender CI check imports."""

from pathlib import Path
from types import ModuleType

import pytest
import synthetic

from dna_core import load, shape_key_name
from dna_core.naming import BLENDER_NAME_MAX_LENGTH


def test_short_names_are_mesh_double_underscore_channel():
    assert shape_key_name("head_lod0_mesh", "jaw_open") == "head_lod0_mesh__jaw_open"


@pytest.mark.parametrize("corner", ["UL", "UR", "DL", "DR"])
def test_long_names_fit_blender_and_stay_distinct(corner: str):
    channel = f"Mfunnel_MupperLipRaise_MlowerLipDepress__funnelWide_{corner}"
    name = shape_key_name("head_lod0_mesh", channel)
    assert len(name) == BLENDER_NAME_MAX_LENGTH
    assert name.startswith("head_lod0_mesh__Mfunnel_MupperLipRaise")
    assert name == shape_key_name("head_lod0_mesh", channel)  # deterministic
    others = {shape_key_name("head_lod0_mesh", channel[:-2] + c) for c in ("UL", "UR", "DL", "DR")}
    assert len(others) == 4  # Blender's own truncation made these four identical


def test_name_limit_counts_bytes():
    name = shape_key_name("mesh", "é" * 40)  # 2 bytes each in UTF-8
    assert len(name.encode("utf-8")) <= BLENDER_NAME_MAX_LENGTH


def test_synthetic_blend_shape_mesh_reads_back(dna: ModuleType, tmp_path: Path):
    reader = load(synthetic.write_blend_shape_mesh(dna, tmp_path / "shapes.dna"))
    assert reader.getMeshName(0) == synthetic.BLEND_SHAPE_MESH
    assert reader.getVertexPositionCount(0) == len(synthetic.BLEND_SHAPE_VERTICES)
    assert reader.getBlendShapeTargetCount(0) == len(synthetic.BLEND_SHAPE_TARGETS)
    for target, (name, deltas) in enumerate(synthetic.BLEND_SHAPE_TARGETS.items()):
        assert reader.getBlendShapeChannelName(reader.getBlendShapeChannelIndex(0, target)) == name
        assert list(reader.getBlendShapeTargetVertexIndices(0, target)) == list(deltas)
        xs = reader.getBlendShapeTargetDeltaXs(0, target)
        ys = reader.getBlendShapeTargetDeltaYs(0, target)
        zs = reader.getBlendShapeTargetDeltaZs(0, target)
        read = [value for vertex in zip(xs, ys, zs, strict=True) for value in vertex]
        assert read == pytest.approx([value for delta in deltas.values() for value in delta])
