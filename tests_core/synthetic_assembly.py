"""A synthetic "Export Character For DCC" folder: a v2 manifest plus stand-in files, no Epic data.

The manifest follows the real schema (dev-docs/FINDINGS.md "Character Assembly Slice 0"): the same
keys, material types, texture roles and colour spaces, with made-up names and hashes. The files are
empty unless ``write_file`` is given (the Blender check writes small real PNGs through it).
"""

import json

from collections.abc import Callable
from pathlib import Path
from typing import Any


# (material name, type, profile, [(role, file, colour space)]) -- roles and colour spaces as exported.
MATERIALS: list[tuple[str, str, str, list[tuple[str, str, str]]]] = [
    (
        "mat_head",
        "head",
        "creator",
        [
            ("base_color", "Head_Basecolor.png", "sRGB"),
            ("normal", "Head_Normal.png", "Non-Color"),
            ("base_color_animated_cm1", "Head_Basecolor_Animated_CM1.png", "Non-Color"),
            ("base_color_animated_cm2", "Head_Basecolor_Animated_CM2.png", "Non-Color"),
            ("base_color_animated_cm3", "Head_Basecolor_Animated_CM3.png", "Non-Color"),
            ("normal_animated_wm1", "Head_Normal_Animated_WM1.png", "Non-Color"),
            ("normal_animated_wm2", "Head_Normal_Animated_WM2.png", "Non-Color"),
            ("normal_animated_wm3", "Head_Normal_Animated_WM3.png", "Non-Color"),
            ("detail_normal", "Head_DetailNormal.png", "Non-Color"),
            ("srmf", "Head_SRMF.png", "Non-Color"),
            ("scatter", "Head_Scatter.png", "sRGB"),
        ],
    ),
    (
        "mat_teeth",
        "teeth",
        "creator",
        [
            ("base_color", "Teeth_Color.png", "sRGB"),
            ("normal", "Teeth_Normal.png", "Non-Color"),
            ("teeth_mask_001", "Teeth_Mask001.png", "Non-Color"),
            ("teeth_mask_002", "Teeth_Mask002.png", "Non-Color"),
        ],
    ),
    ("mat_saliva", "saliva", "hidden", []),
    *[
        (
            f"mat_eye_{side}",
            "eye_ball",
            "creator",
            [
                ("sclera_base_color", "Eyes_ScleraBasecolor.png", "sRGB"),
                ("iris_base_color", "Eyes_IrisBasecolor.png", "sRGB"),
                ("sclera_normal", "Eyes_ScleraNormal.png", "Non-Color"),
                ("iris_normal", "Eyes_IrisNormal.png", "Non-Color"),
                ("veins", "Eyes_Veins.png", "sRGB"),
                ("dust", "Eyes_Dust.png", "sRGB"),
            ],
        )
        for side in ("left", "right")
    ],
    ("mat_eyelashes", "eyelashes", "hidden", []),
    (
        "mat_body",
        "body",
        "creator",
        [
            ("base_color", "Body_Basecolor.png", "sRGB"),
            ("normal", "Body_Normal.png", "Non-Color"),
            ("detail_normal", "Body_DetailNormal.png", "Non-Color"),
            ("srmf", "Body_SRMF.png", "Non-Color"),
            ("scatter", "Body_Scatter.png", "sRGB"),
        ],
    ),
    ("mat_shirt", "clothes", "creator", [("normal", "Clothes_Shirt_Normal.png", "Non-Color")]),
    ("mat_hair", "hair", "creator", [("highlight_mask", "Hair_HighlightsMask.png", "sRGB")]),
    ("mat_lashes_groom", "eyelashes_groom", "creator", []),
    ("mat_fuzz", "peach_fuzz", "creator", []),
]

# Groom components: (name, region, material). Their files are copies of fixtures/synthetic_groom.abc.
GROOMS = [("hair", "scalp", "mat_hair"), ("eyelashes", "lashes", "mat_lashes_groom"), ("fuzz", "fuzz", "mat_fuzz")]
GROOM_FIXTURE = Path(__file__).parent / "fixtures" / "synthetic_groom.abc"
# As exported (hair_color of a hair material), made-up values.
HAIR_COLOR = {
    "melanin": 0.9,
    "redness": 0.25,
    "tint": [1.0, 1.0, 1.0],
    "white_amount": 0.0,
    "roughness": 0.37,
    "color": [0.006, 0.0014, 0.0003],
    "ramps": {"root_to_tip": [{"position": 0.0, "color": [0.006, 0.0014, 0.0003]}]},
}

