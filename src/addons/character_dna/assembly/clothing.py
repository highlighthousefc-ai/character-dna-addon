"""Clothing (Slice 3): the export's outfit FBX, bound to the body rig, with fabric materials.

The outfit (``Clothing/outfits.fbx``) is one skinned mesh with its own 341-bone skeleton rooted at
``pelvis``: the MetaHuman body skeleton, so every bone exists in our body rig under the same name and
at the same rest position (0.008 mm at most on the real export; FINDINGS "Slice 3"). Importing it:

* Blender's FBX importer reads it (centimetres, object scale 0.01); the mesh's world transform is
  baked into its data, and it is re-parented to the body rig with its Armature modifier pointing
  at our body rig. The FBX's own armature and empties are deleted.
* Material slots nobody uses are dropped. The export lists LOD1-3 copies of both garment materials
  (``..._2`` to ``..._7``) but only LOD0 has faces, so LOD0 is all that's kept.
* Each garment material is built from the manifest's ``fabric`` settings and textures by role.
* The body faces under the clothes (``Geometry/body.json``) get a face attribute, and a Geometry Nodes
  modifier after the Armature deletes them, so skin never pokes through. Toggle it with the modifier's
  visibility (the Clothing panel does both viewport and render).

No cloth physics.
"""

import logging
import re
import time

from dataclasses import dataclass, field

import bpy
import numpy as np

from ..constants import ASSEMBLY_CLOTHING_PROPERTY, UV_MAP_NAME, ToolInfo
from ..dna_core import assembly as manifest, clothing as clothing_data
from ..dna_core.assembly import TextureStatus, with_status
from . import materials


logger = logging.getLogger(__name__)

UNDER_CLOTHES_ATTRIBUTE = f"{ToolInfo.NAME}_under_clothes"
HIDE_GROUP = "Character DNA Hide Under Clothes"
HIDE_MODIFIER = "Hide Under Clothes"
CLOTHING_PROPERTY = ASSEMBLY_CLOTHING_PROPERTY
REST_TOLERANCE = 0.001  # m: a bone further than this from our body rig's rest position is reported
FABRIC_ROUGHNESS = 0.8  # not in the export; cotton-like
MACRO_VARIATION_AMOUNT = 0.25  # how much the (0.5-centred) macro variation map shades the colour


@dataclass
class ClothingResult:
    name: str
    objects: list[str] = field(default_factory=list)
    slots_kept: list[str] = field(default_factory=list)
    slots_dropped: list[str] = field(default_factory=list)
    bones: int = 0
    missing_bones: list[str] = field(default_factory=list)
    rest_offset: float = 0.0  # m, the largest rest-position difference to our body rig
    seconds: float = 0.0
    error: str = ""
    statuses: list[TextureStatus] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error

    def line(self) -> str:
        if self.error:
            return f"  {self.name}: FAILED: {self.error}"
        missing = f", {len(self.missing_bones)} bones missing from the body rig" if self.missing_bones else ""
        return (
            f"  {self.name}: {', '.join(self.objects)}; LOD0 slots {self.slots_kept}, dropped empty "
            f"{len(self.slots_dropped)}; bound to the body rig ({self.bones} bones, rest within "
            f"{self.rest_offset * 1000:.3f} mm){missing}; {self.seconds:.2f} s"
        )


# --- hiding the body under the clothes ---------------------------------------------------------------


def hide_group() -> bpy.types.GeometryNodeTree:
    """Geometry Nodes: delete the faces whose ``UNDER_CLOTHES_ATTRIBUTE`` is set."""
    group = bpy.data.node_groups.get(HIDE_GROUP)
    if group is not None:
        return group
    group = bpy.data.node_groups.new(HIDE_GROUP, "GeometryNodeTree")
    group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    inputs, outputs = group.nodes.new("NodeGroupInput"), group.nodes.new("NodeGroupOutput")
    attribute = group.nodes.new("GeometryNodeInputNamedAttribute")
    attribute.data_type = "BOOLEAN"
    attribute.inputs["Name"].default_value = UNDER_CLOTHES_ATTRIBUTE
    delete = group.nodes.new("GeometryNodeDeleteGeometry")
    delete.domain = "FACE"
    group.links.new(inputs.outputs[0], delete.inputs["Geometry"])
    group.links.new(attribute.outputs["Attribute"], delete.inputs["Selection"])
    group.links.new(delete.outputs[0], outputs.inputs[0])
    for x, node in enumerate((inputs, attribute, delete, outputs)):
        node.location = (220 * x, 0)
    return group


