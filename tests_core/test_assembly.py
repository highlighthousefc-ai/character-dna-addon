"""Character assembly manifest (dna_core.assembly): reading, path safety and the texture plan."""

import hashlib
import json

from pathlib import Path

import pytest
import synthetic_assembly

from dna_core.assembly import (
    KNOWN_CAPABILITIES,
    ManifestError,
    dna_mismatches,
    format_report,
    load_manifest,
    texture_plan,
)


@pytest.fixture
def export(tmp_path: Path) -> Path:
    return synthetic_assembly.write_export(tmp_path / "export")


def _plan(manifest: Path) -> dict[tuple[str, str], tuple[str, str, str]]:
    return {
        (entry.material, entry.role): (entry.status, entry.color_space, entry.detail)
        for entry in texture_plan(load_manifest(manifest))
    }


def test_reads_a_v2_manifest(export: Path):
    assembly = load_manifest(export)
    assert assembly.schema_version == 2
    assert assembly.name == "SyntheticCharacter"
    assert assembly.dna == {"head": export.parent / "head.dna", "body": export.parent / "body.dna"}
    assert len(assembly.meshes) == len(synthetic_assembly.HEAD_MESHES) + len(synthetic_assembly.BODY_MESHES)
    assert assembly.mesh_material("head", 3).type == "eye_ball"
    assert assembly.mesh_material("body", 0).name == "mat_body"
    assert [c.type for c in assembly.components] == ["fbx", "alembic"]
    # the folder works too
    assert load_manifest(export.parent).name == "SyntheticCharacter"


@pytest.mark.parametrize("version", [1, 3, None, "2"])
def test_other_schema_versions_are_refused(tmp_path: Path, version: object):
    data = synthetic_assembly.manifest_data(schema_version=version)
    manifest = synthetic_assembly.write_export(tmp_path, data)
    with pytest.raises(ManifestError, match="schema version"):
        load_manifest(manifest)


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside.png", "Maps/../../outside.png", "C:/Windows/x.png"])
def test_paths_may_not_leave_the_export_folder(tmp_path: Path, bad: str):
    data = synthetic_assembly.manifest_data()
    data["materials"][0]["textures"][0]["path"] = bad
    manifest = synthetic_assembly.write_export(tmp_path / "export", data)
    with pytest.raises(ManifestError, match="outside the export folder"):
        load_manifest(manifest)


