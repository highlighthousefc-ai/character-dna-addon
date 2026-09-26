"""Groom curves from an Alembic file, converted for Blender. No ``bpy``.

The export's grooms (``Grooms/*.abc``) are Alembic curves written the way Unreal's groom importer
reads them (dev-docs/FINDINGS.md "Character Assembly Slice 0"):

* ``.geom/P`` points and ``.geom/nVertices`` points per strand, linear, **Z-up, centimetres**.
* ``.geom/width`` per point (a few are slightly negative), ``.geom/uv`` the root UV per strand, in
  the head's UV layout.
* ``.arbGeomParams/groom_guide`` per strand: 1 marks a simulation guide, not a rendered strand.
  Some grooms keep their guides collapsed at the origin. ``groom_color`` per point, on some grooms.

:func:`to_blender` keeps the rendered strands only and converts to Blender's frame, which matches
how the DNA importer places the head: file ``(x, y, z)`` cm -> Blender ``(x, -y, z) / 100`` m (a
mirror, measured from the root UVs). Radius is half the width, in metres too.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .alembic import AlembicError, Archive, Compound


CM_TO_M = 0.01
# File (x, y, z) -> Blender (x, -y, z): the Unreal-to-Blender mirror for grooms (Slice 0).
AXIS_SIGN = np.array([1.0, -1.0, 1.0], dtype=np.float32)


@dataclass
class Groom:
    """A groom as stored in the file: centimetres, file axes, guides included."""

    points: np.ndarray  # (points, 3) float32
    counts: np.ndarray  # (strands,) int32, points per strand
    widths: np.ndarray | None  # (points,) float32
    root_uv: np.ndarray | None  # (strands, 2) float32
    guide: np.ndarray | None  # (strands,) bool
    color: np.ndarray | None  # (points, 3) float32

    @property
    def strands(self) -> int:
        return len(self.counts)

    @property
    def guides(self) -> int:
        return int(self.guide.sum()) if self.guide is not None else 0


@dataclass
class BlenderGroom:
    """Rendered strands in Blender's frame: metres, Z-up (x, -y, z), guides removed."""

    positions: np.ndarray  # (points, 3) float32, metres
    counts: np.ndarray  # (strands,) int32
    radius: np.ndarray  # (points,) float32, metres
    root_uv: np.ndarray | None  # (strands, 2) float32
    color: np.ndarray | None  # (points, 3) float32
    guides_removed: int
    negative_widths: int


def _curves_schema(archive: Archive) -> Compound:
    for _, node in archive.top.walk():
        if node.metadata.get("schema", "").startswith("AbcGeom_Curve"):
            geom = node.properties.get(".geom")
            if geom is not None:
                return geom.compound()
    raise AlembicError(f"{archive.path.name} has no curves")


def _array(compound: Compound, path: str, dtype: str, extent: int = 1) -> np.ndarray | None:
    prop = compound.get(path)
    if prop is None:
        return None
    if prop.kind == "compound":  # an indexed geom param: .vals (+ .indices)
        values = prop.compound().get(".vals")
        indices = prop.compound().get(".indices")
        if values is None:
            return None
        array = np.asarray(values.values())
        if indices is not None:
            array = array[np.asarray(indices.values(), dtype=np.int64)]
    else:
        array = np.asarray(prop.values())
    array = array.astype(dtype, copy=False)
    return array.reshape(-1, extent) if extent > 1 else array.reshape(-1)


