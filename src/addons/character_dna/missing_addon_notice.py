"""A visible warning that a saved character needs this add-on to move.

Without the add-on nothing of it runs when a file opens: the rig's output drivers call a
function that no longer exists, so the face silently stays in its neutral pose and the face
board does nothing. The only thing that can warn then is data saved in the file itself.

So every character gets a small red text object beside its head. It is shown in the saved
file (``save_pre`` un-hides it, ``save_post`` hides it again) and hidden whenever the add-on is
running (after a file loads, and while the add-on is registered). Opening the file without the
add-on therefore shows the notice; opening it with the add-on never does.
"""

import contextlib
import logging
import math

from typing import Any

import bpy

from mathutils import Vector

from .constants import ToolInfo


logger = logging.getLogger(__name__)

MARKER = "character_dna_missing_addon_notice"
MATERIAL_NAME = "CharacterDNA_missing_addon_notice"
TEXT_SIZE = 0.014  # metres; readable above a MetaHuman head in the default front view
LINE_HEIGHT = 1.2  # Blender's default line spacing, in multiples of the text size
TEXT = (
    "Character DNA add-on is not enabled.\n"
    "'{name}' stays in its neutral pose\n"
    "and the face board does nothing.\n"
    "Install and enable the add-on,\n"
    "then reopen this file."
)


def notices() -> list[bpy.types.Object]:
    return [obj for obj in bpy.data.objects if MARKER in obj and not obj.library]


def _material() -> bpy.types.Material:
    material = bpy.data.materials.get(MATERIAL_NAME)
    if material is None:
        material = bpy.data.materials.new(MATERIAL_NAME)
        material.diffuse_color = (1.0, 0.05, 0.02, 1.0)  # solid-mode viewport colour
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        output = nodes.new("ShaderNodeOutputMaterial")
        emission = nodes.new("ShaderNodeEmission")
        emission.inputs[0].default_value = (1.0, 0.05, 0.02, 1.0)  # Color
        material.node_tree.links.new(emission.outputs[0], output.inputs[0])  # Surface
    return material


def _place(notice: bpy.types.Object, head_mesh: bpy.types.Object) -> None:
    """Stand the text up just above the head, facing the front view (-Y).

    Above, because the face board sits beside the head. The text's origin is its first line's
    baseline and the lines run downwards, so the block is lifted by its own height.
    """
    corners = [head_mesh.matrix_world @ Vector(corner) for corner in head_mesh.bound_box]
    low = Vector(min(corner[axis] for corner in corners) for axis in range(3))
    high = Vector(max(corner[axis] for corner in corners) for axis in range(3))
    lines = TEXT.count("\n") + 1
    notice.rotation_euler = (math.radians(90), 0.0, 0.0)
    notice.location = (low.x, low.y, high.z + 0.02 + (lines - 1) * LINE_HEIGHT * TEXT_SIZE)


def ensure(instance: Any) -> bpy.types.Object | None:
    """Create or refresh the notice for one character; ``None`` for linked or headless ones."""
    head_mesh = instance.head_mesh
    if head_mesh is None or head_mesh.library or instance.get("reference_mode") in {"LINK", "EDITABLE_LINK"}:
        return None

    notice = next((obj for obj in notices() if obj[MARKER] == instance.name), None)
    if notice is None:
        curve = bpy.data.curves.new(f"{instance.name}_missing_addon_notice", "FONT")
        notice = bpy.data.objects.new(curve.name, curve)
        notice[MARKER] = instance.name
        curve.size = TEXT_SIZE
        collection = bpy.data.collections.get(instance.name)
        (collection or bpy.context.scene.collection).objects.link(notice)
        notice.hide_select = True
        notice.hide_render = True
        notice.show_in_front = True
    notice.data.body = TEXT.format(name=instance.name)
    _place(notice, head_mesh)
    if not notice.data.materials:
        notice.data.materials.append(_material())
    return notice


def _instances() -> list[Any]:
    return [
        instance
        for scene in bpy.data.scenes
        for instance in getattr(scene, ToolInfo.NAME).rig_instance_list
        if not scene.library
    ]


def set_visible(visible: bool) -> None:
    for notice in notices():
        notice.hide_viewport = not visible


@bpy.app.handlers.persistent
def _before_save(*_args: Any) -> None:
    try:
        instances = _instances()
        names = {instance.name for instance in instances}
        for notice in notices():
            if notice[MARKER] not in names:  # its character was removed
                bpy.data.objects.remove(notice)
        for instance in instances:
            ensure(instance)
        set_visible(True)
    except Exception:  # a failed notice must never block saving the user's work
        logger.exception("Could not update the missing add-on notice")


@bpy.app.handlers.persistent
def _after_save(*_args: Any) -> None:
    set_visible(False)


@bpy.app.handlers.persistent
def _after_load(*_args: Any) -> None:
    set_visible(False)


HANDLERS = (
    (bpy.app.handlers.save_pre, _before_save),
    (bpy.app.handlers.save_post, _after_save),
    (bpy.app.handlers.load_post, _after_load),
)


def register() -> None:
    for handlers, handler in HANDLERS:
        if handler not in handlers:
            handlers.append(handler)
    # Enabled with a file already open. bpy.data is restricted during startup; load_post covers that.
    with contextlib.suppress(AttributeError):
        set_visible(False)


def unregister() -> None:
    for handlers, handler in HANDLERS:
        if handler in handlers:
            handlers.remove(handler)
    # The add-on is going away, so the characters stop evaluating. bpy.data is restricted on quit.
    with contextlib.suppress(AttributeError):
        set_visible(True)
