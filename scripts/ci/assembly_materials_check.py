"""Character assembly (Slice 1): textures wired by manifest role, hidden meshes hidden. No Epic data.

Usage (the ``bpy`` module or a Blender binary):
    python scripts/ci/assembly_materials_check.py
    blender --background --factory-startup --python-exit-code 1 --python scripts/ci/assembly_materials_check.py

Builds a synthetic export (``tests_core/synthetic_assembly.py``: a v2 manifest with small generated
PNGs) and stand-in mesh objects that carry the add-on's own material templates, as the DNA importer
leaves them. It then runs the assembly step (``assembly.importer.apply``) and checks the node trees:
every image comes from its manifest role with the manifest's colour space, the eyes get the
sclera/iris maps, the skin keeps its Texture Logic node, and "hidden" meshes stay hidden across an
LOD switch. The full import of a real character is checked by hand (dev-docs/FINDINGS.md).
Exits non-zero on failure.
"""

import sys
import tempfile

from pathlib import Path
from typing import Any

import bpy


REPO = Path(__file__).resolve().parents[2]
ADDONS_FOLDER = REPO / "src" / "addons"
INSTANCE = "SyntheticCharacter"
TEMPLATES = {
    "head_lod0_mesh": "head_shader",
    "teeth_lod0_mesh": "teeth_shader",
    "saliva_lod0_mesh": "saliva_shader",
    "eyeLeft_lod0_mesh": "eyeLeft_shader",
    "eyeRight_lod0_mesh": "eyeRight_shader",
    "eyelashes_lod0_mesh": "eyelashes_shader",
    "body_lod0_mesh": "body_shader",
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)
    print(f"ok: {message}")


def write_png(path: Path) -> None:
    image = bpy.data.images.new(path.stem, 4, 4)
    image.pixels.foreach_set([0.5] * (4 * 4 * 4))
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


class FakeReader:
    """The two DNA reader calls the assembly step makes, over the synthetic mesh table."""

    def __init__(self, meshes: dict[int, tuple[str, str]]):
        self.names = {index: name for index, (name, _) in meshes.items()}

    def getMeshCount(self) -> int:  # the DNA reader's API
        return max(self.names) + 1

    def getMeshName(self, index: int) -> str:
        return self.names.get(index, f"unused{index}_lod0_mesh")


def stand_in_objects(materials_file: Path) -> None:
    """One plane per DNA mesh, named and textured as the DNA importer leaves them."""
    with bpy.data.libraries.load(str(materials_file)) as (source, target):
        target.materials = [name for name in set(TEMPLATES.values()) if name in source.materials]
    for mesh_name, template in TEMPLATES.items():
        mesh = bpy.data.meshes.new(mesh_name)
        mesh.from_pydata([(0, 0, 0), (1, 0, 0), (0, 1, 0)], [], [(0, 1, 2)])
        mesh.uv_layers.new(name="DiffuseUV")
        scene_object = bpy.data.objects.new(f"{INSTANCE}_{mesh_name}", mesh)
        bpy.context.scene.collection.objects.link(scene_object)
        material = bpy.data.materials.get(template)
        if material is None:  # templates the blend lacks (saliva): a plain material, as the importer does
            material = bpy.data.materials.new(template)
        material.name = f"{INSTANCE}_{template}"
        mesh.materials.append(material)


def upstream(socket: bpy.types.NodeSocket) -> bpy.types.Node | None:
    return socket.links[0].from_node if socket.links else None


def image_path(node: bpy.types.Node | None) -> str:
    return Path(node.image.filepath).name if node is not None and node.type == "TEX_IMAGE" and node.image else ""


def images(material: bpy.types.Material) -> dict[str, bpy.types.Node]:
    return {image_path(node): node for node in material.node_tree.nodes if node.type == "TEX_IMAGE" and node.image}


def reaches(node: bpy.types.Node, target: str, depth: int = 12) -> bool:
    """Whether ``node`` feeds (through any chain) an image node of file ``target``."""
    if image_path(node) == target:
        return True
    if depth == 0:
        return False
    return any(reaches(link.from_node, target, depth - 1) for socket in node.inputs for link in socket.links)


