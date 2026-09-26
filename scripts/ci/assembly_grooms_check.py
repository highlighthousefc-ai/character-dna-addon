"""Character assembly grooms (Slice 2): curves, surface attachment, hair material. No Epic data.

Usage (the ``bpy`` module or a Blender binary):
    python scripts/ci/assembly_grooms_check.py
    blender --background --factory-startup --python-exit-code 1 --python scripts/ci/assembly_grooms_check.py

Uses the synthetic export (``tests_core/synthetic_assembly.py``), whose grooms are copies of
``tests_core/fixtures/synthetic_groom.abc`` (4 strands, one a guide). A UV-mapped grid stands in for
the head. The check runs the real assembly step (``assembly.importer.apply``) and verifies:

* each groom is a Curves object with the guide dropped, bound to the head surface by root UV, with a
  Deform Curves on Surface modifier, and the head has Add Rest Position;
* a shape key that lifts the head by 10 cm lifts every root by 10 cm (the strands follow the skin);
* the Principled Hair material carries the exported melanin values (Cycles) and Unreal's resolved
  colour (EEVEE);
* peach fuzz is hidden in the viewport but renders;
* the eyelash card mesh is hidden only when the eyelash groom was imported.

Exits non-zero on failure.
"""

import sys
import tempfile

from pathlib import Path

import bpy
import numpy as np


REPO = Path(__file__).resolve().parents[2]
ADDONS_FOLDER = REPO / "src" / "addons"
INSTANCE = "SyntheticCharacter"
LIFT = 0.1


def fail(message: str) -> None:
    raise RuntimeError(message)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)
    print(f"ok: {message}")


class FakeReader:
    """The two DNA reader calls the assembly step makes, over the synthetic mesh table."""

    def __init__(self, meshes: dict[int, tuple[str, str]]):
        self.names = {index: name for index, (name, _) in meshes.items()}

    def getMeshCount(self) -> int:  # the DNA reader's API
        return max(self.names) + 1

    def getMeshName(self, index: int) -> str:
        return self.names.get(index, f"unused{index}_lod0_mesh")


def head_stand_in() -> bpy.types.Object:
    """A 0.4 x 0.4 m grid facing -Y at head height, UVs 0..1, with a shape key lifting it by LIFT."""
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=8, y_subdivisions=8, size=0.4, location=(0, 0, 1.6))
    head = bpy.context.active_object
    head.name = f"{INSTANCE}_head_lod0_mesh"
    head.rotation_euler = (np.pi / 2, 0, 0)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    head.data.uv_layers.active.name = "DiffuseUV"
    head.shape_key_add(name="Basis")
    lift = head.shape_key_add(name="Lift")
    for point in lift.data:
        point.co.z += LIFT
    lift.value = 0.0  # a new shape key starts at 1.0
    return head


def root_positions(scene_object: bpy.types.Object) -> np.ndarray:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    curves = scene_object.evaluated_get(depsgraph).data
    positions = np.empty(len(curves.points) * 3, np.float32)
    curves.attributes["position"].data.foreach_get("vector", positions)
    offsets = np.empty(len(curves.curves) + 1, np.int32)
    curves.curve_offset_data.foreach_get("value", offsets)
    return positions.reshape(-1, 3)[offsets[:-1]] @ np.array(scene_object.matrix_world, np.float32)[:3, :3].T


def check_groom(scene_object: bpy.types.Object, head: bpy.types.Object) -> None:
    name = scene_object.name
    curves = scene_object.data
    check(scene_object.type == "CURVES", f"{name}: a Curves object")
    check(len(curves.curves) == 3 and len(curves.points) == 8, f"{name}: 3 strands, 8 points (the guide dropped)")
    check(curves.surface == head and curves.surface_uv_map == "DiffuseUV", f"{name}: bound to the head's DiffuseUV")
    uv = np.empty(len(curves.curves) * 2, np.float32)
    curves.attributes["surface_uv_coordinate"].data.foreach_get("vector", uv)
    check(np.allclose(uv.reshape(-1, 2), [[0.25, 0.75], [0.5, 0.5], [0.9, 0.1]]), f"{name}: root UVs as exported")
    modifier = next((m for m in scene_object.modifiers if m.type == "NODES"), None)
    deform = modifier and any(n.bl_idname == "GeometryNodeDeformCurvesOnSurface" for n in modifier.node_group.nodes)
    check(bool(deform), f"{name}: Deform Curves on Surface modifier")


