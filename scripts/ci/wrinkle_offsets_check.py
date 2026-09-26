"""Offset wrinkle maps: detection, the Texture Logic switch, and the node maths. No Epic data.

Usage (the ``bpy`` module or a Blender binary):
    python scripts/ci/wrinkle_offsets_check.py
    blender --background --factory-startup --python-exit-code 1 --python scripts/ci/wrinkle_offsets_check.py

* Offset maps (centred on 0.5, normal blue 0.5) switch the add-on's head material to offset blending.
  Its first inputs (which the rig's drivers address by index) stay as they were; per-area strengths
  and a gain are appended, all 1; every region mask is multiplied by its area's strength.
* Full maps (the inherited format) leave the material alone.
* The offset merge groups compute ``dna_core.wrinkles.blend``: checked by baking them with Cycles on
  a plane and comparing the pixel with the numpy reference (colour in sRGB space, normals not).

Exits non-zero on failure.
"""

import sys

from pathlib import Path

import bpy
import numpy as np


REPO = Path(__file__).resolve().parents[2]
ADDONS_FOLDER = REPO / "src" / "addons"


def fail(message: str) -> None:
    raise RuntimeError(message)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)
    print(f"ok: {message}")


def image(name: str, rgb: tuple[float, float, float]) -> bpy.types.Image:
    result = bpy.data.images.new(name, 4, 4, float_buffer=True)
    result.colorspace_settings.name = "Non-Color"
    result.pixels.foreach_set(np.tile([*rgb, 1.0], 16).astype(np.float32))
    return result


def head_material(materials_file: Path, name: str) -> bpy.types.Material:
    with bpy.data.libraries.load(str(materials_file)) as (_, target):
        target.materials = ["head_shader"]
    material = target.materials[0]
    material.name = name
    return material


def set_wrinkle_images(logic: bpy.types.Node, color: tuple, normal: tuple) -> None:
    for index in (1, 2, 3):
        for socket, rgb in ((f"Color_CM{index}", color), (f"Normal_WM{index}", normal)):
            logic.inputs[socket].links[0].from_node.image = image(f"{socket}_{rgb}", rgb)


def bake(group: bpy.types.ShaderNodeTree, base: tuple, fac1: float, map1: tuple, gain: float) -> np.ndarray:
    """Bake Emission(group(Base, Fac1, Map1, Fac2 = Fac3 = 0, Gain)) on a plane with Cycles; one pixel."""
    bpy.ops.mesh.primitive_plane_add()
    plane = bpy.context.active_object
    material = bpy.data.materials.new("bake")
    plane.data.materials.append(material)
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    emission = tree.nodes.new("ShaderNodeEmission")
    node = tree.nodes.new("ShaderNodeGroup")
    node.node_tree = group
    node.inputs["Base Map"].default_value = (*base, 1.0)
    node.inputs["Map1 Fac"].default_value = fac1
    node.inputs["Map1"].default_value = (*map1, 1.0)
    for index in (2, 3):
        node.inputs[f"Map{index} Fac"].default_value = 0.0
        node.inputs[f"Map{index}"].default_value = (0.5, 0.5, 0.5, 1.0)
    node.inputs["Gain"].default_value = gain
    tree.links.new(node.outputs["Map"], emission.inputs["Color"])
    tree.links.new(emission.outputs[0], output.inputs["Surface"])
    target = bpy.data.images.new("baked", 2, 2, float_buffer=True)
    target.colorspace_settings.name = "Non-Color"
    texture = tree.nodes.new("ShaderNodeTexImage")
    texture.image = target
    tree.nodes.active = texture
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    bpy.ops.object.bake(type="EMIT")
    pixels = np.empty(2 * 2 * 4, np.float32)
    target.pixels.foreach_get(pixels)
    bpy.data.objects.remove(plane)
    return pixels.reshape(-1, 4)[0, :3]