def check_eyes() -> None:
    # Eyes (the fix): sclera outside the iris, the iris scaled into it, DirectX normal flipped.
    for side in ("Left", "Right"):
        eye = bpy.data.materials[f"{INSTANCE}_eye{side}_shader"]
        principled = next(n for n in eye.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        base = upstream(principled.inputs["Base Color"])
        check(base is not None and reaches(base, "Eyes_ScleraBasecolor.png"), f"eye {side}: sclera reaches Base Color")
        check(reaches(base, "Eyes_IrisBasecolor.png"), f"eye {side}: iris reaches Base Color")
        check(reaches(base, "Eyes_Veins.png"), f"eye {side}: veins reach Base Color")
        iris = images(eye)["Eyes_IrisBasecolor.png"]
        check(upstream(iris.inputs["Vector"]).label == "Iris UV", f"eye {side}: iris uses the iris UV mapping")
        normal = upstream(principled.inputs["Normal"])
        check(normal is not None and normal.type == "NORMAL_MAP", f"eye {side}: Normal comes from a Normal Map")
        check(
            reaches(normal, "Eyes_IrisNormal.png") and reaches(normal, "Eyes_ScleraNormal.png"),
            f"eye {side}: both normals",
        )
        spaces = {name: node.image.colorspace_settings.name for name, node in images(eye).items()}
        check(
            spaces["Eyes_ScleraNormal.png"] == "Non-Color" and spaces["Eyes_IrisBasecolor.png"] == "sRGB",
            f"eye {side}: colour spaces from the manifest",
        )
        check(
            not any(o.links for o in images(eye)["Eyes_Dust.png"].outputs),
            f"eye {side}: dust loaded, not connected",
        )


def check_skin(callbacks: Any) -> None:
    # Head and body: images by role into the Texture Logic node, which stays.
    head = bpy.data.materials[f"{INSTANCE}_head_shader"]
    logic = callbacks.get_head_texture_logic_node(head)
    check(logic is not None, "head: Texture Logic node kept")
    check(image_path(upstream(logic.inputs["Color_MAIN"])) == "Head_Basecolor.png", "head: base colour by role")
    cm1 = upstream(logic.inputs["Color_CM1"])
    check(image_path(cm1) == "Head_Basecolor_Animated_CM1.png", "head: CM1 by role")
    check(cm1.image.colorspace_settings.name == "Non-Color", "head: CM1 is Non-Color, as the manifest says")
    blend = upstream(logic.inputs["Normal_MAIN"])
    check(
        blend.type == "GROUP" and reaches(blend, "Head_Normal.png") and reaches(blend, "Head_DetailNormal.png"),
        "head: normal + detail normal",
    )
    principled = next(n for n in head.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    check(reaches(upstream(principled.inputs["Roughness"]), "Head_SRMF.png"), "head: SRMF drives roughness")
    check(
        reaches(upstream(principled.inputs["Subsurface Weight"]), "Head_Scatter.png"),
        "head: scatter drives subsurface",
    )
    body = bpy.data.materials[f"{INSTANCE}_body_shader"]
    body_logic = callbacks.get_body_texture_logic_node(body)
    check(image_path(upstream(body_logic.inputs["Color_MAIN"])) == "Body_Basecolor.png", "body: base colour by role")
    teeth = bpy.data.materials[f"{INSTANCE}_teeth_shader"]
    teeth_bsdf = next(n for n in teeth.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    check(image_path(upstream(teeth_bsdf.inputs["Base Color"])) == "Teeth_Color.png", "teeth: colour by role")


def check_hidden(callbacks: Any, hidden_property: str) -> None:
    # Hidden meshes stay hidden, also after an LOD switch.
    for name in ("saliva_lod0_mesh", "eyelashes_lod0_mesh"):
        scene_object = bpy.data.objects[f"{INSTANCE}_{name}"]
        check(scene_object.get(hidden_property) and scene_object.hide_render, f"{name}: hidden for render")
    instance = bpy.context.scene.character_dna.rig_instance_list.add()
    instance.name = INSTANCE
    callbacks.set_active_lod(instance.view_options, 0)
    check(not bpy.data.objects[f"{INSTANCE}_head_lod0_mesh"].hide_get(), "LOD 0 switch shows the head")
    check(bpy.data.objects[f"{INSTANCE}_eyelashes_lod0_mesh"].hide_get(), "LOD 0 switch keeps the eyelash card hidden")


def main() -> None:
    sys.path.insert(0, str(ADDONS_FOLDER))
    sys.path.insert(0, str(REPO / "tests_core"))
    import synthetic_assembly

    import character_dna

    from character_dna.assembly import importer
    from character_dna.constants import ASSEMBLY_HIDDEN_PROPERTY, MATERIALS_FILE_PATH
    from character_dna.dna_core.assembly import load_manifest
    from character_dna.ui import callbacks

    character_dna.register()
    try:
        folder = Path(tempfile.mkdtemp(prefix="assembly_check_"))
        manifest = synthetic_assembly.write_export(folder, write_file=write_png)
        assembly = load_manifest(manifest)
        stand_in_objects(MATERIALS_FILE_PATH)
        result = importer.apply(
            assembly,
            INSTANCE,
            {"head": FakeReader(synthetic_assembly.HEAD_MESHES), "body": FakeReader(synthetic_assembly.BODY_MESHES)},
            logic_node_for={
                "head": callbacks.get_head_texture_logic_node,
                "body": callbacks.get_body_texture_logic_node,
            },
            clothing=False,
        )
        print(result.report_text)
        check(result.count("failed") == 0, "no texture failed to wire")
        check(result.count("connected") == 28 and result.count("loaded") == 5, "28 textures connected, 5 loaded")
        check(all(groom.ok for groom in result.grooms) and len(result.grooms) == 3, "3 grooms imported")

        check_eyes()
        check_skin(callbacks)
        check_hidden(callbacks, ASSEMBLY_HIDDEN_PROPERTY)
        check(bpy.data.texts.get(f"{INSTANCE}_assembly_report") is not None, "report written to a Text datablock")
    finally:
        character_dna.unregister()
    print("Assembly materials check passed")


if __name__ == "__main__":
    main()
