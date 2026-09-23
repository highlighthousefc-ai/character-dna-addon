"""Sidebar panel and lists of the Shape Key Editor."""

import re

from typing import Any

import bpy
import numpy as np

from .. import utilities
from ..constants import PanelOrder, ToolInfo
from ..ui.view_3d import RigInstanceDependentPanel
from . import session


# MetaHuman channel names end in their side: brow_down_L, mouth_cornerPull_R, ..._funnelWide_UL.
_LEFT = re.compile(r"_[UD]?L$")
_RIGHT = re.compile(r"_[UD]?R$")


def _side(name: str) -> str:
    return "L" if _LEFT.search(name) else "R" if _RIGHT.search(name) else "C"


def _listed_mesh(context: Any) -> tuple[Any, bpy.types.Object | None]:
    instance = utilities.get_active_rig_instance()
    mesh_object = bpy.data.objects.get(session.state(context).mesh) if instance else None
    return instance, mesh_object


class CHARACTER_DNA_UL_shape_keys(bpy.types.UIList):
    filter_side: bpy.props.EnumProperty(
        name="Side",
        items=[
            ("ALL", "All", "Both sides and the centre"),
            ("L", "L", "Left"),
            ("R", "R", "Right"),
            ("C", "C", "Centre"),
        ],
        default="ALL",
    )  # pyright: ignore[reportInvalidTypeForm]
    non_zero: bpy.props.BoolProperty(name="Non-zero", description="Only keys the face currently drives")  # pyright: ignore[reportInvalidTypeForm]
    has_deltas: bpy.props.BoolProperty(name="Has deltas", description="Hide keys whose DNA target moves no vertices")  # pyright: ignore[reportInvalidTypeForm]
    sort_by_value: bpy.props.BoolProperty(name="Sort by value", description="Highest value first")  # pyright: ignore[reportInvalidTypeForm]
    freeze: bpy.props.BoolProperty(
        name="Freeze", description="Keep the list's rows and order fixed while values change"
    )  # pyright: ignore[reportInvalidTypeForm]

    def draw_filter(self, _context: Any, layout: bpy.types.UILayout) -> None:
        row = layout.row(align=True)
        row.prop(self, "filter_name", text="")
        row.prop(self, "use_filter_invert", text="", icon="ARROW_LEFTRIGHT")
        row = layout.row(align=True)
        row.prop(self, "filter_side", expand=True)
        row = layout.row(align=True)
        row.prop(self, "non_zero", toggle=True)
        row.prop(self, "has_deltas", toggle=True)
        row.prop(self, "sort_by_value", toggle=True, text="By Value")
        row.prop(self, "freeze", toggle=True, icon="FREEZE")

    def filter_items(self, context: Any, data: Any, propname: str) -> tuple[list[int], list[int]]:
        blocks = getattr(data, propname)
        frozen = getattr(self, "_frozen", None)
        if self.freeze and frozen is not None and len(frozen[0]) == len(blocks):
            return frozen
        instance, mesh_object = _listed_mesh(context)
        infos = {}
        if instance is not None and mesh_object is not None:
            infos = session.key_infos(instance, utilities.remove_instance_prefix(mesh_object.name, instance.name))
        values = np.zeros(len(blocks), dtype=np.float32)
        blocks.foreach_get("value", values)
        visible = self.bitflag_filter_item
        flags = []
        pattern = self.filter_name.lower()
        for index, block in enumerate(blocks):
            info = infos.get(block.name)
            keep = index > 0 and info is not None
            if keep and pattern:
                keep = (pattern in block.name.lower()) != self.use_filter_invert
            if keep and self.filter_side != "ALL":
                keep = _side(block.name) == self.filter_side
            if keep and self.non_zero:
                keep = values[index] > 1e-4
            if keep and self.has_deltas:
                keep = info.has_deltas
            flags.append(visible if keep else 0)
        order = []
        if self.sort_by_value:
            ranked = sorted(range(len(blocks)), key=lambda index: -values[index])
            order = [0] * len(blocks)
            for position, index in enumerate(ranked):
                order[index] = position
        self._frozen = (flags, order)
        return flags, order

    def draw_item(
        self,
        context: Any,
        layout: bpy.types.UILayout,
        _data: Any,
        item: bpy.types.ShapeKey,
        _icon: int,
        _active_data: Any,
        _active_property: str,
        _index: int = 0,
        _flt_flag: int = 0,
    ) -> None:
        instance, mesh_object = _listed_mesh(context)
        info = None
        if instance is not None and mesh_object is not None:
            dna_mesh_name = utilities.remove_instance_prefix(mesh_object.name, instance.name)
            info = session.key_infos(instance, dna_mesh_name).get(item.name)
        channel_name = session.graph(instance).channel_names[info.channel] if info else item.name
        row = layout.row(align=True)
        row.label(text=channel_name, icon="SHAPEKEY_DATA" if info and info.has_deltas else "BLANK1")
        value = row.row()
        value.alignment = "RIGHT"
        value.label(text=f"{item.value:.2f}")
        button = row.row()
        button.enabled = bool(info and info.activatable) and not session.state(context).active
        operator = button.operator(
            f"{ToolInfo.NAME}.shape_key_edit", text="", icon="SCULPTMODE_HLT" if button.enabled else "LOCKED"
        )
        operator.key_name = item.name


