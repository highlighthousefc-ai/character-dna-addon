"""Shape Key Editor: sculpt a MetaHuman blend shape against its dependencies and commit it to the DNA.

v1 scope: Edit -> Commit -> Revert on channels driven by face expressions (raw controls and PSD
correctives). See ``session`` for how a session works and ``dna_core.psd`` / ``dna_core.blend_shapes``
for the DNA side.
"""

import bpy

from . import operators, properties, ui


def register() -> None:
    properties.register()
    for cls in (*operators.classes, *ui.classes):
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed((*operators.classes, *ui.classes)):
        bpy.utils.unregister_class(cls)
    properties.unregister()