# DNA mesh index -> (mesh name, material). The head's indices follow MetaHuman's LOD0 order.
HEAD_MESHES = {
    0: ("head_lod0_mesh", "mat_head"),
    1: ("teeth_lod0_mesh", "mat_teeth"),
    2: ("saliva_lod0_mesh", "mat_saliva"),
    3: ("eyeLeft_lod0_mesh", "mat_eye_left"),
    4: ("eyeRight_lod0_mesh", "mat_eye_right"),
    6: ("eyelashes_lod0_mesh", "mat_eyelashes"),
}
BODY_MESHES = {0: ("body_lod0_mesh", "mat_body")}


def _profile(name: str) -> str:
    return next(profile for material, _, profile, _ in MATERIALS if material == name)


def _type(name: str) -> str:
    return next(kind for material, kind, _, _ in MATERIALS if material == name)


def manifest_data(**overrides: Any) -> dict[str, Any]:
    def geometry(role: str, meshes: dict[int, tuple[str, str]]) -> dict[str, Any]:
        return {
            "id": role,
            "role": role,
            "origin": "dna",
            "path": f"Geometry/{role}.json",
            "meshes": [
                {
                    "mesh_index": index,
                    "lod": 0,
                    "skin": role == "body" or name.startswith("head"),
                    "material": {
                        "slot": f"{name}_shader",
                        "name": material,
                        "profile": _profile(material),
                        "type": _type(material),
                    },
                }
                for index, (name, material) in meshes.items()
            ],
        }

    data: dict[str, Any] = {
        "schema_version": 2,
        "name": "SyntheticCharacter",
        "dna": {"body": "body.dna", "head": "head.dna"},
        "dna_geometry": [geometry("body", BODY_MESHES), geometry("head", HEAD_MESHES)],
        "rigs": {"head": {"capabilities": {"valid": True, "joints": 3, "meshes": 7, "lods": 1}}},
        "components": [
            {
                "id": "outfit",
                "name": "outfits",
                "type": "fbx",
                "path": "Clothing/outfits.fbx",
                "role": "clothing",
                "attach_to": "body",
                "materials": [{"name": "mat_shirt"}],
            },
            *[
                {
                    "id": name,
                    "name": name,
                    "type": "alembic",
                    "path": f"Grooms/{name}.abc",
                    "role": "hair",
                    "attach_to": "head",
                    "binding": "surface",
                    "materials": [{"name": material, "region": region, "enabled": True}],
                    "groom": {"width": 0.012, "root_scale": 1.0, "tip_scale": 0.45},
                }
                for name, region, material in GROOMS
            ],
        ],
        "materials": [
            {
                "name": name,
                "type": kind,
                "slot": f"{name}_slot",
                "display_name": f"MI_{name}",
                "profile": profile,
                "textures": [
                    {"role": role, "path": f"Maps/{file}", "color_space": space} for role, file, space in textures
                ],
                **({"hair_color": HAIR_COLOR} if name in {material for _, _, material in GROOMS} else {}),
            }
            for name, kind, profile, textures in MATERIALS
        ],
        "required_capabilities": ["semantic_components", "dna_provenance", "groom_physics_groups"],
        "diagnostics": [],
    }
    data.update(overrides)
    return data


def write_export(
    folder: Path,
    data: dict[str, Any] | None = None,
    write_file: Callable[[Path], None] | None = None,
    skip: tuple[str, ...] = (),
) -> Path:
    """Write the manifest and a stand-in for every file it names (except ``skip``). Returns its path."""
    data = data if data is not None else manifest_data()
    folder.mkdir(parents=True, exist_ok=True)
    files = {data["dna"][role] for role in data["dna"]}
    files |= {texture["path"] for material in data["materials"] for texture in material.get("textures", [])}
    files |= {component["path"] for component in data.get("components", []) if component["type"] == "alembic"}
    root = folder.resolve()
    for relative in sorted(files):
        path = (folder / relative).resolve()
        # Tests put paths that escape the folder (absolute, "..", "C:/...") in the manifest on purpose:
        # never create those.
        if Path(relative).name in skip or ":" in relative or not path.is_relative_to(root):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        if write_file is not None and path.suffix == ".png":
            write_file(path)
        elif path.suffix == ".abc":
            path.write_bytes(GROOM_FIXTURE.read_bytes())
        else:
            path.write_bytes(b"")
    manifest = folder / "CharacterAssemblyManifest.json"
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return manifest