def hide_under_clothes(body: bpy.types.Object, hidden: np.ndarray) -> int:
    """Mark the covered faces and add the (last) modifier that removes them. Returns the face count."""
    mesh = body.data
    if len(mesh.polygons) != len(hidden):
        raise clothing_data.GeometryError(
            f"{body.name} has {len(mesh.polygons)} faces but the export's body geometry has {len(hidden)}"
        )
    attribute = mesh.attributes.get(UNDER_CLOTHES_ATTRIBUTE) or mesh.attributes.new(
        UNDER_CLOTHES_ATTRIBUTE, "BOOLEAN", "FACE"
    )
    attribute.data.foreach_set("value", hidden.astype(bool))
    modifier = body.modifiers.get(HIDE_MODIFIER) or body.modifiers.new(HIDE_MODIFIER, "NODES")
    modifier.node_group = hide_group()
    return int(hidden.sum())


def grow_under_clothes(
    body: bpy.types.Object, garments: list[bpy.types.Object], hidden: np.ndarray, rings: int = 2, depth: float = 0.03
) -> np.ndarray:
    """Widen the covered faces by up to ``rings`` rings of neighbours that the clothes cover at rest.

    The export's mask fits the rest pose: posed (an arm raised), corrective bones bulge skin up to about
    a millimetre past a sleeve's edge (FINDINGS "Slice 3"). A neighbour is added only when a ray from
    its skin outward hits a garment within ``depth``: the garment covers it, so hiding it never opens a
    gap, while the skin past a sleeve or leg opening (open air outward) stays.
    """
    from mathutils.bvhtree import BVHTree

    mesh = body.data
    trees = []
    for garment in garments:
        vertices = [garment.matrix_world @ v.co for v in garment.data.vertices]
        trees.append(BVHTree.FromPolygons(vertices, [tuple(p.vertices) for p in garment.data.polygons]))
    loops = np.empty(len(mesh.loops), np.int32)
    mesh.loops.foreach_get("vertex_index", loops)
    starts = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    totals = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("loop_total", totals)
    face_of_loop = np.repeat(np.arange(len(mesh.polygons)), totals)
    hidden = hidden.copy()
    matrix, rotation = body.matrix_world, body.matrix_world.to_3x3()
    for _ in range(rings):
        border_vertices = np.zeros(len(mesh.vertices), bool)
        border_vertices[loops[hidden[face_of_loop]]] = True
        candidates = np.unique(face_of_loop[border_vertices[loops]])
        candidates = candidates[~hidden[candidates]]
        added = []
        for face in candidates:
            polygon = mesh.polygons[int(face)]
            origin = matrix @ polygon.center
            direction = (rotation @ polygon.normal).normalized()
            if any(tree.ray_cast(origin + direction * 1e-4, direction, depth)[0] is not None for tree in trees):
                added.append(face)
        if not added:
            break
        hidden[np.array(added)] = True
    return hidden


def set_body_hiding(bodies: list[bpy.types.Object], enabled: bool) -> None:
    for body in bodies:
        modifier = body.modifiers.get(HIDE_MODIFIER)
        if modifier is not None:
            modifier.show_viewport = modifier.show_render = enabled


def body_hiding_enabled(bodies: list[bpy.types.Object]) -> bool:
    modifiers = [b.modifiers.get(HIDE_MODIFIER) for b in bodies]
    return any(m is not None and m.show_viewport for m in modifiers)


# --- fabric --------------------------------------------------------------------------------------------


