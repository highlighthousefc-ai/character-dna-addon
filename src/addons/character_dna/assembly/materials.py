"""Wire a character assembly's textures into the imported materials, by manifest role.

Every image comes from the manifest (``dna_core.assembly``): its path and its colour space. Nothing is
found by file name. The DNA importer has already built the materials from ``materials.blend``; this
module then:

* **head / body**: keeps the material and its Texture Logic node (the rig drives its wrinkle masks),
  sets the image of every node feeding a Texture Logic input from its role, and adds the maps the
  template lacks: SRMF (specular, roughness, metallic), scatter (subsurface) and the tiled detail
  normal.
* **eye_ball**: rebuilds the eye. The sclera map covers the eye's UVs, and the iris map is scaled
  into the iris disc at the UV centre, blended across the limbus. Veins multiply the sclera.
* **teeth**: rebuilds the image part of the teeth: colour and normal.

Normal maps from Unreal are DirectX style (green down; measured in FINDINGS), so they're flipped.
The Texture Logic node already does this for the head and body.

Roles the plan leaves unconnected get an image node with the right colour space, placed in a frame.
The tunable values (iris radius, detail tiling and so on) are labelled Value nodes.
"""

import logging

from collections.abc import Callable, Iterable
from pathlib import Path

import bpy

from ..constants import UV_MAP_NAME
from ..dna_core import assembly as manifest
from ..dna_core.assembly import TextureStatus, with_status


logger = logging.getLogger(__name__)

# Measured on a real export (FINDINGS "Character Assembly Slice 1"): the iris edge (0.59 cm from the
# eye's axis) sits at UV radius ~0.155; the sclera map is plain there.
IRIS_RADIUS = 0.155
LIMBUS_WIDTH = 0.012
# The detail normal is a small tiling pore map shared by head and body. Unreal's tiling isn't in the
# export; these are starting values, tunable in the material.
DETAIL_TILING = 16.0
DETAIL_STRENGTH = 0.35
# Subsurface scattering radius for skin in metres (Principled "Subsurface Scale").
SUBSURFACE_SCALE = 0.003
SUBSURFACE_RADIUS = (1.0, 0.35, 0.2)

NORMAL_DETAIL_GROUP = "Character DNA Normal Detail"
UNCONNECTED_FRAME = "Unconnected maps (see the assembly report)"

# Texture Logic input -> manifest role.
HEAD_LOGIC_ROLES = {
    "Color_MAIN": "base_color",
    "Color_CM1": "base_color_animated_cm1",
    "Color_CM2": "base_color_animated_cm2",
    "Color_CM3": "base_color_animated_cm3",
    "Normal_MAIN": "normal",
    "Normal_WM1": "normal_animated_wm1",
    "Normal_WM2": "normal_animated_wm2",
    "Normal_WM3": "normal_animated_wm3",
}
BODY_LOGIC_ROLES = {"Color_MAIN": "base_color", "Normal_MAIN": "normal"}

_COLOR_SPACE_FALLBACKS = {"sRGB": ("sRGB", "sRGB - Display"), "Non-Color": ("Non-Color", "Raw")}


class WiringError(RuntimeError):
    """The material doesn't have the nodes the wiring expects."""


def load_image(texture: manifest.Texture, prefix: str = "") -> bpy.types.Image:
    """Load (or reuse) the texture's image and set the manifest's colour space on it."""
    image = bpy.data.images.load(str(texture.path), check_existing=True)
    if prefix and not image.name.startswith(f"{prefix}_"):
        image.name = f"{prefix}_{Path(texture.path).name}"
    for name in _COLOR_SPACE_FALLBACKS[texture.color_space]:
        try:
            image.colorspace_settings.name = name
        except TypeError:
            continue
        break
    else:
        logger.warning(f'No "{texture.color_space}" colour space in this OCIO config for {image.name}')
    return image