def check_material(scene_object: bpy.types.Object) -> None:
    material = scene_object.data.materials[0]
    tree = material.node_tree
    outputs = {node.target: node for node in tree.nodes if node.type == "OUTPUT_MATERIAL"}
    cycles = outputs["CYCLES"].inputs["Surface"].links[0].from_node
    check(
        cycles.bl_idname == "ShaderNodeBsdfHairPrincipled" and cycles.parametrization == "MELANIN",
        "hair: Principled Hair, melanin",
    )
    check(
        abs(cycles.inputs["Melanin"].default_value - 0.9) < 1e-6
        and abs(cycles.inputs["Melanin Redness"].default_value - 0.25) < 1e-6
        and abs(cycles.inputs["Roughness"].default_value - 0.37) < 1e-6,
        "hair: melanin 0.9, redness 0.25, roughness 0.37 as exported",
    )
    eevee = outputs["EEVEE"].inputs["Surface"].links[0].from_node
    check(
        eevee.bl_idname == "ShaderNodeBsdfPrincipled"
        and abs(eevee.inputs["Base Color"].default_value[0] - 0.006) < 1e-6,
        "hair: EEVEE gets a Principled BSDF with the resolved colour (EEVEE has no hair shading)",
    )


def radius(scene_object: bpy.types.Object) -> np.ndarray:
    values = np.empty(len(scene_object.data.points), np.float32)
    scene_object.data.attributes["radius"].data.foreach_get("value", values)
    return values


def check_unreal_widths(assembly: object, importer: object, readers: dict) -> None:
    """Match Unreal widths: the component's width override, tapered root -> tip (file widths otherwise)."""
    for scene_object in [o for o in bpy.data.objects if o.type == "CURVES"]:
        bpy.data.objects.remove(scene_object)
    result = importer.apply(assembly, INSTANCE, readers, logic_node_for={}, match_unreal_widths=True, clothing=False)
    hair = bpy.data.objects[next(g.object_name for g in result.grooms if g.name == "hair")]
    check(
        np.allclose(radius(hair)[:3], [0.00006, 0.0000435, 0.000027], rtol=1e-4),
        "Match Unreal widths: 0.012 cm, tip x0.45",
    )
    check("Unreal width 0.012 cm" in result.report_text, "Match Unreal widths: the report says so")


def main() -> None:
    sys.path.insert(0, str(ADDONS_FOLDER))
    sys.path.insert(0, str(REPO / "tests_core"))
    import synthetic_assembly

    import character_dna

    from character_dna.assembly import importer
    from character_dna.constants import ASSEMBLY_HIDDEN_PROPERTY
    from character_dna.dna_core.assembly import load_manifest

    character_dna.register()
    try:
        bpy.ops.wm.read_homefile(use_empty=True)
        folder = Path(tempfile.mkdtemp(prefix="assembly_grooms_"))
        assembly = load_manifest(synthetic_assembly.write_export(folder))
        head = head_stand_in()
        mesh = bpy.data.meshes.new("card")
        mesh.from_pydata([(0, 0, 0), (0.01, 0, 0), (0, 0, 0.01)], [], [(0, 1, 2)])
        card = bpy.data.objects.new(f"{INSTANCE}_eyelashes_lod0_mesh", mesh)
        bpy.context.scene.collection.objects.link(card)
        readers = {"head": FakeReader(synthetic_assembly.HEAD_MESHES)}

        # Without grooms the eyelash card mesh stays: nothing else gives the character lashes.
        result = importer.apply(assembly, INSTANCE, readers, logic_node_for={}, grooms=False, clothing=False)
        check(
            not card.hide_get() and not card.get(ASSEMBLY_HIDDEN_PROPERTY), "no grooms: the eyelash card stays visible"
        )
        check(any("no eyelash groom" in w for w in result.warnings), "no grooms: the report says why")

        result = importer.apply(assembly, INSTANCE, readers, logic_node_for={}, clothing=False)
        print(result.report_text)
        check([g.name for g in result.grooms if g.ok] == ["hair", "eyelashes", "fuzz"], "3 grooms imported")
        check(card.hide_get() and card.hide_render, "eyelash groom imported: the card mesh is hidden")
        check(head.add_rest_position_attribute, "head: Add Rest Position on (needed by the deform node)")
        check(bpy.context.scene.render.hair_type == "STRIP", "Render > Curves > Shape is Strip (real widths in EEVEE)")
        grooms = {g.name: bpy.data.objects[g.object_name] for g in result.grooms}
        for scene_object in grooms.values():
            check_groom(scene_object, head)
        check_material(grooms["hair"])
        fuzz = grooms["fuzz"]
        check(fuzz.hide_viewport and not fuzz.hide_render, "fuzz: hidden in the viewport, renders")
        check(not grooms["hair"].hide_viewport, "hair: visible in the viewport")

        # The strands follow the skin: lift the head with a shape key, every root rises with it.
        before = root_positions(grooms["hair"])
        head.data.shape_keys.key_blocks["Lift"].value = 1.0
        bpy.context.view_layer.update()
        moved = root_positions(grooms["hair"]) - before
        print(f"root moves: {moved.round(4).tolist()}")
        check(np.allclose(moved, [0.0, 0.0, LIFT], atol=1e-4), f"roots follow the skin (+{LIFT} m in z)")
        warnings = [w.message for w in grooms["hair"].modifiers[0].node_warnings]
        check(not warnings, f"no node warnings ({warnings})")
        check_unreal_widths(assembly, importer, readers)
    finally:
        character_dna.unregister()
    print("Assembly grooms check passed")


if __name__ == "__main__":
    main()
