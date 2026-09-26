"""Character assembly import (Slice 1): a MetaHuman "Export Character For DCC" folder via its manifest.

The manifest reading and the texture plan live in ``dna_core.assembly`` (no ``bpy``); this package
imports the DNAs, wires the textures (``materials``) and hides the meshes the manifest marks hidden.
See ``dev-docs/specs/08-character-assembly.md``.
"""

import bpy

from . import operators


def register() -> None:
    for cls in operators.classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(operators.classes):
        bpy.utils.unregister_class(cls)
