"""Clothing (dna_core.clothing): the body faces the clothes cover, and fabric settings."""

import json

from pathlib import Path

import numpy as np
import pytest

from dna_core.clothing import GeometryError, body_coverage, coverage, fabric_settings


def mesh(face_count: int, visible_faces: list[int], name: str = "body_lod0_mesh", **extra: object) -> dict:
    """A Geometry/body.json mesh entry: each visible quad lists both of its triangles."""
    triangles = [[face, 0, 1, 2] for face in visible_faces] + [[face, 0, 2, 3] for face in visible_faces]
    return {
        "name": name,
        "lod": 0,
        "face_count": face_count,
        "visibility_valid": True,
        "visible_triangles": triangles,
        **extra,
    }


def test_faces_without_a_visible_triangle_are_covered():
    result = coverage(mesh(6, [0, 1, 4]))
    assert result.hidden.tolist() == [False, False, True, True, False, True]
    assert result.hidden_count == 3
    assert result.partial == 0


def test_a_half_visible_face_stays_visible_and_is_counted():
    entry = mesh(3, [0])
    entry["visible_triangles"].append([2, 0, 1, 2])  # face 2: only one of its triangles
    result = coverage(entry)
    assert result.hidden.tolist() == [False, True, False]
    assert result.partial == 1


def test_invalid_visibility_is_refused():
    with pytest.raises(GeometryError, match="not valid"):
        coverage(mesh(4, [0], visibility_valid=False))
    with pytest.raises(GeometryError, match=r"outside 0\.\.3"):
        coverage(mesh(4, [7]))


def test_reads_every_lod_of_body_json(tmp_path: Path):
    path = tmp_path / "body.json"
    path.write_text(json.dumps({"meshes": [mesh(4, [0, 1]), mesh(2, [1], name="body_lod1_mesh", lod=1)]}))
    result = body_coverage(path)
    assert list(result) == ["body_lod0_mesh", "body_lod1_mesh"]
    assert result["body_lod1_mesh"].lod == 1
    np.testing.assert_array_equal(result["body_lod0_mesh"].hidden, [False, False, True, True])
    with pytest.raises(GeometryError, match="Can't read"):
        body_coverage(tmp_path / "missing.json")


def test_fabric_settings_as_exported_with_defaults():
    settings = fabric_settings({"color": [0.59, 0.59, 0.59], "micro_scale": 80, "normal_strength": 1})
    assert settings["color"] == (0.59, 0.59, 0.59)
    assert settings["micro_scale"] == 80.0
    assert settings["stitch_color"] == (1.0, 1.0, 1.0)  # not exported: default
    assert settings["macro_scale"] == 1.0
