"""Grooms (Slice 2): the export's Alembic grooms as Blender hair curves attached to the head.

Each ``alembic`` component of the manifest becomes one Curves object:

* read with the numpy Ogawa reader (``dna_core.alembic`` / ``dna_core.grooms``), guide strands
  dropped, file (x, y, z) cm -> Blender (x, -y, z) / 100 m, radius = width / 2 (negative widths 0);
* linear (poly) curves, as the file says;
* attached to the head's LOD0 mesh by the root UVs: the Curves' ``surface`` / ``surface_uv_map`` and
  ``surface_uv_coordinate``, plus a Geometry Nodes modifier running **Deform Curves on Surface**, so
  the strands follow the skin (shape keys and bones). The head gets **Add Rest Position**, which
  that node needs;
* a Principled Hair BSDF material from the manifest's ``hair_color`` (melanin parametrisation);
* peach fuzz is hidden in the viewport (``hide_viewport``) but renders.

Physics stays off: Unreal's per-group simulation settings aren't used here.
"""

import logging
import time

from dataclasses import dataclass, field
from pathlib import Path

import bpy
import numpy as np

from ..constants import ToolInfo
from ..dna_core import assembly as manifest, grooms as groom_data
from ..dna_core.alembic import AlembicError
from ..dna_core.assembly import TextureStatus, with_status
from . import materials


logger = logging.getLogger(__name__)

ATTACH_GROUP = "Character DNA Attach To Surface"
GROOM_PROPERTY = f"{ToolInfo.NAME}_groom"  # on each groom object: its region (scalp, brows, lashes, ...)
FUZZ_REGION = "fuzz"
LASHES_REGION = "lashes"
HAIR_IOR = 1.55  # the Principled Hair BSDF default


@dataclass
class GroomResult:
    name: str
    region: str
    file: Path
    object_name: str = ""
    strands_in_file: int = 0
    guides_removed: int = 0
    strands: int = 0
    points: int = 0
    negative_widths: int = 0
    repaired: str = ""
    seconds: float = 0.0
    surface: str = ""
    widths: str = "file widths"
    error: str = ""
    unmapped_hair_color: list[str] = field(default_factory=list)
    statuses: list[TextureStatus] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error

    def line(self) -> str:
        if self.error:
            return f"  {self.name} ({self.region}): FAILED: {self.error}"
        hidden = " (hidden in the viewport, renders)" if self.region == FUZZ_REGION else ""
        return (
            f"  {self.name} ({self.region}): {self.strands} strands, {self.points} points "
            f"({self.strands_in_file} in the file - {self.guides_removed} guides), "
            f"{self.widths}, {self.negative_widths} negative widths clamped, {self.repaired}, "
            f"on {self.surface or 'no surface'}, "
            f"{self.seconds:.2f} s{hidden}"
        )


def attach_group() -> bpy.types.GeometryNodeTree:
    """Geometry Nodes: Deform Curves on Surface (follows the Curves' surface and UV map)."""
    group = bpy.data.node_groups.get(ATTACH_GROUP)
    if group is not None:
        return group
    group = bpy.data.node_groups.new(ATTACH_GROUP, "GeometryNodeTree")
    group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    inputs = group.nodes.new("NodeGroupInput")
    deform = group.nodes.new("GeometryNodeDeformCurvesOnSurface")
    outputs = group.nodes.new("NodeGroupOutput")
    deform.location, outputs.location = (200, 0), (400, 0)
    group.links.new(inputs.outputs[0], deform.inputs[0])
    group.links.new(deform.outputs[0], outputs.inputs[0])
    return group


def build_curves(name: str, groom: groom_data.BlenderGroom) -> bpy.types.Curves:
    curves = bpy.data.hair_curves.new(name)
    curves.add_curves(groom.counts.tolist())
    curves.set_types(type="POLY")
    curves.attributes["position"].data.foreach_set("vector", groom.positions.ravel())
    radius = curves.attributes.get("radius") or curves.attributes.new("radius", "FLOAT", "POINT")
    radius.data.foreach_set("value", groom.radius)
    if groom.root_uv is not None:
        uv = curves.attributes.new("surface_uv_coordinate", "FLOAT2", "CURVE")
        uv.data.foreach_set("vector", groom.root_uv.ravel())
    if groom.color is not None:
        color = curves.attributes.new("groom_color", "FLOAT_VECTOR", "POINT")
        color.data.foreach_set("vector", groom.color.ravel())
    return curves


