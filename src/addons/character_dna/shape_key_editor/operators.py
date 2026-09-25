"""Operators of the Shape Key Editor: Edit, Sculpt / Edit Mode, Commit, Revert."""

import logging

from typing import Any

import bpy

from .. import utilities
from ..constants import ToolInfo
from . import session


logger = logging.getLogger(__name__)


def _report_errors(operator: bpy.types.Operator, function: Any, *args: Any) -> set[str]:
    try:
        function(*args)
    except session.SessionError as error:
        operator.report({"ERROR"}, str(error))
        return {"CANCELLED"}
    return {"FINISHED"}


def _enter_mode(context: Any, mesh_object: bpy.types.Object, mode: str) -> None:
    """Make the edited mesh the only active, selected object and switch it to ``mode``."""
    if context.mode != "OBJECT" and context.active_object is not None:
        bpy.ops.object.mode_set(mode="OBJECT")
    for obj in context.view_layer.objects:
        obj.select_set(False)
    mesh_object.hide_set(False)
    mesh_object.select_set(True)
    context.view_layer.objects.active = mesh_object
    bpy.ops.object.mode_set(mode=mode)


class CHARACTER_DNA_OT_shape_key_edit(bpy.types.Operator):
    """Edit this shape key: switch on everything it depends on, then sculpt it against the real face"""

    bl_idname = f"{ToolInfo.NAME}.shape_key_edit"
    bl_label = "Edit Shape Key"
    bl_options = {"REGISTER", "UNDO"}

    key_name: bpy.props.StringProperty(options={"SKIP_SAVE"})  # pyright: ignore[reportInvalidTypeForm]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return not session.state(context).active and utilities.dependencies_are_valid()

    def execute(self, context: Any) -> set[str]:
        state = session.state(context)
        mesh_object = bpy.data.objects.get(state.mesh)
        instance = utilities.get_active_rig_instance()
        if instance is None or mesh_object is None:
            self.report({"ERROR"}, "Select a character and a mesh with imported shape keys")
            return {"CANCELLED"}
        return _report_errors(self, session.start, context, instance, mesh_object, self.key_name)


class CHARACTER_DNA_OT_shape_key_sculpt(bpy.types.Operator):
    """Sculpt the shape key being edited. Only that key changes; its dependencies stay locked"""

    bl_idname = f"{ToolInfo.NAME}.shape_key_sculpt"
    bl_label = "Sculpt"
    bl_options = {"REGISTER", "UNDO"}

    mode: bpy.props.EnumProperty(
        items=[("SCULPT", "Sculpt", "Sculpt mode"), ("EDIT", "Edit Mode", "Edit mode")],
        default="SCULPT",
        options={"SKIP_SAVE"},
    )  # pyright: ignore[reportInvalidTypeForm]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return session.state(context).active

    def execute(self, context: Any) -> set[str]:
        state = session.state(context)
        mesh_object = bpy.data.objects.get(state.object_name)
        if mesh_object is None:
            self.report({"ERROR"}, f'"{state.object_name}" is no longer in the scene')
            return {"CANCELLED"}
        _enter_mode(context, mesh_object, self.mode)
        return {"FINISHED"}


class CHARACTER_DNA_OT_shape_key_commit(bpy.types.Operator):
    """Write the edited shape key into the head DNA file. The previous file is kept in a backups folder next to it"""

    bl_idname = f"{ToolInfo.NAME}.shape_key_commit"
    bl_label = "Commit"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return session.state(context).active

    def execute(self, context: Any) -> set[str]:
        try:
            result = session.commit(context)
        except (session.SessionError, OSError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, session.state(context).status)
        logger.info(f"Shape key commit: {result}")
        return {"FINISHED"}


class CHARACTER_DNA_OT_shape_key_revert(bpy.types.Operator):
    """Discard the edit and put the shape key back to what the DNA stores"""

    bl_idname = f"{ToolInfo.NAME}.shape_key_revert"
    bl_label = "Revert"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return session.state(context).active

    def execute(self, context: Any) -> set[str]:
        return _report_errors(self, session.revert, context)


class CHARACTER_DNA_OT_shape_key_mirror(bpy.types.Operator):
    """Mirror your edit of this shape key onto its left/right counterpart (e.g. _L onto _R). Nothing is saved until Commit, which then writes both keys; Revert discards both"""  # noqa: E501

    bl_idname = f"{ToolInfo.NAME}.shape_key_mirror"
    bl_label = "Mirror to Opposite"
    bl_options = {"REGISTER", "UNDO"}

    whole_shape: bpy.props.BoolProperty(
        name="Whole Shape",
        description=(
            "Replace the counterpart with the exact mirror image of this whole shape (makes the pair symmetric). "
            "Off: add only what you changed, mirrored, keeping the counterpart's own asymmetric shape"
        ),
        default=False,
    )  # pyright: ignore[reportInvalidTypeForm]

    @classmethod
    def poll(cls, context: Any) -> bool:
        return session.state(context).active

    def execute(self, context: Any) -> set[str]:
        result = _report_errors(self, session.mirror_to_opposite, context, self.whole_shape)
        if result == {"FINISHED"}:
            self.report({"INFO"}, session.state(context).status)
        return result


class CHARACTER_DNA_OT_shape_key_flip(bpy.types.Operator):
    """Flip the edited shape key in place: its left side becomes its right. Nothing is saved until Commit"""

    bl_idname = f"{ToolInfo.NAME}.shape_key_flip"
    bl_label = "Flip"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return session.state(context).active

    def execute(self, context: Any) -> set[str]:
        result = _report_errors(self, session.flip, context)
        if result == {"FINISHED"}:
            self.report({"INFO"}, session.state(context).status)
        return result


class CHARACTER_DNA_OT_shape_key_abandon(bpy.types.Operator):
    """End an edit whose character or shape key was removed, without changing anything"""

    bl_idname = f"{ToolInfo.NAME}.shape_key_abandon"
    bl_label = "End Edit"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return session.state(context).active

    def execute(self, context: Any) -> set[str]:
        session.abandon(context)
        return {"FINISHED"}


classes = (
    CHARACTER_DNA_OT_shape_key_edit,
    CHARACTER_DNA_OT_shape_key_sculpt,
    CHARACTER_DNA_OT_shape_key_commit,
    CHARACTER_DNA_OT_shape_key_revert,
    CHARACTER_DNA_OT_shape_key_mirror,
    CHARACTER_DNA_OT_shape_key_flip,
    CHARACTER_DNA_OT_shape_key_abandon,
)
