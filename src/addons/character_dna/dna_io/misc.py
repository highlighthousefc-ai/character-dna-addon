# standard library imports
import logging
import math

from pathlib import Path
from typing import Any, Literal

# third party imports
import bpy
import numpy as np

from mathutils import Matrix

# local imports
from ..constants import SHAPE_KEY_BASIS_NAME, ComponentType
from ..dna_core import shape_key_name
from ..typing import *  # noqa: F403
from ..utilities import (
    exclude_rig_instance_evaluation,
    get_addon_window_manager_properties,
    switch_to_object_mode,
)


logger = logging.getLogger(__name__)

FileFormat = Literal["binary", "json"]
DataLayer = Literal[
    "Descriptor",
    "Definition",
    "Behavior",
    "Geometry",
    "GeometryWithoutBlendShapes",
    "MachineLearnedBehavior",
    "RBFBehavior",
    "JointBehaviorMetadata",
    "TwistSwingBehavior",
    "All",
]


def release_dna_handle(handle: Any) -> None:
    """Destroy an OpenRigLogic handle now instead of waiting for garbage collection.

    ``dna``/``riglogic`` factory objects are caller-owned C++ allocations. The Python
    bindings only call ``destroy`` from the wrapper's ``__del__``, so dropping the last
    reference eventually frees them -- but not deterministically, which matters on Windows
    where a live reader/writer keeps the ``.dna`` file handle open.

    Args:
        handle: A wrapper returned by :func:`get_dna_reader` / :func:`get_dna_writer`, or
            any other RAII-wrapped binding object. ``None`` and raw SWIG proxies are ignored.
    """
    if handle is None:
        return

    instance = getattr(handle, "_instance", None)
    if instance is None:
        return

    try:
        type(handle).destroy(instance)
    except Exception as error:
        logger.warning(f"Failed to destroy {type(handle).__name__}: {error}")
    handle._instance = None  # noqa: SLF001
    # The wrapper keeps its constructor arguments alive, which is what owns the stream a
    # reader/writer was built on. Dropping them here releases those in child-before-parent order.
    if getattr(handle, "_args", None):
        handle._args = ()  # noqa: SLF001


def get_dna_reader(
    file_path: Path,
    file_format: FileFormat = "binary",
    data_layer: DataLayer = "All",
    memory_resource: "dna.MemoryResource | None" = None,
) -> "dna.BinaryStreamReader":
    from ..bindings import dna  # type: ignore[reportAttributeAccessIssue]

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File '{file_path}' does not exist.")

    mode = dna.OpenMode_Binary
    # if file_format.lower() == 'json':
    #     mode = dna.OpenMode_Text  # noqa: ERA001

    # Construct via the class rather than `.create()`: the constructor returns the binding's
    # owning wrapper, which destroys the C++ object on release and keeps the stream alive for
    # exactly as long as the reader needs it. `.create()` returns a raw pointer that leaks.
    stream = dna.FileStream(path=str(file_path), accessMode=dna.AccessMode_Read, openMode=mode, memRes=memory_resource)

    # Explicitly enforce the coordinate frame our importer assumes (Maya Y-up:
    # x=left, y=up, z=front) instead of trusting whatever system the incoming DNA
    # was authored in. With the Transform policy the reader converts any source
    # system to this frame at load time (a no-op when the data is already Maya
    # Y-up), so the downstream manual +90deg X rotation and scale handling stay
    # valid even for DNAs exported with a different coordinate system. Units are
    # not touched here (the Configuration transform does not convert cm<->m or
    # degrees<->radians); those are still adapted from getTranslationUnit /
    # getRotationUnit by the importer.
    coordinate_system = dna.CoordinateSystem()
    coordinate_system.x = dna.Direction_left
    coordinate_system.y = dna.Direction_up
    coordinate_system.z = dna.Direction_front

    config = dna.Configuration()
    config.layer = getattr(dna, f"DataLayer_{data_layer}")
    config.unknownLayerPolicy = dna.UnknownLayerPolicy_Preserve
    config.coordinateSystemTransformPolicy = dna.CoordinateSystemTransformPolicy_Transform
    config.coordinateSystem = coordinate_system

    if file_format.lower() == "json":
        # The JSON reader has no Configuration overload, so it cannot enforce the
        # coordinate system on load; JSON DNAs are expected to already be Maya Y-up.
        reader = dna.JSONStreamReader(stream, memory_resource)
    elif file_format.lower() == "binary":
        reader = dna.BinaryStreamReader(stream, config, memory_resource)
    else:
        raise ValueError(f"Invalid file format '{file_format}'. Must be 'binary' or 'json'.")

    try:
        reader.read()
    except IndexError as error:
        logger.debug(f"Error reading DNA file '{file_path}': {error}")
        release_dna_handle(reader)
        return None  # pyright: ignore[reportReturnType]

    if not dna.Status.isOk():
        status = dna.Status.get()
        release_dna_handle(reader)
        raise RuntimeError(f'Error loading DNA: {status.message} from "{file_path}"')
    return reader