class _Fabric:
    """Builds one garment material: nodes left to right, textures by role (``wire_fabric``)."""

    def __init__(self, material: bpy.types.Material, source: manifest.Material, prefix: str):
        if material.node_tree is None:
            material.use_nodes = True
        self.tree = material.node_tree
        self.tree.nodes.clear()
        self.nodes, self.links = self.tree.nodes, self.tree.links
        self.source, self.prefix = source, prefix
        self.settings = clothing_data.fabric_settings(source.fabric)
        self.done: dict[str, str] = {}
        output = self.nodes.new("ShaderNodeOutputMaterial")
        self.bsdf = self.nodes.new("ShaderNodeBsdfPrincipled")
        output.location, self.bsdf.location = (400, 0), (100, 0)
        self.links.new(self.bsdf.outputs[0], output.inputs["Surface"])
        self.bsdf.inputs["Roughness"].default_value = FABRIC_ROUGHNESS
        self.uv = self.nodes.new("ShaderNodeUVMap")
        self.uv.uv_map = UV_MAP_NAME
        self.uv.location = (-1600, 0)

    def node(self, kind: str, x: float, y: float, **settings: object) -> bpy.types.Node:
        node = self.nodes.new(kind)
        node.location = (x, y)
        for key, value in settings.items():
            setattr(node, key, value)
        return node

    def image(self, role: str, x: float, y: float, tiling: float | None = None) -> bpy.types.Node | None:
        texture = self.source.texture(role)
        if texture is None or not texture.exists:
            return None
        node = self.node("ShaderNodeTexImage", x, y, label=role)
        node.image = materials.load_image(texture, self.prefix)
        vector = self.uv.outputs["UV"]
        if tiling is not None:
            mapping = self.node("ShaderNodeMapping", x - 200, y)
            mapping.inputs["Scale"].default_value = (tiling, tiling, 1.0)
            self.links.new(vector, mapping.inputs["Vector"])
            vector = mapping.outputs["Vector"]
        self.links.new(vector, node.inputs["Vector"])
        return node

    def mix(self, kind: str, a: object, b: object, factor: object, x: float, y: float) -> bpy.types.NodeSocket:
        node = self.node("ShaderNodeMix", x, y, data_type="RGBA", blend_type=kind)
        sockets = (
            next(s for s in node.inputs if s.name == "Factor" and s.type == "VALUE"),
            next(s for s in node.inputs if s.name == "A" and s.type == "RGBA"),
            next(s for s in node.inputs if s.name == "B" and s.type == "RGBA"),
        )
        for socket, value in zip(sockets, (factor, a, b), strict=True):
            if isinstance(value, bpy.types.NodeSocket):
                self.links.new(value, socket)
            else:
                socket.default_value = value
        return next(s for s in node.outputs if s.name == "Result" and s.type == "RGBA")

    def color(self) -> None:
        """Fabric colour, stitches in the stitch colour, AO (red channel), tiled macro variation."""
        settings = self.settings
        color: object = (*settings["color"], 1.0)
        stitch = self.image("stitch_mask", -1100, 300)
        if stitch is not None:
            color = self.mix("MIX", color, (*settings["stitch_color"], 1.0), stitch.outputs["Color"], -700, 300)
            self.done["stitch_mask"] = "Base Color (stitch colour where the mask is set)"
        ao = self.image("ambient_occlusion", -1100, 0)
        if ao is not None:
            red = self.node("ShaderNodeSeparateColor", -850, 0)
            self.links.new(ao.outputs["Color"], red.inputs["Color"])
            color = self.mix("MULTIPLY", color, red.outputs["Red"], 1.0, -500, 150)
            self.done["ambient_occlusion"] = "Base Color (multiplies; red channel)"
        macro = self.image("macro_variation", -1100, -300, tiling=settings["macro_scale"])
        if macro is not None:
            doubled = self.node("ShaderNodeMath", -800, -300, operation="MULTIPLY")
            doubled.inputs[1].default_value = 2.0
            self.links.new(macro.outputs["Color"], doubled.inputs[0])
            color = self.mix("MULTIPLY", color, doubled.outputs[0], MACRO_VARIATION_AMOUNT, -300, 0)
            self.done["macro_variation"] = (
                f"Base Color (x{settings['macro_scale']:g} tiling, {MACRO_VARIATION_AMOUNT:g} strength)"
            )
        if isinstance(color, bpy.types.NodeSocket):
            self.links.new(color, self.bsdf.inputs["Base Color"])
        else:
            self.bsdf.inputs["Base Color"].default_value = color

    def normal(self) -> None:
        """Garment normal plus the tiled micro normal (DirectX style), then micro height as a bump."""
        settings = self.settings
        normal = self.image("normal", -1100, -700)
        micro = self.image("micro_normal", -1100, -1000, tiling=settings["micro_scale"])
        color = normal.outputs["Color"] if normal is not None else None
        if normal is not None and micro is not None:
            blend = self.node("ShaderNodeGroup", -800, -800)
            blend.node_tree = materials.normal_detail_group()
            self.links.new(normal.outputs["Color"], blend.inputs["Base"])
            self.links.new(micro.outputs["Color"], blend.inputs["Detail"])
            blend.inputs["Strength"].default_value = settings["micro_normal_strength"]
            color = blend.outputs["Color"]
            self.done["micro_normal"] = (
                f"Normal (x{settings['micro_scale']:g} tiling, strength {settings['micro_normal_strength']:g})"
            )
        vector = self.directx_normal(color, settings["normal_strength"]) if color is not None else None
        if normal is not None:
            self.done["normal"] = f"Normal (DirectX, strength {settings['normal_strength']:g})"
        height = self.image("micro_height", -1100, -1300, tiling=settings["micro_scale"])
        if height is not None:
            bump = self.node("ShaderNodeBump", -150, -1000)
            bump.inputs["Strength"].default_value = 0.2
            bump.inputs["Distance"].default_value = 0.0005
            self.links.new(height.outputs["Color"], bump.inputs["Height"])
            if vector is not None:
                self.links.new(vector, bump.inputs["Normal"])
            vector = bump.outputs["Normal"]
            self.done["micro_height"] = f"Normal (bump, x{settings['micro_scale']:g} tiling)"
        if vector is not None:
            self.links.new(vector, self.bsdf.inputs["Normal"])

    def directx_normal(self, color: bpy.types.NodeSocket, strength: float) -> bpy.types.NodeSocket:
        split = self.node("ShaderNodeSeparateXYZ", -600, -700)
        flip = self.node("ShaderNodeMath", -450, -700, operation="SUBTRACT")
        flip.inputs[0].default_value = 1.0
        combine = self.node("ShaderNodeCombineXYZ", -300, -700)
        normal_map = self.node("ShaderNodeNormalMap", -150, -700, uv_map=UV_MAP_NAME)
        normal_map.inputs["Strength"].default_value = strength
        self.links.new(color, split.inputs[0])
        self.links.new(split.outputs["X"], combine.inputs["X"])
        self.links.new(split.outputs["Y"], flip.inputs[1])
        self.links.new(flip.outputs[0], combine.inputs["Y"])
        self.links.new(split.outputs["Z"], combine.inputs["Z"])
        self.links.new(combine.outputs[0], normal_map.inputs["Color"])
        return normal_map.outputs["Normal"]


