"""Sidebar panel: the active character's grooms, each with a one-click viewport toggle."""

from typing import Any

import bpy

from .. import utilities
from ..constants import PanelOrder, ToolInfo
from ..ui import callbacks
from ..ui.view_3d import RigInstanceDependentPanel
from .clothing import CLOTHING_PROPERTY, HIDE_MODIFIER, body_hiding_enabled
from .grooms import FUZZ_REGION, GROOM_PROPERTY
from .wrinkles import AREAS, GAIN_INPUT, STRENGTH_PREFIX, is_offset_logic


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


class CHARACTER_DNA_PT_wrinkles(RigInstanceDependentPanel):
    """Offset wrinkle maps: one strength per facial area, and an overall gain."""

    bl_label = "Wrinkles"
    bl_category = "Character DNA"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = PanelOrder.GROOMS.value + 1

    @staticmethod
    def logic_node(instance: Any) -> Any:
        material = instance.head_material if instance is not None else None
        return callbacks.get_head_texture_logic_node(material) if material else None

    @classmethod
    def poll(cls, context: Any) -> bool:
        return super().poll(context) and is_offset_logic(cls.logic_node(utilities.get_active_rig_instance()))

    def draw(self, _context: Any) -> None:
        layout = self.layout
        logic = self.logic_node(utilities.get_active_rig_instance())
        if layout is None or logic is None:
            return
        layout.label(text="Wrinkle maps are offsets (Unreal 5.6+)", icon="INFO")
        column = layout.column(align=True)
        for area in AREAS:
            column.prop(logic.inputs[STRENGTH_PREFIX + area], "default_value", text=area)
        layout.prop(logic.inputs[GAIN_INPUT], "default_value", text="Gain")


def instance_bodies(instance: Any) -> list[bpy.types.Object]:
    prefix = f"{instance.name}_body_lod"
    return [o for o in bpy.data.objects if o.name.startswith(prefix) and o.modifiers.get(HIDE_MODIFIER)]


def instance_clothing(instance: Any) -> list[bpy.types.Object]:
    prefix = f"{instance.name}_"
    return sorted(
        (o for o in bpy.data.objects if o.get(CLOTHING_PROPERTY) and o.name.startswith(prefix)), key=lambda o: o.name
    )


class CHARACTER_DNA_PT_clothing(RigInstanceDependentPanel):
    bl_label = "Clothing"
    bl_category = "Character DNA"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_order = PanelOrder.GROOMS.value + 2

    @classmethod
    def poll(cls, context: Any) -> bool:
        instance = utilities.get_active_rig_instance()
        return super().poll(context) and instance is not None and bool(instance_clothing(instance))

    def draw(self, _context: Any) -> None:
        layout = self.layout
        instance = utilities.get_active_rig_instance()
        if layout is None or instance is None:
            return
        for scene_object in instance_clothing(instance):
            row = layout.row(align=True)
            row.label(text=scene_object.name.removeprefix(instance.name + "_"), icon="MOD_CLOTH")
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
        bodies = instance_bodies(instance)
        if bodies:
            enabled = body_hiding_enabled(bodies)
            layout.operator(
                f"{ToolInfo.NAME}.toggle_body_under_clothes",
                text="Body Under Clothes: " + ("Hidden" if enabled else "Shown"),
                icon="HIDE_ON" if enabled else "HIDE_OFF",
                depress=enabled,
            )


classes = (CHARACTER_DNA_PT_grooms, CHARACTER_DNA_PT_wrinkles, CHARACTER_DNA_PT_clothing)
