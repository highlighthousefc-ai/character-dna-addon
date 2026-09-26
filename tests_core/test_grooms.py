"""Groom Alembic reading (dna_core.alembic / dna_core.grooms) on a synthetic groom, no Epic data.

``fixtures/synthetic_groom.abc`` was written by the reference Alembic library
(``fixtures/make_synthetic_groom.cpp``): 4 strands, the second a guide collapsed at the origin, one
negative width, points in cm with Z up.
"""

from pathlib import Path

import numpy as np
import pytest

from dna_core.alembic import AlembicError, Archive
from dna_core.grooms import hair_shader_inputs, read_groom, to_blender


FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_groom.abc"


def test_reads_the_archive_tree():
    with Archive(FIXTURE) as archive:
        tree = {path: node.metadata.get("schema") for path, node in archive.top.walk()}
        assert tree == {"/Groom": "AbcGeom_Xform_v3", "/Groom/Curves": "AbcGeom_Curve_v2"}
        curves = next(node for path, node in archive.top.walk() if path == "/Groom/Curves")
        geom = curves.properties[".geom"].compound()
        assert {"P", "nVertices", "width", "uv", ".arbGeomParams"} <= set(geom.properties)
        assert geom["P"].extent == 3
        assert geom["uv"].metadata.get("geoScope") == "uni"  # one root UV per strand
        assert geom[".arbGeomParams/groom_guide"].kind == "array"


def test_reads_the_groom_as_written():
    groom = read_groom(FIXTURE)
    assert groom.counts.tolist() == [3, 4, 2, 3]
    assert groom.points.shape == (12, 3)
    assert groom.points[0].tolist() == [1.0, 2.0, 150.0]
    assert groom.points[-1].tolist() == [8.0, -9.0, 172.0]
    assert groom.guide.tolist() == [False, True, False, False]
    assert groom.guides == 1
    np.testing.assert_allclose(groom.root_uv, [[0.25, 0.75], [0.0, 0.0], [0.5, 0.5], [0.9, 0.1]])
    assert groom.widths[7] == pytest.approx(-0.0005)
    np.testing.assert_allclose(groom.color[0], [0.25, 0.5, 0.0])


def test_blender_frame_is_x_minus_y_z_in_metres():
    """File (x, y, z) cm -> Blender (x, -y, z) / 100 m (a mirror, measured on the real export)."""
    converted = to_blender(read_groom(FIXTURE))
    np.testing.assert_allclose(converted.positions[0], [0.01, -0.02, 1.50], rtol=1e-6)
    np.testing.assert_allclose(converted.positions[-1], [0.08, 0.09, 1.72], rtol=1e-6)


def test_guides_are_dropped():
    converted = to_blender(read_groom(FIXTURE))
    assert converted.counts.tolist() == [3, 2, 3]  # the 4-point guide is gone
    assert converted.guides_removed == 1
    assert len(converted.positions) == 8
    assert not np.any(np.all(converted.positions == 0, axis=1))  # no strand left at the origin
    np.testing.assert_allclose(converted.root_uv, [[0.25, 0.75], [0.5, 0.5], [0.9, 0.1]])
    kept = to_blender(read_groom(FIXTURE), drop_guides=False)
    assert kept.counts.tolist() == [3, 4, 2, 3]


def test_radius_is_half_the_width_in_metres_and_never_negative():
    converted = to_blender(read_groom(FIXTURE))
    assert converted.negative_widths == 1
    assert converted.radius.min() == 0.0
    np.testing.assert_allclose(converted.radius[:3], [0.0001, 0.000075, 0.00005], rtol=1e-6)  # 0.02 cm wide


def test_not_an_alembic_file(tmp_path: Path):
    bad = tmp_path / "bad.abc"
    bad.write_bytes(b"not an ogawa archive at all")
    with pytest.raises(AlembicError, match="not an Alembic"):
        read_groom(bad)


def test_hair_colour_maps_to_the_principled_hair_melanin_inputs():
    values, unmapped = hair_shader_inputs(
        {
            "melanin": 0.9,
            "redness": 0.25,
            "tint": [1.0, 0.5, 0.25],
            "roughness": 0.37,
            "white_amount": 0.0,
            "color": [0.006, 0.001, 0.0003],
            "ramps": {},
        }
    )
    assert values == {"Melanin": 0.9, "Melanin Redness": 0.25, "Tint": (1.0, 0.5, 0.25, 1.0), "Roughness": 0.37}
    assert unmapped == ["white_amount", "ramps"]