def wire_fabric(material: bpy.types.Material, source: manifest.Material, prefix: str) -> dict[str, str]:
    """Build a garment material from the manifest's fabric settings and textures. Returns {role: detail}."""
    fabric = _Fabric(material, source, prefix)
    fabric.color()
    fabric.normal()
    return fabric.done


# --- the outfit ----------------------------------------------------------------------------------------


def _drop_unused_slots(mesh: bpy.types.Mesh) -> tuple[list[str], list[str]]:
    indices = np.empty(len(mesh.polygons), np.int32)
    mesh.polygons.foreach_get("material_index", indices)
    used = sorted(set(indices.tolist()))
    kept = [mesh.materials[i] for i in used]
    dropped = [m.name for i, m in enumerate(mesh.materials) if i not in used and m is not None]
    remap = np.zeros(max(len(mesh.materials), 1), np.int32)
    for new, old in enumerate(used):
        remap[old] = new
    mesh.materials.clear()
    for material in kept:
        mesh.materials.append(material)
    mesh.polygons.foreach_set("material_index", remap[indices])
    return [m.name for m in kept if m is not None], dropped


def _manifest_material(assembly: manifest.Assembly, component: manifest.Component, name: str):  # noqa: ANN202
    name = re.sub(r"\.\d{3}$", "", name)  # Blender's duplicate suffix (a re-import, an existing name)
    for material_name in component.materials:
        material = assembly.materials.get(material_name)
        if material is not None and name in (material.display_name, material.slot, material.name):
            return material
    return None


def _compare_skeletons(armatures: list[bpy.types.Object], body_rig: bpy.types.Object, result: ClothingResult) -> None:
    """Count the garment bones our body rig has, and how far their rest positions differ."""
    body_bones = {bone.name: bone for bone in body_rig.data.bones}
    for armature in armatures:
        for bone in armature.data.bones:
            ours = body_bones.get(bone.name)
            if ours is None:
                result.missing_bones.append(bone.name)
                continue
            result.bones += 1
            offset = (armature.matrix_world @ bone.head_local - body_rig.matrix_world @ ours.head_local).length
            result.rest_offset = max(result.rest_offset, offset)