def _socket(sockets: Iterable[bpy.types.NodeSocket], name: str, kind: str | None = None) -> bpy.types.NodeSocket:
    """A socket by name (and type, for nodes like Mix that repeat names across data types)."""
    for socket in sockets:
        if socket.name == name and (kind is None or socket.type == kind) and socket.enabled:
            return socket
    for socket in sockets:
        if socket.name == name and (kind is None or socket.type == kind):
            return socket
    raise WiringError(f'No socket "{name}"')


class _Builder:
    """Adds nodes to a material in columns, left of its Principled BSDF."""

    def __init__(self, material: bpy.types.Material, prefix: str):
        if not material.node_tree:
            raise WiringError(f'"{material.name}" has no node tree')
        self.material = material
        self.nodes = material.node_tree.nodes
        self.links = material.node_tree.links
        self.prefix = prefix
        self.principled = next((n for n in self.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if self.principled is None:
            raise WiringError(f'"{self.material.name}" has no Principled BSDF')
        self.origin = self.principled.location.copy()

    def add(self, kind: str, column: float, row: float, label: str = "", **settings: object) -> bpy.types.Node:
        node = self.nodes.new(kind)
        node.location = (self.origin.x - 300 * column, self.origin.y - 280 * row)
        if label:
            node.label = label
        for key, value in settings.items():
            setattr(node, key, value)
        return node

    def link(self, output: bpy.types.NodeSocket, input_: bpy.types.NodeSocket) -> None:
        self.links.new(output, input_)

    def image(self, texture: manifest.Texture, column: float, row: float) -> bpy.types.Node:
        node = self.add("ShaderNodeTexImage", column, row, label=texture.role)
        node.image = load_image(texture, self.prefix)
        return node

    def uv(self, column: float, row: float) -> bpy.types.Node:
        return self.add("ShaderNodeUVMap", column, row, uv_map=UV_MAP_NAME)

    def value(self, label: str, value: float, column: float, row: float) -> bpy.types.NodeSocket:
        node = self.add("ShaderNodeValue", column, row, label=label)
        node.outputs[0].default_value = value
        return node.outputs[0]

    def principled_input(self, name: str) -> bpy.types.NodeSocket:
        return _socket(self.principled.inputs, name)

    def directx_normal(self, color: bpy.types.NodeSocket, column: float, row: float) -> bpy.types.NodeSocket:
        """A tangent-space normal from a DirectX-style normal map colour (green flipped)."""
        separate = self.add("ShaderNodeSeparateXYZ", column + 2, row)
        flip = self.add("ShaderNodeMath", column + 1.5, row + 0.4, operation="SUBTRACT")
        flip.inputs[0].default_value = 1.0
        combine = self.add("ShaderNodeCombineXYZ", column + 1, row)
        normal_map = self.add("ShaderNodeNormalMap", column, row, space="TANGENT", uv_map=UV_MAP_NAME)
        self.link(color, separate.inputs[0])
        self.link(separate.outputs["X"], combine.inputs["X"])
        self.link(separate.outputs["Y"], flip.inputs[1])
        self.link(flip.outputs[0], combine.inputs["Y"])
        self.link(separate.outputs["Z"], combine.inputs["Z"])
        self.link(combine.outputs[0], normal_map.inputs["Color"])
        return normal_map.outputs["Normal"]

    def unconnected(self, textures: Iterable[manifest.Texture]) -> None:
        textures = list(textures)
        if not textures:
            return
        frame = self.add("NodeFrame", 9, -1.5, label=UNCONNECTED_FRAME)
        for index, texture in enumerate(textures):
            node = self.image(texture, 9, -1.5 + index)
            node.parent = frame


def normal_detail_group() -> bpy.types.ShaderNodeTree:
    """``Base`` + ``Detail`` (normal map colours, same convention) -> blended colour.

    Whiteout blend: add the detail's XY (scaled by ``Strength``) to the base's, keep the base's Z,
    renormalise. Works the same in DirectX and OpenGL conventions, since both inputs share one.
    """
    group = bpy.data.node_groups.get(NORMAL_DETAIL_GROUP)
    if group is not None:
        return group
    group = bpy.data.node_groups.new(NORMAL_DETAIL_GROUP, "ShaderNodeTree")
    group.interface.new_socket("Base", in_out="INPUT", socket_type="NodeSocketColor")
    group.interface.new_socket("Detail", in_out="INPUT", socket_type="NodeSocketColor")
    strength = group.interface.new_socket("Strength", in_out="INPUT", socket_type="NodeSocketFloat")
    strength.default_value = DETAIL_STRENGTH
    group.interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    nodes, links = group.nodes, group.links
    inputs = nodes.new("NodeGroupInput")
    outputs = nodes.new("NodeGroupOutput")

    def vector_math(operation: str, x: float) -> bpy.types.Node:
        node = nodes.new("ShaderNodeVectorMath")
        node.operation = operation
        node.location = (x, 0)
        return node

    def unpack(color: bpy.types.NodeSocket, x: float) -> bpy.types.NodeSocket:
        node = vector_math("MULTIPLY_ADD", x)
        links.new(color, node.inputs[0])
        node.inputs[1].default_value = (2.0, 2.0, 2.0)
        node.inputs[2].default_value = (-1.0, -1.0, -1.0)
        return node.outputs[0]

    base = unpack(inputs.outputs["Base"], 200)
    detail = unpack(inputs.outputs["Detail"], 200)
    xy_scale = nodes.new("ShaderNodeCombineXYZ")
    links.new(inputs.outputs["Strength"], xy_scale.inputs["X"])
    links.new(inputs.outputs["Strength"], xy_scale.inputs["Y"])
    scaled = vector_math("MULTIPLY", 400)
    links.new(detail, scaled.inputs[0])
    links.new(xy_scale.outputs[0], scaled.inputs[1])
    added = vector_math("ADD", 600)
    links.new(base, added.inputs[0])
    links.new(scaled.outputs[0], added.inputs[1])
    normalized = vector_math("NORMALIZE", 800)
    links.new(added.outputs[0], normalized.inputs[0])
    packed = vector_math("MULTIPLY_ADD", 1000)
    links.new(normalized.outputs[0], packed.inputs[0])
    packed.inputs[1].default_value = (0.5, 0.5, 0.5)
    packed.inputs[2].default_value = (0.5, 0.5, 0.5)
    links.new(packed.outputs[0], outputs.inputs["Color"])
    outputs.location = (1200, 0)
    inputs.location = (0, 0)
    return group


def wire_skin(
    material: bpy.types.Material,
    source: manifest.Material,
    roles: set[str],
    logic_node: bpy.types.Node | None,
    logic_roles: dict[str, str],
    prefix: str,
) -> dict[str, str]:
    """Head or body skin. Returns ``{role: detail}`` for each role connected."""
    if logic_node is None:
        raise WiringError(f'"{material.name}" has no Texture Logic node')
    build = _Builder(material, prefix)
    done: dict[str, str] = {}
    normal_image = None
    for socket_name, role in logic_roles.items():
        socket = logic_node.inputs.get(socket_name)
        if socket is None:
            raise WiringError(f'The Texture Logic node has no "{socket_name}" input')
        texture = source.texture(role)
        node = socket.links[0].from_node if socket.links else None
        if node is None or node.type != "TEX_IMAGE":
            node = build.add("ShaderNodeTexImage", 4, len(done))
            build.link(node.outputs["Color"], socket)
        if texture is None or role not in roles:
            node.image = None  # no guessing: an absent role stays empty (reported as missing)
            continue
        node.image = load_image(texture, prefix)
        node.label = role
        done[role] = f"Texture Logic {socket_name}"
        if role == "normal":
            normal_image = node

    detail = source.texture("detail_normal")
    if detail is not None and "detail_normal" in roles and normal_image is not None:
        uv = build.uv(7, 3)
        tiling = build.value("Detail Tiling", DETAIL_TILING, 7, 4)
        mapping = build.add("ShaderNodeMapping", 6, 3, vector_type="POINT")
        build.link(uv.outputs["UV"], mapping.inputs["Vector"])
        build.link(tiling, mapping.inputs["Scale"])
        detail_node = build.image(detail, 5, 3)
        build.link(mapping.outputs["Vector"], detail_node.inputs["Vector"])
        blend = build.add("ShaderNodeGroup", 3, 2.5, label="Normal + Detail")
        blend.node_tree = normal_detail_group()
        normal_socket = logic_node.inputs["Normal_MAIN"]
        for existing in list(normal_socket.links):
            build.links.remove(existing)
        build.link(normal_image.outputs["Color"], blend.inputs["Base"])
        build.link(detail_node.outputs["Color"], blend.inputs["Detail"])
        build.link(blend.outputs["Color"], normal_socket)
        done["detail_normal"] = "Texture Logic Normal_MAIN (tiled, blended into the normal)"

    srmf = source.texture("srmf")
    if srmf is not None and "srmf" in roles:
        node = build.image(srmf, 3, -1.5)
        separate = build.add("ShaderNodeSeparateColor", 1.5, -1.5)
        build.link(node.outputs["Color"], separate.inputs["Color"])
        build.link(separate.outputs["Red"], build.principled_input("Specular IOR Level"))
        build.link(separate.outputs["Green"], build.principled_input("Roughness"))
        build.link(separate.outputs["Blue"], build.principled_input("Metallic"))
        done["srmf"] = "Principled Specular IOR Level (R), Roughness (G), Metallic (B); A (probably fuzz) not connected"

    scatter = source.texture("scatter")
    if scatter is not None and "scatter" in roles:
        node = build.image(scatter, 3, -2.5)
        separate = build.add("ShaderNodeSeparateColor", 1.5, -2.5)
        build.link(node.outputs["Color"], separate.inputs["Color"])
        build.link(separate.outputs["Red"], build.principled_input("Subsurface Weight"))
        build.principled_input("Subsurface Scale").default_value = SUBSURFACE_SCALE
        build.principled_input("Subsurface Radius").default_value = SUBSURFACE_RADIUS
        done["scatter"] = "Principled Subsurface Weight"
    return done


def _clear_except_shader(build: _Builder) -> None:
    output = next((n for n in build.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if output is None:
        raise WiringError(f'"{build.material.name}" has no Material Output')
    for node in list(build.nodes):
        if node not in (output, build.principled):
            build.nodes.remove(node)
    for link in list(build.principled.inputs["Base Color"].links) + list(build.principled.inputs["Normal"].links):
        build.links.remove(link)
    if not build.principled.outputs["BSDF"].links:
        build.link(build.principled.outputs["BSDF"], output.inputs["Surface"])


def wire_eye(material: bpy.types.Material, source: manifest.Material, roles: set[str], prefix: str) -> dict[str, str]:
    """Rebuild an eyeball: sclera over the whole eye, the iris scaled into the disc at the UV centre."""
    build = _Builder(material, prefix)
    _clear_except_shader(build)
    uv = build.uv(10, 0)
    texture = {role: source.texture(role) for role in roles}
    radius = build.value("Iris Radius (UV)", IRIS_RADIUS, 10, 2)
    iris_uv = _iris_mapping(build, uv.outputs["UV"], radius)
    iris_mask = _iris_mask(build, uv.outputs["UV"], radius)

    def image(role: str, column: float, row: float, iris: bool) -> bpy.types.Node | None:
        if texture.get(role) is None:
            return None
        node = build.image(texture[role], column, row)
        build.link(iris_uv if iris else uv.outputs["UV"], node.inputs["Vector"])
        return node

    done = _eye_color(build, image, iris_mask)
    done.update(_eye_normal(build, image, iris_mask))
    return done


def _iris_mapping(build: _Builder, uv: bpy.types.NodeSocket, radius: bpy.types.NodeSocket) -> bpy.types.NodeSocket:
    """UVs for the iris map: its 0..1 square fills the disc of radius ``radius`` at the UV centre."""
    scale = build.add("ShaderNodeMath", 9, 2, operation="DIVIDE")
    scale.inputs[0].default_value = 0.5
    build.link(radius, scale.inputs[1])
    offset = build.add("ShaderNodeMath", 8, 2.5, operation="MULTIPLY_ADD")  # 0.5 - 0.5 * scale
    build.link(scale.outputs[0], offset.inputs[0])
    offset.inputs[1].default_value = -0.5
    offset.inputs[2].default_value = 0.5
    scale_xy = build.add("ShaderNodeCombineXYZ", 8, 1.5)
    offset_xy = build.add("ShaderNodeCombineXYZ", 7, 2.5)
    for axis in ("X", "Y"):
        build.link(scale.outputs[0], scale_xy.inputs[axis])
        build.link(offset.outputs[0], offset_xy.inputs[axis])
    iris_uv = build.add("ShaderNodeMapping", 7, 1.5, vector_type="POINT", label="Iris UV")
    build.link(uv, iris_uv.inputs["Vector"])
    build.link(scale_xy.outputs[0], iris_uv.inputs["Scale"])
    build.link(offset_xy.outputs[0], iris_uv.inputs["Location"])
    return iris_uv.outputs["Vector"]


def _iris_mask(build: _Builder, uv: bpy.types.NodeSocket, radius: bpy.types.NodeSocket) -> bpy.types.NodeSocket:
    """1 inside the iris, 0 on the sclera, smooth across the limbus."""
    centre = build.add("ShaderNodeVectorMath", 8, 4, operation="DISTANCE")
    build.link(uv, centre.inputs[0])
    centre.inputs[1].default_value = (0.5, 0.5, 0.0)
    width = build.value("Limbus Width (UV)", LIMBUS_WIDTH, 8, 5)
    low = build.add("ShaderNodeMath", 7, 5, operation="SUBTRACT")
    high = build.add("ShaderNodeMath", 7, 5.5, operation="ADD")
    for node in (low, high):
        build.link(radius, node.inputs[0])
        build.link(width, node.inputs[1])
    mask = build.add("ShaderNodeMapRange", 6, 4, interpolation_type="SMOOTHSTEP", label="Iris Mask")
    build.link(centre.outputs["Value"], mask.inputs["Value"])
    build.link(low.outputs[0], mask.inputs["From Min"])
    build.link(high.outputs[0], mask.inputs["From Max"])
    mask.inputs["To Min"].default_value = 1.0
    mask.inputs["To Max"].default_value = 0.0
    return mask.outputs["Result"]


def _eye_color(
    build: _Builder, image: Callable[..., bpy.types.Node | None], iris_mask: bpy.types.NodeSocket
) -> dict[str, str]:
    done: dict[str, str] = {}
    sclera = image("sclera_base_color", 5, 0, iris=False)
    iris = image("iris_base_color", 5, 1, iris=True)
    veins = image("veins", 5, -1, iris=False)
    color: bpy.types.NodeSocket | None = sclera.outputs["Color"] if sclera else None
    if sclera:
        done["sclera_base_color"] = "Principled Base Color (outside the iris)"
    if sclera and veins:
        multiply = build.add("ShaderNodeMix", 3, -0.5, data_type="RGBA", blend_type="MULTIPLY", label="Veins")
        _socket(multiply.inputs, "Factor", "VALUE").default_value = 1.0
        build.link(sclera.outputs["Color"], _socket(multiply.inputs, "A", "RGBA"))
        build.link(veins.outputs["Color"], _socket(multiply.inputs, "B", "RGBA"))
        color = _socket(multiply.outputs, "Result", "RGBA")
        done["veins"] = "Principled Base Color (multiplies the sclera)"
    if iris:
        done["iris_base_color"] = "Principled Base Color (inside the iris)"
        if color is None:
            color = iris.outputs["Color"]
        else:
            mix = build.add("ShaderNodeMix", 2, 0.5, data_type="RGBA", label="Sclera / Iris")
            build.link(iris_mask, _socket(mix.inputs, "Factor", "VALUE"))
            build.link(color, _socket(mix.inputs, "A", "RGBA"))
            build.link(iris.outputs["Color"], _socket(mix.inputs, "B", "RGBA"))
            color = _socket(mix.outputs, "Result", "RGBA")
    if color is not None:
        build.link(color, build.principled_input("Base Color"))
    return done


def _eye_normal(
    build: _Builder, image: Callable[..., bpy.types.Node | None], iris_mask: bpy.types.NodeSocket
) -> dict[str, str]:
    done: dict[str, str] = {}
    sclera_normal = image("sclera_normal", 5, 2.5, iris=False)
    iris_normal = image("iris_normal", 5, 3.5, iris=True)
    normal_color = None
    if sclera_normal and iris_normal:
        mix = build.add("ShaderNodeMix", 3, 3, data_type="RGBA", label="Sclera / Iris Normal")
        build.link(iris_mask, _socket(mix.inputs, "Factor", "VALUE"))
        build.link(sclera_normal.outputs["Color"], _socket(mix.inputs, "A", "RGBA"))
        build.link(iris_normal.outputs["Color"], _socket(mix.inputs, "B", "RGBA"))
        normal_color = _socket(mix.outputs, "Result", "RGBA")
    elif sclera_normal or iris_normal:
        normal_color = (sclera_normal or iris_normal).outputs["Color"]
    if normal_color is not None:
        build.link(build.directx_normal(normal_color, -1, 3), build.principled_input("Normal"))
        if sclera_normal:
            done["sclera_normal"] = "Principled Normal (outside the iris)"
        if iris_normal:
            done["iris_normal"] = "Principled Normal (inside the iris)"
    return done


def wire_teeth(material: bpy.types.Material, source: manifest.Material, roles: set[str], prefix: str) -> dict[str, str]:
    build = _Builder(material, prefix)
    _clear_except_shader(build)
    done: dict[str, str] = {}
    uv = build.uv(6, 0)
    color = source.texture("base_color")
    if color is not None and "base_color" in roles:
        node = build.image(color, 4, 0)
        build.link(uv.outputs["UV"], node.inputs["Vector"])
        build.link(node.outputs["Color"], build.principled_input("Base Color"))
        done["base_color"] = "Principled Base Color"
    normal = source.texture("normal")
    if normal is not None and "normal" in roles:
        node = build.image(normal, 5, 2)
        build.link(uv.outputs["UV"], node.inputs["Vector"])
        build.link(build.directx_normal(node.outputs["Color"], 0, 2), build.principled_input("Normal"))
        done["normal"] = "Principled Normal"
    return done


def wire_material(
    material: bpy.types.Material,
    source: manifest.Material,
    plan: list[TextureStatus],
    prefix: str,
    logic_node_for: Callable[[bpy.types.Material], bpy.types.Node | None] | None = None,
) -> list[TextureStatus]:
    """Carry out the plan for one material; returns the plan entries with what actually happened."""
    to_connect = {entry.role for entry in plan if entry.status == "connected"}
    to_load = [source.texture(entry.role) for entry in plan if entry.status == "loaded"]
    try:
        if source.type in ("head", "body"):
            logic_roles = HEAD_LOGIC_ROLES if source.type == "head" else BODY_LOGIC_ROLES
            logic_node = logic_node_for(material) if logic_node_for else None
            done = wire_skin(material, source, to_connect, logic_node, logic_roles, prefix)
        elif source.type == "eye_ball":
            done = wire_eye(material, source, to_connect, prefix)
        elif source.type == "teeth":
            done = wire_teeth(material, source, to_connect, prefix)
        else:
            done = {}
        _Builder(material, prefix).unconnected(texture for texture in to_load if texture is not None)
    except (WiringError, RuntimeError, KeyError) as error:
        logger.exception(f'Wiring "{material.name}" failed')
        return [
            with_status(entry, "failed", f"{material.name}: {error}")
            if entry.status in ("connected", "loaded")
            else entry
            for entry in plan
        ]
    return [_outcome(entry, done, material.name) for entry in plan]


def _outcome(entry: TextureStatus, done: dict[str, str], material_name: str) -> TextureStatus:
    if entry.status == "connected" and entry.role not in done:
        return with_status(entry, "failed", f"{material_name}: no node to connect it to")
    if entry.status == "connected":
        return with_status(entry, "connected", f"{material_name}: {done[entry.role]}")
    if entry.status == "loaded":
        return with_status(entry, "loaded", f"{material_name}: {entry.detail}")
    return entry