def hair_material(source: manifest.Material, entries: list[TextureStatus], prefix: str) -> tuple:
    """A Principled Hair BSDF material from the manifest's hair colour. Returns (material, statuses, unmapped)."""
    name = f"{prefix}_{source.display_name or source.name}"
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if material.node_tree is None:  # Blender 4.x builds the tree only with use_nodes
        material.use_nodes = True
    tree = material.node_tree
    tree.nodes.clear()
    # Cycles: the physically based melanin model, as exported.
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.target = "CYCLES"
    hair = tree.nodes.new("ShaderNodeBsdfHairPrincipled")
    hair.model = "CHIANG"
    hair.parametrization = "MELANIN"
    hair.label = "Hair (melanin, as exported)"
    hair.location, output.location = (0, 0), (300, 0)
    tree.links.new(hair.outputs[0], output.inputs["Surface"])
    values, unmapped = groom_data.hair_shader_inputs(source.hair_color)
    for socket, value in values.items():
        hair.inputs[socket].default_value = value
    color = source.hair_color.get("color")
    if color is not None and len(color) >= 3:
        # EEVEE (and so Material Preview) has no hair shading yet: Blender 5.1 renders a Principled Hair
        # BSDF there as a plain diffuse of its Color input, ignoring melanin and highlights
        # (gpu_shader_material_hair.glsl; FINDINGS "Slice 2"). So EEVEE gets a Principled BSDF with
        # Unreal's resolved colour (linear RGB), the exported roughness and hair's IOR: the specular
        # highlight is what makes near-black hair read neutral, as in Cycles.
        rgba = (*map(float, color[:3]), 1.0)
        material.diffuse_color = rgba
        eevee_output = tree.nodes.new("ShaderNodeOutputMaterial")
        eevee_output.target = "EEVEE"
        eevee = tree.nodes.new("ShaderNodeBsdfPrincipled")
        eevee.label = "EEVEE: Unreal's resolved colour"
        eevee.inputs["Base Color"].default_value = rgba
        eevee.inputs["IOR"].default_value = HAIR_IOR
        if "Roughness" in values:
            eevee.inputs["Roughness"].default_value = values["Roughness"]
        eevee.location, eevee_output.location = (0, -400), (300, -400)
        tree.links.new(eevee.outputs[0], eevee_output.inputs["Surface"])
    statuses = []
    textures = []
    for entry in entries:
        texture = source.texture(entry.role)
        if entry.status == "loaded" and texture is not None:
            textures.append(texture)
            statuses.append(with_status(entry, "loaded", f"{name}: {entry.detail}"))
        else:
            statuses.append(entry)
    frame = None
    for index, texture in enumerate(textures):
        if frame is None:
            frame = tree.nodes.new("NodeFrame")
            frame.label = materials.UNCONNECTED_FRAME
        node = tree.nodes.new("ShaderNodeTexImage")
        node.label = texture.role
        node.image = materials.load_image(texture, prefix)
        node.location = (-400, -300 * index)
        node.parent = frame
    return material, statuses, unmapped


def import_groom(
    component: manifest.Component,
    assembly: manifest.Assembly,
    head: bpy.types.Object | None,
    instance_name: str,
    entries: list[TextureStatus],
    match_unreal_widths: bool = False,
) -> GroomResult:
    """Import one groom component. Errors end up in ``GroomResult.error``, never raised.

    ``match_unreal_widths`` uses the component's Unreal width override and root / tip scale instead
    of the file's per-point widths.
    """
    result = GroomResult(name=component.name, region=component.region, file=component.path)
    start = time.perf_counter()
    try:
        groom = groom_data.read_groom(component.path)
    except (OSError, AlembicError) as error:
        result.error = str(error)
        result.statuses = [with_status(e, "failed", f"groom not imported: {error}") for e in entries]
        return result
    settings = component.groom
    if match_unreal_widths and settings.get("width"):
        converted = groom_data.to_blender(
            groom,
            width=float(settings["width"]),
            root_scale=float(settings.get("root_scale", 1.0)),
            tip_scale=float(settings.get("tip_scale", 1.0)),
        )
        result.widths = (
            f"Unreal width {float(settings['width']):g} cm, root x{float(settings.get('root_scale', 1.0)):g}"
            f" -> tip x{float(settings.get('tip_scale', 1.0)):g}"
        )
    else:
        converted = groom_data.to_blender(groom)
    result.strands_in_file = groom.strands
    result.guides_removed = converted.guides_removed
    result.strands = len(converted.counts)
    result.points = len(converted.positions)
    result.negative_widths = converted.negative_widths
    result.repaired = f"repaired {converted.duplicate_points} duplicate and {converted.spike_points} spike points" + (
        f", dropped {converted.strands_dropped} degenerate strands" if converted.strands_dropped else ""
    )

    name = f"{instance_name}_{component.name}"
    if head is not None:  # positions are in the head's space (the head sits at the origin on import)
        inverse = np.array(head.matrix_world.inverted(), dtype=np.float32)
        converted.positions = converted.positions @ inverse[:3, :3].T + inverse[:3, 3]
    curves = build_curves(name, converted)
    scene_object = bpy.data.objects.new(name, curves)
    scene_object[GROOM_PROPERTY] = component.region or component.name
    collections = head.users_collection if head is not None else ()
    (collections[0] if collections else bpy.context.scene.collection).objects.link(scene_object)

    if head is not None and converted.root_uv is not None:
        scene_object.parent = head
        head.add_rest_position_attribute = True  # Deform Curves on Surface needs it
        curves.surface = head
        uv_maps = head.data.uv_layers
        curves.surface_uv_map = (uv_maps.active or uv_maps[0]).name if uv_maps else ""
        modifier = scene_object.modifiers.new("Attach To Surface", "NODES")
        modifier.node_group = attach_group()
        result.surface = head.name

    source = assembly.materials.get(component.materials[0]) if component.materials else None
    if source is not None:
        material, result.statuses, result.unmapped_hair_color = hair_material(source, entries, instance_name)
        curves.materials.append(material)
    if component.region == FUZZ_REGION:
        scene_object.hide_viewport = True
        scene_object.hide_render = False
    result.object_name = scene_object.name
    result.seconds = time.perf_counter() - start
    return result