class CHARACTER_DNA_UL_shape_key_dependencies(bpy.types.UIList):
    def draw_item(
        self,
        _context: Any,
        layout: bpy.types.UILayout,
        _data: Any,
        item: Any,
        _icon: int,
        _active_data: Any,
        _active_property: str,
        _index: int = 0,
        _flt_flag: int = 0,
    ) -> None:
        row = layout.row(align=True)
        row.label(text=item.name, icon="LOCKED")
        row.label(text=f"{item.weight:.2f}")
        row.prop(item, "visible", text="", icon="HIDE_OFF" if item.visible else "HIDE_ON", emboss=False)


class CHARACTER_DNA_PT_shape_key_editor(RigInstanceDependentPanel):
    bl_label = "Shape Key Editor"
    bl_category = "Character DNA"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = PanelOrder.SHAPE_KEY_EDITOR.value

    def draw(self, context: Any) -> None:
        layout = self.layout
        if layout is None:
            return
        state = session.state(context)
        if state.active:
            self._draw_session(context, layout, state)
        else:
            self._draw_list(context, layout, state)
        if state.status:
            layout.label(text=state.status, icon="INFO")

    @staticmethod
    def _draw_list(context: Any, layout: bpy.types.UILayout, state: Any) -> None:
        instance, mesh_object = _listed_mesh(context)
        layout.prop(state, "mesh", text="Mesh")
        if instance is None or mesh_object is None or not mesh_object.data.shape_keys:
            layout.label(text="Import the head's shape keys first (Rig Instances > Head).", icon="INFO")
            return
        layout.template_list(
            "CHARACTER_DNA_UL_shape_keys",
            "",
            mesh_object.data.shape_keys,
            "key_blocks",
            state,
            "list_index",
            rows=8,
        )
        layout.label(text="Pick a key's sculpt button to edit it against its dependencies.", icon="SCULPTMODE_HLT")

    @staticmethod
    def _draw_session(_context: Any, layout: bpy.types.UILayout, state: Any) -> None:
        box = layout.box()
        name = state.key_name
        try:
            instance = session.rig_instance(state.instance_name)
            name = session.graph(instance).channel_names[state.channel]
        except session.SessionError:
            box.label(text="The edited character is gone.", icon="ERROR")
            box.operator(f"{ToolInfo.NAME}.shape_key_abandon")
            return
        box.label(text=f"Editing: {name}", icon="SCULPTMODE_HLT")
        box.label(text=f"Mesh: {state.mesh_name}")
        box.label(text=f"Controls at 1: {state.controls}")
        row = box.row(align=True)
        row.operator(f"{ToolInfo.NAME}.shape_key_sculpt", text="Sculpt", icon="SCULPTMODE_HLT").mode = "SCULPT"
        row.operator(f"{ToolInfo.NAME}.shape_key_sculpt", text="Edit Mode", icon="EDITMODE_HLT").mode = "EDIT"
        box.label(text=f"Dependencies ({len(state.dependencies)}, locked):")
        box.template_list(
            "CHARACTER_DNA_UL_shape_key_dependencies", "", state, "dependencies", state, "dependencies_index", rows=4
        )
        row = box.row(align=True)
        row.scale_y = 1.4
        row.operator(f"{ToolInfo.NAME}.shape_key_commit", icon="CHECKMARK")
        row.operator(f"{ToolInfo.NAME}.shape_key_revert", icon="LOOP_BACK")


classes = (CHARACTER_DNA_UL_shape_keys, CHARACTER_DNA_UL_shape_key_dependencies, CHARACTER_DNA_PT_shape_key_editor)
