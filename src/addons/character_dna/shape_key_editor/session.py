"""The Shape Key Editor's edit session: activate a key's dependencies, sculpt, commit or revert.

One session at a time. Its state lives in ``Scene.character_dna_shape_key_editor`` (so the UI can
show it and undo restores it), and the DNA is written only by :func:`commit`, never on an undo step.

Coordinates: a Blender shape key holds absolute rest-space positions in metres, Z-up; the DNA holds
per-vertex deltas in its own unit, Y-up. ``delta_dna = rotate(-90 deg about X, key - basis) / unit``
and back again with the inverse, exactly as import and export already convert them.
"""

import logging

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import bpy
import numpy as np

from .. import dna_core, utilities
from ..constants import SCALE_FACTOR, SHAPE_KEY_BASIS_NAME, ToolInfo
from ..dna_core import blend_shapes
from ..dna_core.psd import ControlGraph, NotActivatableError


logger = logging.getLogger(__name__)

# Dependencies weaker than this are not listed (they don't visibly change the face).
DEPENDENCY_THRESHOLD = 1e-3
# DNA Y-up -> Blender Z-up is +90 degrees about X: (x, y, z) -> (x, -z, y).
TO_BLENDER = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
TO_DNA = TO_BLENDER.T


class SessionError(RuntimeError):
    """An edit session can't start, continue or commit; the message is shown to the user."""


@dataclass(frozen=True)
class KeyInfo:
    """What the editor knows about one shape key of one LOD0 mesh."""

    channel: int
    target: int
    has_deltas: bool
    activatable: bool
    reason: str


# Per-DNA caches, keyed by (path, modification time) so a commit invalidates them.
_graphs: dict[tuple[str, float], ControlGraph] = {}
_key_infos: dict[tuple[str, float, str], dict[str, KeyInfo]] = {}


def state(context: Any = None) -> Any:
    return getattr((context or bpy.context).scene, f"{ToolInfo.NAME}_shape_key_editor")


def _dna_path(instance: Any) -> Path:
    path = Path(bpy.path.abspath(instance.head_dna_file_path))
    if not path.is_file():
        raise SessionError(f"Head DNA file not found: {path}")
    return path


def _cache_key(path: Path) -> tuple[str, float]:
    return (str(path), path.stat().st_mtime)


def graph(instance: Any) -> ControlGraph:
    path = _dna_path(instance)
    key = _cache_key(path)
    if key not in _graphs:
        _graphs.clear()
        reader = dna_core.load(path)
        try:
            _graphs[key] = ControlGraph(reader)
        finally:
            blend_shapes.release(reader)
    return _graphs[key]


def key_infos(instance: Any, dna_mesh_name: str) -> dict[str, KeyInfo]:
    """Shape key name -> :class:`KeyInfo` for one LOD0 mesh of the character's head DNA."""
    path = _dna_path(instance)
    key = (*_cache_key(path), dna_mesh_name)
    if key not in _key_infos:
        graph_ = graph(instance)
        reader = dna_core.load(path)
        try:
            mesh = blend_shapes.mesh_index(reader, dna_mesh_name)
            infos = {}
            for target in range(reader.getBlendShapeTargetCount(mesh)):
                channel = reader.getBlendShapeChannelIndex(mesh, target)
                name = dna_core.shape_key_name(dna_mesh_name, graph_.channel_names[channel])
                try:
                    graph_.activation(channel)
                    activatable, reason = True, ""
                except NotActivatableError as error:
                    activatable, reason = False, str(error)
                has_deltas = len(reader.getBlendShapeTargetVertexIndices(mesh, target)) > 0
                infos[name] = KeyInfo(channel, target, has_deltas, activatable, reason)
        finally:
            blend_shapes.release(reader)
        _key_infos.clear()
        _key_infos[key] = infos
    return _key_infos[key]


@dataclass(frozen=True)
class DnaInfo:
    """The few DNA facts the editor needs, read from the file (not the character's cached reader,
    which Blender's undo handlers release)."""

    unit: float  # Blender metres per DNA unit
    lod0_meshes: tuple[str, ...]


_dna_infos: dict[tuple[str, float], DnaInfo] = {}


def dna_info(instance: Any) -> DnaInfo:
    path = _dna_path(instance)
    key = _cache_key(path)
    if key not in _dna_infos:
        dna = dna_core._bindings.dna_module()  # noqa: SLF001
        reader = dna_core.load(path, layer="Definition")
        try:
            unit = 1 / SCALE_FACTOR if reader.getTranslationUnit() == dna.TranslationUnit_cm else 1.0
            meshes = tuple(reader.getMeshName(index) for index in reader.getMeshIndicesForLOD(0))
        finally:
            blend_shapes.release(reader)
        _dna_infos.clear()
        _dna_infos[key] = DnaInfo(unit, meshes)
    return _dna_infos[key]