def test_unreadable_manifests_raise_manifest_error(tmp_path: Path):
    (tmp_path / "CharacterAssemblyManifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ManifestError, match="not valid JSON"):
        load_manifest(tmp_path)
    with pytest.raises(ManifestError, match="Can't read"):
        load_manifest(tmp_path / "missing" / "CharacterAssemblyManifest.json")


def test_unknown_colour_space_is_refused(tmp_path: Path):
    data = synthetic_assembly.manifest_data()
    data["materials"][0]["textures"][0]["color_space"] = "ACEScg"
    with pytest.raises(ManifestError, match="colour space"):
        load_manifest(synthetic_assembly.write_export(tmp_path, data))


def test_eye_textures_are_connected_by_role(export: Path):
    """The eye fix: the export's sclera/iris maps (not Eyes_Color/Eyes_Normal) reach the eye shader."""
    plan = _plan(export)
    for side in ("left", "right"):
        material = f"mat_eye_{side}"
        for role in ("sclera_base_color", "iris_base_color", "sclera_normal", "iris_normal", "veins"):
            assert plan[material, role][0] == "connected", (material, role)
        assert plan[material, "iris_base_color"][2].endswith("(inside the iris)")
        assert plan[material, "dust"][0] == "loaded"


def test_every_exported_skin_role_is_connected(export: Path):
    plan = _plan(export)
    head_roles = [role for role, _, _ in synthetic_assembly.MATERIALS[0][3]]
    assert all(plan["mat_head", role][0] == "connected" for role in head_roles)
    assert all(plan["mat_body", role][0] == "connected" for role in ("base_color", "normal", "srmf", "scatter"))
    assert plan["mat_teeth", "base_color"][0] == "connected"
    assert plan["mat_teeth", "teeth_mask_001"][0] == "loaded"


def test_colour_space_comes_from_the_manifest_not_the_file_name(tmp_path: Path):
    data = synthetic_assembly.manifest_data()
    # A "..._Color.png" file tagged Non-Color stays Non-Color; a "..._Normal.png" tagged sRGB stays sRGB.
    textures = data["materials"][0]["textures"]
    textures[0].update(path="Maps/Odd_Color.png", color_space="Non-Color")
    textures[1].update(path="Maps/Odd_Normal.png", color_space="sRGB")
    plan = _plan(synthetic_assembly.write_export(tmp_path, data))
    assert plan["mat_head", "base_color"][1] == "Non-Color"
    assert plan["mat_head", "normal"][1] == "sRGB"


def test_missing_files_are_reported(tmp_path: Path):
    manifest = synthetic_assembly.write_export(tmp_path, skip=("Eyes_IrisBasecolor.png",))
    plan = _plan(manifest)
    assert plan["mat_eye_left", "iris_base_color"][:1] == ("missing",)
    assert plan["mat_eye_left", "sclera_base_color"][0] == "connected"


def test_hidden_meshes_and_deferred_components(export: Path):
    assembly = load_manifest(export)
    assert [m.mesh_index for m in assembly.hidden_meshes("head")] == [2, 6]
    assert assembly.hidden_meshes("body") == []
    plan = _plan(export)
    assert plan["mat_shirt", "normal"][0::2] == ("deferred", "clothing is Slice 3")
    assert plan["mat_hair", "highlight_mask"][0::2] == ("deferred", "grooms are Slice 2")


def test_textures_of_hidden_materials_are_not_wired(tmp_path: Path):
    data = synthetic_assembly.manifest_data()
    saliva = next(m for m in data["materials"] if m["name"] == "mat_saliva")
    saliva["textures"] = [{"role": "base_color", "path": "Maps/Saliva.png", "color_space": "sRGB"}]
    assert _plan(synthetic_assembly.write_export(tmp_path, data))["mat_saliva", "base_color"][0] == "hidden"


def test_unknown_roles_and_types_are_loaded_not_guessed(tmp_path: Path):
    data = synthetic_assembly.manifest_data()
    data["materials"][0]["textures"].append({"role": "new_role", "path": "Maps/New.png", "color_space": "sRGB"})
    saliva = next(m for m in data["materials"] if m["name"] == "mat_saliva")
    saliva["profile"] = "creator"
    saliva["textures"] = [{"role": "base_color", "path": "Maps/Saliva.png", "color_space": "sRGB"}]
    for geometry in data["dna_geometry"]:
        for mesh in geometry["meshes"]:
            if mesh["material"]["name"] == "mat_saliva":
                mesh["material"]["profile"] = "creator"
    plan = _plan(synthetic_assembly.write_export(tmp_path, data))
    assert plan["mat_head", "new_role"][0::2] == ("loaded", 'unknown role for a "head" material')
    assert plan["mat_saliva", "base_color"][0::2] == ("loaded", 'no shader for "saliva" materials yet')


def test_report_lists_counts_warnings_and_unknown_capabilities(tmp_path: Path):
    data = synthetic_assembly.manifest_data(required_capabilities=["semantic_components", "time_travel"])
    data["diagnostics"] = ["groom hair: 3 strands clamped"]
    assembly = load_manifest(synthetic_assembly.write_export(tmp_path, data))
    assert assembly.unknown_capabilities() == ["time_travel"]
    assert "semantic_components" in KNOWN_CAPABILITIES
    report = format_report(assembly, texture_plan(assembly), ["X_saliva_lod0_mesh"], ["something off"])
    assert "Textures: 28 connected, 4 loaded, 2 deferred" in report
    assert "WARNING: something off" in report
    assert "WARNING: Unknown required capabilities (may not import fully): time_travel" in report
    assert "WARNING: Exporter diagnostic: groom hair: 3 strands clamped" in report
    assert "MI_mat_eye_left (eye_ball) iris_base_color = Eyes_IrisBasecolor.png [sRGB]" in report
    assert "  X_saliva_lod0_mesh" in report


def test_edited_dna_is_detected(tmp_path: Path):
    folder = tmp_path / "export"
    data = synthetic_assembly.manifest_data()
    manifest = synthetic_assembly.write_export(folder, data)
    (folder / "head.dna").write_bytes(b"exported")
    data["dna_geometry"][1]["dna_sha256"] = hashlib.sha256(b"exported").hexdigest()
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert dna_mismatches(load_manifest(manifest)) == []
    (folder / "head.dna").write_bytes(b"edited")
    assert dna_mismatches(load_manifest(manifest)) == [
        "head.dna differs from the exported file (edited since the export?)"
    ]