def get_dna_writer(file_path: Path, file_format: FileFormat = "binary") -> "dna.BinaryStreamWriter":
    from ..bindings import dna  # type: ignore[reportAttributeAccessIssue]

    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    mode = dna.OpenMode_Binary
    # if file_format.lower() == 'json':
    #     mode = dna.OpenMode_Text  # noqa: ERA001

    # See get_dna_reader: the constructor form owns the C++ object and, critically for the
    # writer, keeps the stream alive until `write()` is called and the writer is released.
    stream = dna.FileStream(
        path=str(file_path),
        accessMode=dna.AccessMode_Write,
        openMode=mode,
    )
    if file_format.lower() == "json":
        writer = dna.JSONStreamWriter(stream)
    elif file_format.lower() == "binary":
        writer = dna.BinaryStreamWriter(stream)
    else:
        raise ValueError(f"Invalid file format '{file_format}'. Must be 'binary' or 'json'.")

    return writer


def get_dna_component_type(file_path: Path) -> ComponentType | None:
    """
    Determine the DNA component type based on the mesh names in the DNA file.

    Mesh names are the strongest signal, but some DNA files (for example clothing
    or custom body assets) do not include "head" or "body" in their mesh names. In
    that case we fall back to the joint names: head DNA files contain facial joints
    (``FACIAL_*``) while body DNA files are skinned to the body skeleton only.
    """
    component_type = None
    dna_reader = get_dna_reader(file_path=file_path, file_format="binary", data_layer="Definition")
    if dna_reader:
        for index in range(dna_reader.getMeshCount()):
            mesh_name = dna_reader.getMeshName(index)
            if "head" in mesh_name.lower():
                component_type = "head"
            elif "body" in mesh_name.lower():
                component_type = "body"

        # Fall back to joint names when the mesh names are inconclusive.
        if component_type is None and dna_reader.getJointCount() > 0:
            has_facial_joint = any(
                "facial" in dna_reader.getJointName(index).lower() for index in range(dna_reader.getJointCount())
            )
            component_type = "head" if has_facial_joint else "body"

        release_dna_handle(dna_reader)
    return component_type


@exclude_rig_instance_evaluation
def create_shape_key(
    index: int,
    mesh_index: int,
    mesh_object: bpy.types.Object,
    reader: "dna.BinaryStreamReader",
    name: str,
    prefix: str = "",
    is_neutral: bool = False,
    linear_modifier: float = 1.0,
) -> bpy.types.ShapeKey | None:
    if not mesh_object:
        logger.error(f"Mesh object not found for shape key {name}. Skipping creation.")
        return None
    if not mesh_object.data or not isinstance(mesh_object.data, bpy.types.Mesh):
        logger.error(
            f"Object '{mesh_object.name}' has no mesh data in the blender scene. Skipping shape key creation..."
        )
        return None
    if not mesh_object.data.shape_keys:
        mesh_object.shape_key_add(name=SHAPE_KEY_BASIS_NAME, from_mix=False)

    window_manager_properties = get_addon_window_manager_properties()
    window_manager_properties.progress_mesh_name = mesh_object.name
    # create the new key block on the shape key
    logger.debug(f"Creating shape key {name}")
    shape_key_name = f"{prefix}{name}"

    switch_to_object_mode()

    # remove any pre-existing key block with this name so re-imports overwrite cleanly
    shape_key = mesh_object.data.shape_keys.key_blocks.get(shape_key_name)  # type: ignore[attr-defined]
    if shape_key:
        shape_key.lock_shape = False
        mesh_object.shape_key_remove(shape_key)

    shape_key_block = mesh_object.shape_key_add(name=shape_key_name, from_mix=False)
    # zero the influence so the imported key is stored but not applied on top of the
    # basis (the delta geometry is written directly to the key block's data, so this
    # only affects the value slider, not the stored shape)
    shape_key_block.value = 0.0

    # Import the deltas if the shape key is not supposed to be neutral
    if not is_neutral:
        apply_blend_shape_deltas(
            mesh_object=mesh_object,
            shape_key_block=shape_key_block,
            reader=reader,
            mesh_index=mesh_index,
            index=index,
            name=name,
            linear_modifier=linear_modifier,
        )

    shape_key_block.lock_shape = True

    return shape_key_block


