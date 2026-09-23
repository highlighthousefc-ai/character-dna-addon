"""Pure DNA layer: read, write and inspect MetaHuman DNA files without Blender.

This package must never import ``bpy`` (or ``bmesh`` / ``mathutils``), so it can be tested with
plain CPython and reused outside Blender. ``tests_core/test_no_bpy.py`` enforces this. Blender-side
import/export stays in ``dna_io``.
"""

from .naming import shape_key_name
from .reader import DnaReadError, load
from .writer import DnaWriteError, write_copy


__all__ = [
    "DnaReadError",
    "DnaWriteError",
    "load",
    "shape_key_name",
    "write_copy",
]
