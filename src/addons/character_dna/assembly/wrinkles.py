"""Offset blending for wrinkle maps stored as offsets (MetaHuman exports from Unreal 5.6 and later).

``dna_core.wrinkles`` explains the format and holds the formula; this module builds it in the head
material's Texture Logic. For a character whose wrinkle maps are offsets, :func:`enable_offsets`:

* gives the character its own copy of the inherited blend group (``head_shader_logic``, shared by every
  character in the file) and swaps its colour and normal ``MergeMaps`` for offset merges:
  ``base + sum_i(weight_i * (map_i - 0.5)) * gain``, the colour one summing in sRGB space;
* multiplies every region mask by the strength of its facial area (brows, eyes, nose, cheeks, mouth,
  chin & jaw, neck);
* exposes those strengths and the gain as new inputs **at the end** of the Texture Logic node, so the
  rig's drivers, which address its inputs by index, keep working. All default to 1.

Unreal's exact wrinkle scale isn't in the export: strength 1 and gain 1 are starting values.
"""

import logging

import bpy
import numpy as np

from ..dna_core.wrinkles import AREAS, GAMMA, are_offsets, area_of


logger = logging.getLogger(__name__)

OFFSET_MERGE_GROUP = "Character DNA Wrinkle Offsets"
COLOR_OFFSET_MERGE_GROUP = "Character DNA Wrinkle Offsets (sRGB)"
GAIN_INPUT = "Wrinkle Gain"
STRENGTH_PREFIX = "Wrinkle Strength: "


def image_means(image: bpy.types.Image, step: int = 8) -> np.ndarray:
    """Mean RGB of an image's stored values (sampled), without colour management."""
    width, height = image.size
    pixels = np.empty(width * height * 4, np.float32)
    image.pixels.foreach_get(pixels)
    return pixels.reshape(height, width, 4)[::step, ::step, :3].reshape(-1, 3).mean(0)


def maps_are_offsets(color_map: bpy.types.Image | None, normal_map: bpy.types.Image | None) -> bool:
    """True when the wrinkle maps are offsets: colour centred on 0.5, normal blue near 0.5 (not 1)."""
    if color_map is None or normal_map is None or 0 in color_map.size or 0 in normal_map.size:
        return False
    return are_offsets(image_means(color_map), image_means(normal_map))


