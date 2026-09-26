"""Sidebar panel: the active character's grooms, each with a one-click viewport toggle."""

from typing import Any

import bpy

from .. import utilities
from ..constants import PanelOrder
from ..ui.view_3d import RigInstanceDependentPanel
from .grooms import FUZZ_REGION, GROOM_PROPERTY


def instance_grooms(instance: Any) -> list[bpy.types.Object]:
    prefix = f"{instance.name}_"
    return sorted(
        (o for o in bpy.data.objects if o.get(GROOM_PROPERTY) and o.name.startswith(prefix)),
        key=lambda o: o.name,
    )


class CHARACTER_DNA_PT_grooms(RigInstanceDependentPanel):
    bl_label = "Grooms"
    bl_category = "Character DNA"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_order = PanelOrder.GROOMS.value

    @classmethod
    def poll(cls, context: Any) -> bool:
        instance = utilities.get_active_rig_instance()
        return super().poll(context) and instance is not None and bool(instance_grooms(instance))

    def draw(self, _context: Any) -> None:
        layout = self.layout
        instance = utilities.get_active_rig_instance()
        if layout is None or instance is None:
            return
        for scene_object in instance_grooms(instance):
            region = scene_object[GROOM_PROPERTY]
            row = layout.row(align=True)
            label = f"{scene_object.name.removeprefix(instance.name + '_')} ({region})"
            row.label(text=label, icon="CURVES_DATA")
            row.label(text=f"{len(scene_object.data.curves):,}")
            shown = not scene_object.hide_viewport
            row.prop(
                scene_object,
                "hide_viewport",
                text="",
                icon="RESTRICT_VIEW_OFF" if shown else "RESTRICT_VIEW_ON",
                invert_checkbox=True,
                emboss=False,
            )
            row.prop(
                scene_object,
                "hide_render",
                text="",
                icon="RESTRICT_RENDER_ON" if scene_object.hide_render else "RESTRICT_RENDER_OFF",
                emboss=False,
            )
            if region == FUZZ_REGION and not shown:
                layout.label(text="Peach fuzz is hidden in the viewport and renders", icon="INFO")


classes = (CHARACTER_DNA_PT_grooms,)