def read_groom(path: Path) -> Groom:
    """Read the first curves object of an Alembic file (sample 0)."""
    with Archive(Path(path)) as archive:
        geom = _curves_schema(archive)
        points = _array(geom, "P", "<f4", 3)
        counts = _array(geom, "nVertices", "<i4")
        if points is None or counts is None:
            raise AlembicError(f"{Path(path).name}: curves without points")
        if int(counts.sum()) != len(points):
            raise AlembicError(f"{Path(path).name}: {len(points)} points but the strands need {int(counts.sum())}")
        guide = _array(geom, ".arbGeomParams/groom_guide", "<i4")
        groom = Groom(
            points=points,
            counts=counts,
            widths=_array(geom, "width", "<f4"),
            root_uv=_array(geom, "uv", "<f4", 2),
            guide=None if guide is None else guide.astype(bool),
            color=_array(geom, ".arbGeomParams/groom_color", "<f4", 3),
        )
    for name, array, expected in (
        ("width", groom.widths, len(points)),
        ("uv", groom.root_uv, len(counts)),
        ("groom_guide", groom.guide, len(counts)),
        ("groom_color", groom.color, len(points)),
    ):
        if array is not None and len(array) != expected:
            raise AlembicError(f"{Path(path).name}: {name} has {len(array)} values, expected {expected}")
    return groom


def taper(counts: np.ndarray, root_scale: float, tip_scale: float) -> np.ndarray:
    """Per point: ``root_scale`` at each strand's root, ``tip_scale`` at its tip, linear by point index."""
    counts = np.asarray(counts, dtype=np.int64)
    first = np.repeat(np.cumsum(counts) - counts, counts)
    index = np.arange(int(counts.sum())) - first
    last = np.repeat(np.maximum(counts - 1, 1), counts)
    t = index / last
    return (root_scale + (tip_scale - root_scale) * t).astype(np.float32)


def to_blender(
    groom: Groom,
    drop_guides: bool = True,
    width: float | None = None,
    root_scale: float = 1.0,
    tip_scale: float = 1.0,
) -> BlenderGroom:
    """Rendered strands in Blender's frame. Negative widths become 0.

    ``width`` (cm) replaces the file's widths with Unreal's groom width override, tapered from
    ``root_scale`` to ``tip_scale`` along each strand (Unreal's root / tip scale).
    """
    keep = np.ones(groom.strands, dtype=bool)
    if drop_guides and groom.guide is not None:
        keep = ~groom.guide
    point_keep = np.repeat(keep, groom.counts)
    widths = groom.widths if groom.widths is not None else np.zeros(len(groom.points), np.float32)
    widths = widths[point_keep]
    if width is not None:
        widths = np.float32(width) * taper(groom.counts[keep], root_scale, tip_scale)
    return BlenderGroom(
        positions=(groom.points[point_keep] * AXIS_SIGN * CM_TO_M).astype(np.float32),
        counts=groom.counts[keep].astype(np.int32),
        radius=(np.maximum(widths, 0.0) * 0.5 * CM_TO_M).astype(np.float32),
        root_uv=None if groom.root_uv is None else groom.root_uv[keep],
        color=None if groom.color is None else groom.color[point_keep],
        guides_removed=int((~keep).sum()),
        negative_widths=int((widths < 0).sum()),
    )


# Manifest ``hair_color`` -> Principled Hair BSDF (melanin parametrisation) inputs.
HAIR_INPUTS = {"melanin": "Melanin", "redness": "Melanin Redness", "roughness": "Roughness", "tint": "Tint"}


def hair_shader_inputs(hair_color: dict) -> tuple[dict[str, object], list[str]]:
    """Principled Hair BSDF input values for a manifest ``hair_color``, and the keys left unmapped.

    Melanin, redness, tint and roughness carry over as exported (both use a 0-1 melanin model).
    ``white_amount``, ``color`` (Unreal's resolved colour, used here for the viewport only) and the
    colour ``ramps`` have no Principled Hair input.
    """
    values: dict[str, object] = {}
    for key, socket in HAIR_INPUTS.items():
        if key not in hair_color:
            continue
        value = hair_color[key]
        values[socket] = (*map(float, value[:3]), 1.0) if key == "tint" else float(value)
    unmapped = [key for key in hair_color if key not in HAIR_INPUTS and key != "color"]
    return values, unmapped