def _bind(scene_object: bpy.types.Object, body_rig: bpy.types.Object, result: ClothingResult) -> None:
    """Bake the mesh's world transform into its data and skin it to our body rig."""
    world = scene_object.matrix_world.copy()
    scene_object.parent = None
    scene_object.data.transform(world)
    scene_object.matrix_world = body_rig.matrix_world.copy()  # identity on import
    scene_object.parent = body_rig
    scene_object.matrix_parent_inverse = body_rig.matrix_world.inverted()
    for modifier in list(scene_object.modifiers):
        if modifier.type == "ARMATURE":
            scene_object.modifiers.remove(modifier)
    scene_object.modifiers.new("Armature", "ARMATURE").object = body_rig
    missing = [g.name for g in scene_object.vertex_groups if g.name not in body_rig.data.bones]
    result.missing_bones.extend(name for name in missing if name not in result.missing_bones)


def import_outfit(
    component: manifest.Component,
    assembly: manifest.Assembly,
    body_rig: bpy.types.Object,
    instance_name: str,
    entries: list[TextureStatus],
) -> ClothingResult:
    """Import one FBX clothing component onto the body rig. Errors end up in ``error``, never raised."""
    result = ClothingResult(name=component.name)
    start = time.perf_counter()
    if not component.path.is_file():
        result.error = f"{component.path.name} not found"
        result.statuses = [with_status(e, "failed", f"clothing not imported: {result.error}") for e in entries]
        return result
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.fbx(filepath=str(component.path), use_anim=False)
    except (RuntimeError, AttributeError) as error:
        result.error = f"FBX import failed: {error}"
        result.statuses = [with_status(e, "failed", f"clothing not imported: {error}") for e in entries]
        return result
    new = [o for o in bpy.data.objects if o not in before]
    armatures = [o for o in new if o.type == "ARMATURE"]
    meshes = [o for o in new if o.type == "MESH"]
    _compare_skeletons(armatures, body_rig, result)
    collections = body_rig.users_collection
    target = collections[0] if collections else bpy.context.scene.collection
    by_material: dict[str, TextureStatus] = {}
    for index, scene_object in enumerate(meshes):
        _bind(scene_object, body_rig, result)
        kept, dropped = _drop_unused_slots(scene_object.data)
        result.slots_kept.extend(kept)
        result.slots_dropped.extend(dropped)
        scene_object.name = f"{instance_name}_{component.name}" + (f"_{index}" if index else "")
        scene_object[CLOTHING_PROPERTY] = component.name
        for collection in list(scene_object.users_collection):
            collection.objects.unlink(scene_object)
        target.objects.link(scene_object)
        for slot in scene_object.material_slots:
            source = _manifest_material(assembly, component, slot.material.name) if slot.material else None
            if source is None:
                continue
            slot.material.name = f"{instance_name}_{source.display_name or source.name}"
            done = wire_fabric(slot.material, source, instance_name)
            for entry in entries:
                if entry.material == source.name:
                    status = ("connected", done[entry.role]) if entry.role in done else ("loaded", entry.detail)
                    by_material[(entry.material, entry.role)] = with_status(entry, *status)
        result.objects.append(scene_object.name)
    for scene_object in new:
        if scene_object.type in ("ARMATURE", "EMPTY"):
            data = scene_object.data
            bpy.data.objects.remove(scene_object)
            if data is not None and data.users == 0:
                bpy.data.armatures.remove(data)
    result.statuses = [by_material.get((e.material, e.role), e) for e in entries]
    result.seconds = time.perf_counter() - start
    return result


# --- checking for skin through the clothes ---------------------------------------------------------------


def poke_through(body: bpy.types.Object, garments: list[bpy.types.Object], depth: float = 0.03) -> int:
    """Rendered body faces whose skin covers the outside of a garment: skin showing through the clothes.

    From each face of the evaluated body (after the hiding modifier, when on), a ray goes inward up to
    ``depth``. It counts when it hits a garment surface facing outward, the same way as the skin: the
    garment's visible side lies under the skin there. Hitting an inward-facing surface (a hem's inner
    layer, tucked a few mm under the skin at a sleeve or leg opening) is invisible and not counted.
    """
    from mathutils.bvhtree import BVHTree

    depsgraph = bpy.context.evaluated_depsgraph_get()
    trees = [BVHTree.FromObject(g, depsgraph) for g in garments]
    evaluated = body.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        count = 0
        matrix = evaluated.matrix_world
        rotation = matrix.to_3x3()
        for polygon in mesh.polygons:
            origin = matrix @ polygon.center
            direction = -(rotation @ polygon.normal).normalized()
            start = origin - direction * 1e-4
            for tree in trees:
                location, hit_normal, _, _ = tree.ray_cast(start, direction, depth)
                if location is not None and hit_normal.dot(-direction) > 0:
                    count += 1
                    break
        return count
    finally:
        evaluated.to_mesh_clear()
