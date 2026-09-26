"""Character assembly clothing (Slice 3): FBX outfit on the body rig, fabric, body hiding. No Epic data.

Usage (the ``bpy`` module or a Blender binary):
    python scripts/ci/assembly_clothing_check.py
    blender --background --factory-startup --python-exit-code 1 --python scripts/ci/assembly_clothing_check.py

Builds a synthetic outfit in Blender and writes it as FBX: a tube "garment" skinned to its own
two-bone skeleton (``pelvis``, ``spine_01``), with one material slot nobody uses. Our "body" is a
tube skinned to a body rig with the same bones; its middle bulges out through the garment. A
synthetic ``Geometry/body.json`` marks the body faces the garment covers. The real assembly step
(``assembly.importer.apply``) then imports the outfit, and the check verifies:

* the garment is bound to our body rig (its own armature deleted), the unused slot dropped;
* its fabric material is built from the manifest (colour, normal by role);
* the covered body faces are marked and removed by the hiding modifier, and skin never shows over the
  garment's outside (``clothing.poke_through`` = 0), at rest and with the spine bent;
* with the hiding off, the bulge does poke through (so the test can fail);
* the Clothing toggle switches the hiding in viewport and render.

Exits non-zero on failure.
"""

import json
import math
import sys
import tempfile

from collections.abc import Callable
from pathlib import Path

import bpy
import numpy as np


REPO = Path(__file__).resolve().parents[2]
ADDONS_FOLDER = REPO / "src" / "addons"
INSTANCE = "Synthetic"


def fail(message: str) -> None:
    raise RuntimeError(message)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)
    print(f"ok: {message}")


def rig(name: str) -> bpy.types.Object:
    armature = bpy.data.armatures.new(name)
    scene_object = bpy.data.objects.new(name, armature)
    bpy.context.scene.collection.objects.link(scene_object)
    bpy.context.view_layer.objects.active = scene_object
    bpy.ops.object.mode_set(mode="EDIT")
    pelvis = armature.edit_bones.new("pelvis")
    pelvis.head, pelvis.tail = (0, 0, 0.8), (0, 0, 1.05)
    spine = armature.edit_bones.new("spine_01")
    spine.head, spine.tail, spine.parent = (0, 0, 1.05), (0, 0, 1.45), pelvis
    bpy.ops.object.mode_set(mode="OBJECT")
    return scene_object


def tube(
    name: str, radius: Callable[[float], float], z0: float, z1: float, rings: int, armature: bpy.types.Object
) -> bpy.types.Object:
    """An open tube, skinned to pelvis below 1.05 m and spine_01 above. ``radius(z)`` shapes it."""
    segments = 24
    vertices, faces = [], []
    for ring in range(rings + 1):
        z = z0 + (z1 - z0) * ring / rings
        for segment in range(segments):
            angle = 2 * math.pi * segment / segments
            vertices.append((radius(z) * math.cos(angle), radius(z) * math.sin(angle), z))
    for ring in range(rings):
        for segment in range(segments):
            a, b = ring * segments + segment, ring * segments + (segment + 1) % segments
            faces.append((a, b, b + segments, a + segments))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.uv_layers.new(name="DiffuseUV")
    scene_object = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(scene_object)
    lower, upper = scene_object.vertex_groups.new(name="pelvis"), scene_object.vertex_groups.new(name="spine_01")
    for index, co in enumerate(vertices):
        (lower if co[2] < 1.05 else upper).add([index], 1.0, "REPLACE")
    scene_object.parent = armature
    scene_object.modifiers.new("Armature", "ARMATURE").object = armature
    return scene_object


def write_png(path: Path, rgb: tuple) -> None:
    image = bpy.data.images.new(path.stem, 4, 4)
    image.pixels.foreach_set([*rgb, 1.0] * 16)
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    bpy.data.images.remove(image)


