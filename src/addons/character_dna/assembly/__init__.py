"""Character assembly import (Slices 1-2): a MetaHuman "Export Character For DCC" folder via its manifest.

The manifest reading and the texture plan live in ``dna_core.assembly`` (no ``bpy``); this package
imports the DNAs, wires the textures (``materials``), imports the grooms onto the head
(``grooms``, with the numpy Alembic reader in ``dna_core``) and hides the meshes the manifest marks
hidden. ``ui`` lists the grooms with viewport toggles.
See ``dev-docs/specs/08-character-assembly.md``.
"""

import bpy

from . import operators, ui


def register() -> None:
    for cls in (*operators.classes, *ui.classes):
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed((*operators.classes, *ui.classes)):
        bpy.utils.unregister_class(cls)
