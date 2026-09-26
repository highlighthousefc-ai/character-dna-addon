"""Clothing (Slice 3): which body faces the clothes cover, and the fabric settings. No ``bpy``.

The export's ``Geometry/body.json`` lists, per body mesh (one per LOD), the triangles that stay
visible under the outfit: ``visible_triangles`` entries are ``[face, v0, v1, v2]``, a DNA face index
and one of its triangles (dev-docs/FINDINGS.md "Character Assembly Slice 3"). On the real export every
quad is either fully visible (both triangles listed) or fully covered (neither), and the DNA importer
builds the body mesh with the DNA's faces in the same order, so a face is hidden when none of its
triangles is listed.

``fabric`` is the manifest's per-material garment settings: ``color`` and ``stitch_color`` (linear
RGB), ``normal_strength``, ``micro_normal_strength``, ``micro_scale`` and ``macro_scale`` (tiling).
"""

import json

from dataclasses import dataclass
from pathlib import Path

import numpy as np


class GeometryError(ValueError):
    """``Geometry/<role>.json`` can't be used for this mesh."""


@dataclass(frozen=True)
class Coverage:
    """Body faces covered by the clothes, for one mesh (LOD)."""

    name: str
    lod: int
    hidden: np.ndarray  # (faces,) bool
    partial: int  # faces with only one of their triangles visible (kept visible)

    @property
    def hidden_count(self) -> int:
        return int(self.hidden.sum())


def coverage(mesh: dict) -> Coverage:
    """Covered faces of one ``meshes[]`` entry of ``Geometry/body.json``."""
    if not mesh.get("visibility_valid", False):
        raise GeometryError(f"{mesh.get('name')}: the export marks its visibility as not valid")
    face_count = int(mesh["face_count"])
    visible = np.zeros(face_count, dtype=np.int64)
    faces = np.asarray([entry[0] for entry in mesh.get("visible_triangles", [])], dtype=np.int64)
    if len(faces) and (faces.min() < 0 or faces.max() >= face_count):
        raise GeometryError(f"{mesh.get('name')}: a visible triangle names a face outside 0..{face_count - 1}")
    np.add.at(visible, faces, 1)
    return Coverage(
        name=str(mesh.get("name", "")),
        lod=int(mesh.get("lod", 0)),
        hidden=visible == 0,
        partial=int(((visible > 0) & (visible < 2)).sum()),
    )


def body_coverage(path: Path) -> dict[str, Coverage]:
    """Mesh name (``body_lod0_mesh`` ...) -> its covered faces."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GeometryError(f"Can't read {Path(path).name}: {error}") from error
    return {entry["name"]: coverage(entry) for entry in data.get("meshes", [])}


# Manifest ``fabric`` -> the values the fabric material uses, with Unreal's defaults when absent.
FABRIC_DEFAULTS = {
    "color": (1.0, 1.0, 1.0),
    "stitch_color": (1.0, 1.0, 1.0),
    "normal_strength": 1.0,
    "micro_normal_strength": 1.0,
    "micro_scale": 1.0,
    "macro_scale": 1.0,
}


def fabric_settings(fabric: dict) -> dict[str, object]:
    settings = dict(FABRIC_DEFAULTS)
    for key, default in FABRIC_DEFAULTS.items():
        if key in fabric:
            value = fabric[key]
            settings[key] = tuple(float(v) for v in value[:3]) if isinstance(default, tuple) else float(value)
    return settings