def synthetic_export(folder: Path) -> tuple[Path, bpy.types.Object, bpy.types.Object]:
    """Write the outfit FBX, body.json, maps and manifest; leave the body rig and body in the scene."""
    (folder / "Clothing").mkdir(parents=True)
    (folder / "Geometry").mkdir()
    (folder / "Maps").mkdir()
    # The outfit: garment tube (radius 0.16 m, z 0.9-1.3) on its own skeleton, two material slots.
    outfit_rig = rig("Root")
    garment = tube("Garment", lambda _z: 0.16, 0.9, 1.3, 8, outfit_rig)
    for name in ("MI_Fabric", "MI_Fabric_2"):
        garment.data.materials.append(bpy.data.materials.new(name))
    bpy.ops.object.select_all(action="DESELECT")
    for scene_object in (outfit_rig, garment):
        scene_object.select_set(True)
    bpy.ops.export_scene.fbx(
        filepath=str(folder / "Clothing" / "outfits.fbx"), use_selection=True, add_leaf_bones=False
    )
    for scene_object in (garment, outfit_rig):
        bpy.data.objects.remove(scene_object)
    # Our body: a tube (radius 0.15) whose middle (z 1.0-1.15) bulges to 0.17, through the garment.
    body_rig = rig(f"{INSTANCE}_body_rig")
    body = tube(f"{INSTANCE}_body_lod0_mesh", lambda z: 0.17 if 1.0 <= z <= 1.15 else 0.15, 0.7, 1.5, 16, body_rig)
    covered = [p.center.z > 0.9 and p.center.z < 1.3 for p in body.data.polygons]
    visible = []
    for face, polygon in enumerate(body.data.polygons):
        if not covered[face]:
            a, b, c, d = polygon.vertices
            visible += [[face, a, b, c], [face, a, c, d]]
    geometry = {
        "meshes": [
            {
                "mesh_index": 0,
                "lod": 0,
                "name": "body_lod0_mesh",
                "vertex_count": len(body.data.vertices),
                "face_count": len(body.data.polygons),
                "visibility_valid": True,
                "visible_triangles": visible,
            }
        ]
    }
    (folder / "Geometry" / "body.json").write_text(json.dumps(geometry), encoding="utf-8")
    write_png(folder / "Maps" / "Fabric_Normal.png", (0.5, 0.5, 1.0))
    write_png(folder / "Maps" / "Fabric_AO.png", (1.0, 1.0, 0.0))
    manifest = {
        "schema_version": 2,
        "name": INSTANCE,
        "dna": {"head": "head.dna", "body": "body.dna"},
        "dna_geometry": [{"role": "body", "path": "Geometry/body.json", "meshes": []}],
        "components": [
            {
                "id": "outfit",
                "name": "outfits",
                "type": "fbx",
                "path": "Clothing/outfits.fbx",
                "role": "clothing",
                "attach_to": "body",
                "materials": [{"name": "mat_fabric"}],
            }
        ],
        "materials": [
            {
                "name": "mat_fabric",
                "type": "clothes",
                "slot": "M_Fabric",
                "display_name": "MI_Fabric",
                "profile": "creator",
                "textures": [
                    {"role": "normal", "path": "Maps/Fabric_Normal.png", "color_space": "Non-Color"},
                    {"role": "ambient_occlusion", "path": "Maps/Fabric_AO.png", "color_space": "sRGB"},
                ],
                "fabric": {"color": [0.2, 0.4, 0.6], "normal_strength": 0.8, "micro_scale": 50},
            }
        ],
    }
    path = folder / "CharacterAssemblyManifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, body_rig, body


class FakeReader:
    def getMeshCount(self) -> int:  # the DNA reader's API
        return 1

    def getMeshName(self, _index: int) -> str:
        return "body_lod0_mesh"


def main() -> None:
    sys.path.insert(0, str(ADDONS_FOLDER))
    import character_dna

    from character_dna.assembly import clothing, importer
    from character_dna.dna_core.assembly import load_manifest

    character_dna.register()
    try:
        bpy.ops.wm.read_homefile(use_empty=True)
        manifest, body_rig, body = synthetic_export(Path(tempfile.mkdtemp(prefix="assembly_clothing_")))
        assembly = load_manifest(manifest)
        result = importer.apply(assembly, INSTANCE, {"body": FakeReader()}, logic_node_for={})
        print(result.report_text)
        check(len(result.clothing) == 1 and result.clothing[0].ok, "the outfit imported")
        outfit = bpy.data.objects[result.clothing[0].objects[0]]
        modifier = next(m for m in outfit.modifiers if m.type == "ARMATURE")
        check(outfit.parent == body_rig and modifier.object == body_rig, "the garment is bound to our body rig")
        check(
            not [o for o in bpy.data.objects if o.type == "ARMATURE" and o != body_rig],
            "the FBX's own armature is gone",
        )
        check(
            result.clothing[0].bones == 2 and not result.clothing[0].missing_bones,
            "every garment bone maps to the body rig",
        )
        check(
            [m.name for m in outfit.data.materials] == [f"{INSTANCE}_MI_Fabric"], "the unused material slot is dropped"
        )
        tree = outfit.data.materials[0].node_tree
        bsdf = next(n for n in tree.nodes if n.type == "BSDF_PRINCIPLED")
        check(
            bsdf.inputs["Normal"].is_linked and bsdf.inputs["Base Color"].is_linked, "fabric: normal and colour wired"
        )
        connected = {e.role for e in result.statuses if e.material == "mat_fabric" and e.status == "connected"}
        check(connected == {"normal", "ambient_occlusion"}, "fabric textures connected by role")

        covered = np.zeros(len(body.data.polygons), bool)
        body.data.attributes[clothing.UNDER_CLOTHES_ATTRIBUTE].data.foreach_get("value", covered)
        check(covered.sum() >= 24 * 8, f"covered body faces marked ({int(covered.sum())})")
        check(body.modifiers[-1].name == clothing.HIDE_MODIFIER, "the hiding modifier runs after the Armature")
        depsgraph = bpy.context.evaluated_depsgraph_get()
        shown = len(body.evaluated_get(depsgraph).data.polygons)
        check(shown == len(body.data.polygons) - covered.sum(), "covered faces are removed from the rendered body")
        check(clothing.poke_through(body, [outfit]) == 0, "no skin over the clothes (hiding on, rest)")
        pose = body_rig.pose.bones["spine_01"]
        pose.rotation_mode = "XYZ"
        pose.rotation_euler = (math.radians(25), 0, 0)
        bpy.context.view_layer.update()
        check(clothing.poke_through(body, [outfit]) == 0, "no skin over the clothes (hiding on, spine bent)")
        clothing.set_body_hiding([body], False)
        bpy.context.view_layer.update()
        through = clothing.poke_through(body, [outfit])
        check(through > 0, f"with the hiding off, the bulge pokes through ({through} faces)")
        check(not clothing.body_hiding_enabled([body]), "the toggle turns the hiding off")
        clothing.set_body_hiding([body], True)
        hide = body.modifiers[clothing.HIDE_MODIFIER]
        check(hide.show_viewport and hide.show_render, "the toggle turns it back on, viewport and render")
    finally:
        character_dna.unregister()
    print("Assembly clothing check passed")


if __name__ == "__main__":
    main()