def offset_merge_group(srgb: bool = False) -> bpy.types.ShaderNodeTree:
    """Base + (Fac1 (Map1 - 0.5) + Fac2 (Map2 - 0.5) + Fac3 (Map3 - 0.5)) * Gain, clamped at 0.

    ``srgb``: the base arrives linear (an sRGB image) but the offsets were authored against the 8-bit
    sRGB texture, so the sum happens in sRGB (display) space. Added in linear space, the same offsets
    darken dim channels far more than bright ones and creases turn orange (FINDINGS).
    """
    name = COLOR_OFFSET_MERGE_GROUP if srgb else OFFSET_MERGE_GROUP
    group = bpy.data.node_groups.get(name)
    if group is not None:
        return group
    group = bpy.data.node_groups.new(name, "ShaderNodeTree")
    group.interface.new_socket("Base Map", in_out="INPUT", socket_type="NodeSocketColor")
    for index in (1, 2, 3):
        group.interface.new_socket(f"Map{index} Fac", in_out="INPUT", socket_type="NodeSocketFloat")
        group.interface.new_socket(f"Map{index}", in_out="INPUT", socket_type="NodeSocketColor")
    gain = group.interface.new_socket("Gain", in_out="INPUT", socket_type="NodeSocketFloat")
    gain.default_value = 1.0
    group.interface.new_socket("Map", in_out="OUTPUT", socket_type="NodeSocketColor")
    nodes, links = group.nodes, group.links
    inputs, outputs = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    total = None
    for index in (1, 2, 3):
        offset = nodes.new("ShaderNodeVectorMath")  # Map - 0.5
        offset.operation = "SUBTRACT"
        links.new(inputs.outputs[f"Map{index}"], offset.inputs[0])
        offset.inputs[1].default_value = (0.5, 0.5, 0.5)
        weighted = nodes.new("ShaderNodeVectorMath")  # * Fac
        weighted.operation = "SCALE"
        links.new(offset.outputs[0], weighted.inputs[0])
        links.new(inputs.outputs[f"Map{index} Fac"], weighted.inputs["Scale"])
        if total is None:
            total = weighted.outputs[0]
        else:
            add = nodes.new("ShaderNodeVectorMath")
            add.operation = "ADD"
            links.new(total, add.inputs[0])
            links.new(weighted.outputs[0], add.inputs[1])
            total = add.outputs[0]
    scaled = nodes.new("ShaderNodeVectorMath")
    scaled.operation = "SCALE"
    links.new(total, scaled.inputs[0])
    links.new(inputs.outputs["Gain"], scaled.inputs["Scale"])
    base = inputs.outputs["Base Map"]
    if srgb:
        encode = nodes.new("ShaderNodeGamma")
        links.new(base, encode.inputs["Color"])
        encode.inputs["Gamma"].default_value = 1.0 / GAMMA
        base = encode.outputs[0]
    result = nodes.new("ShaderNodeVectorMath")
    result.operation = "ADD"
    links.new(base, result.inputs[0])
    links.new(scaled.outputs[0], result.inputs[1])
    clamp = nodes.new("ShaderNodeVectorMath")
    clamp.operation = "MAXIMUM"
    links.new(result.outputs[0], clamp.inputs[0])
    clamp.inputs[1].default_value = (0.0, 0.0, 0.0)
    out = clamp.outputs[0]
    if srgb:
        decode = nodes.new("ShaderNodeGamma")
        links.new(out, decode.inputs["Color"])
        decode.inputs["Gamma"].default_value = GAMMA
        out = decode.outputs[0]
    links.new(out, outputs.inputs["Map"])
    for x, node in enumerate(nodes):
        node.location = (200 * (x % 6), -200 * (x // 6))
    return group


def _merge_nodes(inner: bpy.types.ShaderNodeTree) -> dict[str, bpy.types.Node]:
    """The inner logic's MergeMaps nodes by what they output: Color, Normal (and Mask, left alone)."""
    found = {}
    for link in inner.links:
        if link.to_node.type == "GROUP_OUTPUT" and link.from_node.type == "GROUP":
            found[link.to_socket.name] = link.from_node
    return found


def enable_offsets(logic_node: bpy.types.Node, prefix: str) -> dict[str, float]:
    """Switch a head material's Texture Logic to offset blending. Returns the area strengths."""
    outer = logic_node.node_tree
    inner_node = next(
        n for n in outer.nodes if n.type == "GROUP" and n.node_tree and "shader_logic" in n.node_tree.name
    )
    inner = inner_node.node_tree
    if not inner.get("character_dna_offsets"):
        inner = inner.copy()  # the inherited group is shared by every character in the file
        inner.name = f"{prefix}_head_shader_logic_offsets"
        inner["character_dna_offsets"] = True
        inner_node.node_tree = inner
        merges = _merge_nodes(inner)
        for socket_name in ("Color", "Normal"):
            old = merges[socket_name]
            new = inner.nodes.new("ShaderNodeGroup")
            new.node_tree = offset_merge_group(srgb=socket_name == "Color")
            new.label = f"{socket_name} offsets"
            new.location = old.location
            for link in list(inner.links):
                if link.to_node == old:
                    inner.links.new(link.from_socket, new.inputs[link.to_socket.name])
                elif link.from_node == old:
                    inner.links.new(new.outputs["Map"], link.to_socket)
            inner.nodes.remove(old)
        _add_strengths(inner)
    # Expose the strengths and the gain on the Texture Logic node, appended so input indices stay put.
    strengths = {}
    for name in (*(STRENGTH_PREFIX + area for area in AREAS), GAIN_INPUT):
        if name not in outer.interface.items_tree:
            socket = outer.interface.new_socket(name, in_out="INPUT", socket_type="NodeSocketFloat")
            socket.default_value = 1.0
            socket.min_value, socket.max_value = 0.0, 4.0
            # The node's new input exists before the default was set, so it starts at 0: set it.
            logic_node.inputs[name].default_value = 1.0
        group_input = next(n for n in outer.nodes if n.type == "GROUP_INPUT")
        if not inner_node.inputs[name].links:
            outer.links.new(group_input.outputs[name], inner_node.inputs[name])
        strengths[name] = logic_node.inputs[name].default_value
    return strengths


def _add_strengths(inner: bpy.types.ShaderNodeTree) -> None:
    """Multiply every region mask by its area's strength; wire the gain into the offset merges."""
    group_input = next(n for n in inner.nodes if n.type == "GROUP_INPUT")
    for area in AREAS:
        socket = inner.interface.new_socket(STRENGTH_PREFIX + area, in_out="INPUT", socket_type="NodeSocketFloat")
        socket.default_value = 1.0
    gain = inner.interface.new_socket(GAIN_INPUT, in_out="INPUT", socket_type="NodeSocketFloat")
    gain.default_value = 1.0
    for link in list(inner.links):
        name = link.from_socket.name
        if link.from_node != group_input or not name.endswith("_msk"):
            continue
        area = area_of(name)
        if area is None:
            logger.warning(f"No wrinkle area for mask {name}; its strength stays 1")
            continue
        multiply = inner.nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        multiply.label = f"{area} strength"
        multiply.location = (link.to_node.location.x - 200, link.to_node.location.y)
        inner.links.new(link.from_socket, multiply.inputs[0])
        inner.links.new(group_input.outputs[STRENGTH_PREFIX + area], multiply.inputs[1])
        inner.links.new(multiply.outputs[0], link.to_socket)
    for node in inner.nodes:
        if (
            node.type == "GROUP"
            and node.node_tree
            and node.node_tree.name in (OFFSET_MERGE_GROUP, COLOR_OFFSET_MERGE_GROUP)
        ):
            inner.links.new(group_input.outputs[GAIN_INPUT], node.inputs["Gain"])


WRINKLE_INPUTS = {
    "Color_CM1": "color",
    "Color_CM2": "color",
    "Color_CM3": "color",
    "Normal_WM1": "normal",
    "Normal_WM2": "normal",
    "Normal_WM3": "normal",
}


def _image(logic_node: bpy.types.Node, socket_name: str) -> bpy.types.Image | None:
    socket = logic_node.inputs.get(socket_name)
    node = socket.links[0].from_node if socket is not None and socket.links else None
    return getattr(node, "image", None) if node is not None and node.type == "TEX_IMAGE" else None


def apply_if_offsets(logic_node: bpy.types.Node | None, prefix: str) -> str | None:
    """Switch the head material to offset blending when its wrinkle maps are offsets.

    Returns what was done (for the import report), or ``None`` when the maps are full maps (or absent)
    and the inherited mix stays.
    """
    if logic_node is None:
        return None
    if not maps_are_offsets(_image(logic_node, "Color_CM1"), _image(logic_node, "Normal_WM1")):
        return None
    for socket_name in WRINKLE_INPUTS:  # offsets are data, never colour-managed
        image = _image(logic_node, socket_name)
        if image is not None:
            try:
                image.colorspace_settings.name = "Non-Color"
            except TypeError:
                image.colorspace_settings.name = "Raw"
    enable_offsets(logic_node, prefix)
    return (
        "Wrinkle maps are offsets (Unreal 5.6+ export): offset blending on, colour in sRGB space; "
        f"per-area strengths and gain on the Texture Logic node ({len(AREAS)} areas, all 1)"
    )


def is_offset_logic(logic_node: bpy.types.Node | None) -> bool:
    return logic_node is not None and GAIN_INPUT in logic_node.inputs