def editable_meshes(instance: Any) -> list[tuple[str, bpy.types.Object]]:
    """``(dna mesh name, object)`` for every imported LOD0 head mesh that has shape keys."""
    meshes = []
    for dna_mesh_name in dna_info(instance).lod0_meshes:
        mesh_object = bpy.data.objects.get(f"{instance.name}_{dna_mesh_name}")
        if mesh_object and mesh_object.type == "MESH" and mesh_object.data.shape_keys:
            meshes.append((dna_mesh_name, mesh_object))
    return meshes


def _unit(instance: Any) -> float:
    return dna_info(instance).unit


def rig_instance(name: str) -> Any:
    for scene in bpy.data.scenes:
        instance = getattr(scene, ToolInfo.NAME).rig_instance_list.get(name)
        if instance is not None:
            return instance
    raise SessionError(f'Character "{name}" is no longer in the file')


def _coordinates(block: bpy.types.ShapeKey) -> np.ndarray:
    values = np.empty(len(block.data) * 3, dtype=np.float32)
    block.data.foreach_get("co", values)
    return values.reshape(-1, 3).astype(np.float64)


def _object_mode(mesh_object: bpy.types.Object) -> None:
    """Leave Sculpt/Edit mode so the key's data is written back before it is read or replaced."""
    if bpy.context.mode != "OBJECT":
        with bpy.context.temp_override(active_object=mesh_object, object=mesh_object):
            bpy.ops.object.mode_set(mode="OBJECT")


def active_instance(context: Any = None) -> Any:
    session = state(context)
    instance = utilities.get_active_rig_instance()
    if session.active and (instance is None or instance.name != session.instance_name):
        raise SessionError(f'Finish editing "{session.key_name}" on "{session.instance_name}" first')
    return instance


def _edited_block(session: Any) -> tuple[bpy.types.Object, bpy.types.ShapeKey]:
    mesh_object = bpy.data.objects.get(session.object_name)
    block = mesh_object.data.shape_keys.key_blocks.get(session.key_name) if mesh_object else None
    if block is None:
        raise SessionError(f'Shape key "{session.key_name}" is no longer in the scene')
    return mesh_object, block


# --------------------------------------------------------------------------------------------
# Session lifecycle
# --------------------------------------------------------------------------------------------
def start(context: Any, instance: Any, mesh_object: bpy.types.Object, key_name: str) -> None:
    session = state(context)
    if session.active:
        raise SessionError(f'Commit or revert "{session.key_name}" first')
    dna_mesh_name = utilities.remove_instance_prefix(mesh_object.name, instance.name)
    info = key_infos(instance, dna_mesh_name).get(key_name)
    if info is None:
        raise SessionError(f'"{key_name}" is not a blend shape of {dna_mesh_name} in the DNA')
    if not info.activatable:
        raise SessionError(info.reason)
    block = mesh_object.data.shape_keys.key_blocks.get(key_name)
    if block is None:
        raise SessionError(f'Shape key "{key_name}" is not in the scene. Import the shape keys first.')

    graph_ = graph(instance)
    activation = graph_.activation(info.channel)
    weights = _engine().preview_raw(instance, activation)
    if weights is None:
        raise SessionError("The character isn't evaluating. Turn on evaluation and Force Evaluate, then try again.")

    session.active = True
    session.instance_name = instance.name
    session.object_name = mesh_object.name
    session.mesh_name = dna_mesh_name
    session.key_name = key_name
    session.channel = info.channel
    session.target = info.target
    session.controls = ", ".join(graph_.name(control).removeprefix("CTRL_expressions.") for control in activation)
    session.status = ""
    session.dependencies.clear()
    for channel in sorted(range(len(weights)), key=lambda index: -weights[index]):
        if channel == info.channel or weights[channel] < DEPENDENCY_THRESHOLD:
            continue
        item = session.dependencies.add()
        item.channel = channel
        item.name = graph_.channel_names[channel]
        item.weight = weights[channel]

    for key_block in mesh_object.data.shape_keys.key_blocks:
        key_block.lock_shape = key_block != block
    mesh_object.active_shape_key_index = list(mesh_object.data.shape_keys.key_blocks).index(block)
    mesh_object.show_only_shape_key = False
    mesh_object.use_shape_key_edit_mode = True
    logger.info(f"Editing {key_name}: controls {session.controls}; {len(session.dependencies)} dependencies")


def refresh_preview(context: Any = None) -> None:
    """Republish the session's pose, hiding the dependencies whose eye is off."""
    session = state(context)
    if not session.active:
        return
    instance = rig_instance(session.instance_name)
    overrides = {item.channel: 0.0 for item in session.dependencies if not item.visible}
    _engine().preview_raw(instance, graph(instance).activation(session.channel), overrides)