def blend_shape_target_deltas(
    reader: "dna.BinaryStreamReader",
    mesh_index: int,
    index: int,
    linear_modifier: float = 1.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return one blend shape target's sparse ``(vertex_indices, deltas)`` in Blender space.

    The DNA stores deltas Y-up; the imported mesh is rotated +90 degrees about X to Z-up, so
    the deltas get the same rotation (and the same linear unit scale as the vertex positions).
    ``vertex_indices`` are DNA position indices, which are the Blender vertex indices of an
    imported mesh (``DNAImporter`` creates and sorts its vertices in DNA position order).
    """
    vertex_indices = np.asarray(reader.getBlendShapeTargetVertexIndices(mesh_index, index), dtype=np.int64)
    deltas = np.empty((len(vertex_indices), 3), dtype=np.float32)
    if len(vertex_indices):
        deltas[:, 0] = reader.getBlendShapeTargetDeltaXs(mesh_index, index)
        deltas[:, 1] = reader.getBlendShapeTargetDeltaYs(mesh_index, index)
        deltas[:, 2] = reader.getBlendShapeTargetDeltaZs(mesh_index, index)

    # DNA is Y-up, Blender is Z-up, so we need to rotate the deltas
    rotation = np.array(Matrix.Rotation(math.radians(90), 4, "X").to_3x3(), dtype=np.float32)
    return vertex_indices, (deltas * linear_modifier) @ rotation.T


def _scatter_deltas(
    shape_key_block: bpy.types.ShapeKey,
    base_flat: np.ndarray,
    vertex_indices: np.ndarray,
    rotated: np.ndarray,
    mesh_object: bpy.types.Object,
    name: str,
) -> None:
    """Write ``base + deltas`` into ``shape_key_block`` with one ``foreach_set``."""
    base = base_flat.reshape(-1, 3)
    vertex_count = len(base)

    # guard against vertex indices that no longer exist on the base mesh
    valid = vertex_indices < vertex_count
    if not valid.all():
        logger.warning(
            f'Some vertex indices are missing for shape key "{name}". '
            f'Were they deleted on the base mesh "{mesh_object.name}"?'
        )
        vertex_indices = vertex_indices[valid]
        rotated = rotated[valid]

    # the new vertex layout is the original vertex layout with the deltas from the dna applied
    new_flat = base_flat.copy()
    new = new_flat.reshape(-1, 3)
    new[vertex_indices] = base[vertex_indices] + rotated
    shape_key_block.data.foreach_set("co", new_flat)


def apply_blend_shape_deltas(
    mesh_object: bpy.types.Object,
    shape_key_block: bpy.types.ShapeKey,
    reader: "dna.BinaryStreamReader",
    mesh_index: int,
    index: int,
    name: str,
    linear_modifier: float = 1.0,
) -> None:
    """Apply a DNA blend shape target's deltas onto ``shape_key_block`` using
    vectorized numpy + ``foreach_get``/``foreach_set`` for speed.

    Reads the basis (reference key) coordinates once, rotates the sparse deltas
    from DNA's Y-up space into Blender's Z-up space, scatters them onto the
    affected vertices, and writes the whole shape key in a single bulk call.
    """
    vertex_indices, rotated = blend_shape_target_deltas(reader, mesh_index, index, linear_modifier)
    if len(vertex_indices) == 0:
        return

    reference_key = mesh_object.data.shape_keys.reference_key  # type: ignore[attr-defined]
    base_flat = np.empty(len(reference_key.data) * 3, dtype=np.float32)
    reference_key.data.foreach_get("co", base_flat)
    _scatter_deltas(shape_key_block, base_flat, vertex_indices, rotated, mesh_object, name)


def import_blend_shapes(
    mesh_object: bpy.types.Object,
    reader: "dna.BinaryStreamReader",
    mesh_index: int,
    mesh_name: str,
    linear_modifier: float = 1.0,
) -> int:
    """Create every blend shape target of one DNA mesh as a shape key on ``mesh_object``.

    Existing shape keys are cleared first, so a re-import replaces them instead of stacking
    duplicates. Each key is named by :func:`dna_core.shape_key_name` (the name the runtime,
    exporter and calibrator look blocks up by), holds the basis plus the target's deltas, starts
    at value 0 and is locked so a stray edit cannot change what the rig evaluates.

    Returns the number of shape keys created (the basis not included).
    """
    if not isinstance(getattr(mesh_object, "data", None), bpy.types.Mesh):
        logger.error(f'"{getattr(mesh_object, "name", mesh_object)}" has no mesh data. Skipping its blend shapes.')
        return 0

    count = reader.getBlendShapeTargetCount(mesh_index)
    if count == 0:
        return 0

    mesh_object.shape_key_clear()
    basis = mesh_object.shape_key_add(name=SHAPE_KEY_BASIS_NAME, from_mix=False)
    basis.id_data.name = mesh_object.name

    base_flat = np.empty(len(mesh_object.data.vertices) * 3, dtype=np.float32)
    basis.data.foreach_get("co", base_flat)

    for index in range(count):
        channel_index = reader.getBlendShapeChannelIndex(mesh_index, index)
        name = shape_key_name(mesh_name, reader.getBlendShapeChannelName(channel_index))
        block = mesh_object.shape_key_add(name=name, from_mix=False)
        block.value = 0.0
        vertex_indices, rotated = blend_shape_target_deltas(reader, mesh_index, index, linear_modifier)
        if len(vertex_indices):
            _scatter_deltas(block, base_flat, vertex_indices, rotated, mesh_object, name)
        block.lock_shape = True

    return count
