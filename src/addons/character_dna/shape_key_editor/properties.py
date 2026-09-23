"""Scene state of the Shape Key Editor: which key is being edited and what it depends on."""

from typing import Any

import bpy

from ..constants import ToolInfo


def _visibility_changed(_self: Any, context: Any) -> None:
    from . import session

    session.refresh_preview(context)


def _mesh_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    from .. import utilities
    from . import session

    instance = utilities.get_active_rig_instance()
    items = []
    if instance is not None and instance.head_dna_reader:
        for dna_mesh_name, mesh_object in session.editable_meshes(instance):
            count = len(mesh_object.data.shape_keys.key_blocks) - 1
            items.append((mesh_object.name, dna_mesh_name, f"{count} shape keys on {mesh_object.name}"))
    # Blender keeps a reference to dynamic enum items; hold them on the function.
    _mesh_items.items = items or [("", "No shape keys imported", "")]
    return _mesh_items.items


class ShapeKeyEditorDependency(bpy.types.PropertyGroup):
    channel: bpy.props.IntProperty()  # pyright: ignore[reportInvalidTypeForm]
    weight: bpy.props.FloatProperty()  # pyright: ignore[reportInvalidTypeForm]
    visible: bpy.props.BoolProperty(
        default=True,
        name="Show",
        description="Show this dependency's contribution while sculpting, to compare against it",
        update=_visibility_changed,
    )  # pyright: ignore[reportInvalidTypeForm]


class ShapeKeyEditorState(bpy.types.PropertyGroup):
    mesh: bpy.props.EnumProperty(
        name="Mesh",
        description="The LOD0 mesh whose shape keys are listed",
        items=_mesh_items,
    )  # pyright: ignore[reportInvalidTypeForm]
    list_index: bpy.props.IntProperty(default=0)  # pyright: ignore[reportInvalidTypeForm]

    active: bpy.props.BoolProperty(default=False)  # pyright: ignore[reportInvalidTypeForm]
    instance_name: bpy.props.StringProperty()  # pyright: ignore[reportInvalidTypeForm]
    object_name: bpy.props.StringProperty()  # pyright: ignore[reportInvalidTypeForm]
    mesh_name: bpy.props.StringProperty()  # pyright: ignore[reportInvalidTypeForm]
    key_name: bpy.props.StringProperty()  # pyright: ignore[reportInvalidTypeForm]
    channel: bpy.props.IntProperty(default=-1)  # pyright: ignore[reportInvalidTypeForm]
    target: bpy.props.IntProperty(default=-1)  # pyright: ignore[reportInvalidTypeForm]
    controls: bpy.props.StringProperty()  # pyright: ignore[reportInvalidTypeForm]
    dependencies: bpy.props.CollectionProperty(type=ShapeKeyEditorDependency)  # pyright: ignore[reportInvalidTypeForm]
    dependencies_index: bpy.props.IntProperty(default=0)  # pyright: ignore[reportInvalidTypeForm]
    status: bpy.props.StringProperty()  # pyright: ignore[reportInvalidTypeForm]
    last_backup: bpy.props.StringProperty()  # pyright: ignore[reportInvalidTypeForm]


classes = (ShapeKeyEditorDependency, ShapeKeyEditorState)
SCENE_PROPERTY = f"{ToolInfo.NAME}_shape_key_editor"


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)
    setattr(bpy.types.Scene, SCENE_PROPERTY, bpy.props.PointerProperty(type=ShapeKeyEditorState))


def unregister() -> None:
    if hasattr(bpy.types.Scene, SCENE_PROPERTY):
        delattr(bpy.types.Scene, SCENE_PROPERTY)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