def _end(context: Any, instance: Any, mesh_object: bpy.types.Object | None) -> None:
    session = state(context)
    if instance is not None:
        _engine().clear_preview(instance)
    if mesh_object is not None and mesh_object.data.shape_keys:
        for key_block in mesh_object.data.shape_keys.key_blocks:
            key_block.lock_shape = key_block.name != SHAPE_KEY_BASIS_NAME
    session.active = False
    session.dependencies.clear()


def edited_deltas(context: Any = None) -> np.ndarray:
    """The edited key's full delta array, converted to DNA space (``float64 (vertices, 3)``)."""
    session = state(context)
    mesh_object, block = _edited_block(session)
    _object_mode(mesh_object)
    basis = _coordinates(block.relative_key)
    instance = rig_instance(session.instance_name)
    return ((_coordinates(block) - basis) @ TO_DNA.T) / _unit(instance)


def write_key_from_dna(instance: Any, mesh_object: bpy.types.Object, key_name: str, target: int) -> None:
    """Set a shape key to exactly what the DNA stores for it (basis + converted deltas)."""
    block = mesh_object.data.shape_keys.key_blocks[key_name]
    dna_mesh_name = utilities.remove_instance_prefix(mesh_object.name, instance.name)
    reader = dna_core.load(_dna_path(instance))
    try:
        indices, deltas = blend_shapes.target_deltas(reader, blend_shapes.mesh_index(reader, dna_mesh_name), target)
    finally:
        blend_shapes.release(reader)
    basis = _coordinates(block.relative_key)
    positions = basis.copy()
    positions[indices] += (deltas.astype(np.float64) * _unit(instance)) @ TO_BLENDER.T
    block.data.foreach_set("co", positions.astype(np.float32).ravel())
    mesh_object.data.update()


def commit(context: Any) -> dict[str, Any]:
    """Write the edited key into the DNA in place (after a backup) and rebuild the character."""
    session = state(context)
    if not session.active:
        raise SessionError("Nothing is being edited")
    instance = rig_instance(session.instance_name)
    mesh_object, _block = _edited_block(session)
    edited = edited_deltas(context)
    path = _dna_path(instance)

    reader = dna_core.load(path)
    try:
        mesh = blend_shapes.mesh_index(reader, session.mesh_name)
        if reader.getVertexPositionCount(mesh) != len(edited):
            raise SessionError(
                f"{session.mesh_name} has {len(edited)} vertices in Blender but "
                f"{reader.getVertexPositionCount(mesh)} in the DNA; the topology must match to commit"
            )
        original = blend_shapes.target_deltas(reader, mesh, session.target)
    finally:
        blend_shapes.release(reader)
    indices, deltas = blend_shapes.merge(original, edited)
    stored = blend_shapes.dense(*original, len(edited))
    changed = int((np.abs(edited - stored).max(axis=1) > blend_shapes.UNCHANGED_TOLERANCE).sum())

    from ..runtime import controller

    key_name, target = session.key_name, session.target
    _end(context, instance, mesh_object)
    # The character's own reader and runtime hold the file (a lock on Windows): release them,
    # replace the file, then rebuild everything from the new DNA.
    instance.destroy_head()
    backup = blend_shapes.commit_target(path, mesh, target, indices, deltas)
    controller.rebuild(instance)
    write_key_from_dna(instance, mesh_object, key_name, target)
    result = {"key": key_name, "changed_vertices": changed, "backup": str(backup), "target_vertices": len(indices)}
    channel_name = graph(instance).channel_names[session.channel]
    session.status = f"Committed {channel_name}: {changed} vertices changed. Backup: {backup.name}"
    session.last_backup = str(backup)
    logger.info(session.status)
    return result


def revert(context: Any) -> None:
    """Discard the edit: put the key back to what the DNA stores and end the session."""
    session = state(context)
    if not session.active:
        return
    instance = rig_instance(session.instance_name)
    mesh_object, _block = _edited_block(session)
    _object_mode(mesh_object)
    key_name, target = session.key_name, session.target
    write_key_from_dna(instance, mesh_object, key_name, target)
    _end(context, instance, mesh_object)
    session.status = f"Reverted {graph(instance).channel_names[session.channel]}"


def abandon(context: Any = None) -> None:
    """End a session whose character or key disappeared, without touching any data."""
    session = state(context)
    try:
        instance = rig_instance(session.instance_name)
    except SessionError:
        instance = None
    _end(context, instance, bpy.data.objects.get(session.object_name))


def _engine() -> Any:
    from ..runtime import engine

    return engine