def main() -> None:
    sys.path.insert(0, str(ADDONS_FOLDER))
    import character_dna

    from character_dna.assembly import wrinkles
    from character_dna.constants import MATERIALS_FILE_PATH
    from character_dna.dna_core import wrinkles as reference
    from character_dna.ui import callbacks

    character_dna.register()
    try:
        bpy.ops.wm.read_homefile(use_empty=True)
        # Full maps (older exports): nothing changes.
        full = head_material(MATERIALS_FILE_PATH, "Full_head_shader")
        logic = callbacks.get_head_texture_logic_node(full)
        set_wrinkle_images(logic, (0.61, 0.43, 0.34), (0.5, 0.5, 1.0))
        check(wrinkles.apply_if_offsets(logic, "Full") is None, "full wrinkle maps: the inherited mix stays")
        check(not wrinkles.is_offset_logic(logic), "full wrinkle maps: no strength inputs added")

        # Offset maps (Unreal 5.6+): offset blending, strengths appended, driver indices unchanged.
        material = head_material(MATERIALS_FILE_PATH, "Offsets_head_shader")
        logic = callbacks.get_head_texture_logic_node(material)
        set_wrinkle_images(logic, (0.496, 0.495, 0.496), (0.498, 0.498, 0.497))
        before = [socket.name for socket in logic.inputs]
        note = wrinkles.apply_if_offsets(logic, "Offsets")
        check(note is not None and "offset blending on" in note, "offset wrinkle maps detected and switched")
        after = [socket.name for socket in logic.inputs]
        check(after[: len(before)] == before, "the existing inputs keep their order (drivers address them by index)")
        added = after[len(before) :]
        expected = [wrinkles.STRENGTH_PREFIX + area for area in reference.AREAS] + [wrinkles.GAIN_INPUT]
        check(added == expected, f"appended inputs: {len(reference.AREAS)} area strengths and the gain")
        check(all(logic.inputs[name].default_value == 1.0 for name in added), "strengths and gain default to 1")
        inner = next(n for n in logic.node_tree.nodes if n.type == "GROUP" and "shader_logic" in n.node_tree.name)
        check(inner.node_tree.name == "Offsets_head_shader_logic_offsets", "the character got its own blend group")
        full_logic = callbacks.get_head_texture_logic_node(full)
        full_inner = next(
            n for n in full_logic.node_tree.nodes if n.type == "GROUP" and "shader_logic" in n.node_tree.name
        )
        full_groups = {n.node_tree.name for n in full_inner.node_tree.nodes if n.type == "GROUP"}
        check(
            "offsets" not in full_inner.node_tree.name
            and not full_groups & {wrinkles.OFFSET_MERGE_GROUP, wrinkles.COLOR_OFFSET_MERGE_GROUP},
            "the other character (full maps) keeps the shared, mixing blend group",
        )
        groups = {n.node_tree.name for n in inner.node_tree.nodes if n.type == "GROUP"}
        check(
            {wrinkles.OFFSET_MERGE_GROUP, wrinkles.COLOR_OFFSET_MERGE_GROUP} <= groups,
            "colour and normal offset merges",
        )
        multiplies = [n for n in inner.node_tree.nodes if n.type == "MATH" and n.label.endswith(" strength")]
        masks = [s for s in inner.node_tree.interface.items_tree if s.item_type == "SOCKET" and s.name.endswith("_msk")]
        check(len(multiplies) >= len(masks) > 30, f"every region mask ({len(masks)}) scaled by its area's strength")
        spaces = {logic.inputs[s].links[0].from_node.image.colorspace_settings.name for s in wrinkles.WRINKLE_INPUTS}
        check(spaces == {"Non-Color"}, "offset maps read as data (Non-Color)")

        # The node maths match the reference formula (a Cycles bake of each merge group).
        base, crease = (0.33, 0.155, 0.1), (0.41, 0.41, 0.435)
        color = bake(bpy.data.node_groups[wrinkles.COLOR_OFFSET_MERGE_GROUP], base, 0.8, crease, 1.5)
        expected_color = reference.blend(np.array(base), [0.8, 0, 0], [np.array(crease), 0.5, 0.5], gain=1.5, srgb=True)
        print(f"colour: baked {color.round(5).tolist()}, reference {expected_color.round(5).tolist()}")
        check(np.allclose(color, expected_color, atol=2e-3), "colour offset merge = reference (summed in sRGB)")
        normal_base, wm = (0.5, 0.5, 1.0), (0.62, 0.40, 0.5)
        normal = bake(bpy.data.node_groups[wrinkles.OFFSET_MERGE_GROUP], normal_base, 1.0, wm, 1.0)
        expected_normal = reference.blend(np.array(normal_base), [1.0, 0, 0], [np.array(wm), 0.5, 0.5])
        print(f"normal: baked {normal.round(5).tolist()}, reference {expected_normal.round(5).tolist()}")
        check(np.allclose(normal, expected_normal, atol=2e-3), "normal offset merge = reference (encoded values)")
    finally:
        character_dna.unregister()
    print("Wrinkle offsets check passed")


if __name__ == "__main__":
    main()
