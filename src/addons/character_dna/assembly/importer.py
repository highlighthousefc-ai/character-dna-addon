"""Import a character assembly: the DNAs through the existing importer, then textures and visibility.

Steps: read the manifest (``dna_core.assembly``), import head and body into one rig instance
(``operators.import_character``), wire every texture by role into the materials the DNA importer
built (``materials``), hide the meshes the manifest marks hidden, and write a report to a Text
datablock ``<instance>_assembly_report``.
"""

import logging

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bpy

from ..constants import ASSEMBLY_HIDDEN_PROPERTY
from ..dna_core import assembly as manifest
from ..dna_core.assembly import Assembly, TextureStatus, with_status
from . import materials


logger = logging.getLogger(__name__)


@dataclass
class AssemblyImportResult:
    instance_name: str = ""
    statuses: list[TextureStatus] = field(default_factory=list)
    hidden_objects: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    report_text: str = ""

    def count(self, status: str) -> int:
        return sum(1 for entry in self.statuses if entry.status == status)

    def summary(self) -> str:
        parts = [f"{self.count(s)} {s}" for s in ("connected", "loaded", "missing", "failed") if self.count(s)]
        hidden = f", {len(self.hidden_objects)} meshes hidden" if self.hidden_objects else ""
        return f'Textures: {", ".join(parts) or "none"}{hidden}. Report: Text "{self.report_name}"'

    @property
    def report_name(self) -> str:
        return f"{self.instance_name}_assembly_report"


def mesh_objects(instance_name: str, reader: Any, dna: str, assembly: Assembly) -> dict[str, list[bpy.types.Object]]:
    """Manifest material name -> the imported objects of the DNA meshes that use it."""
    found: dict[str, list[bpy.types.Object]] = {}
    for mesh in assembly.meshes:
        if mesh.dna != dna or mesh.mesh_index >= reader.getMeshCount():
            continue
        scene_object = bpy.data.objects.get(f"{instance_name}_{reader.getMeshName(mesh.mesh_index)}")
        if scene_object is not None:
            found.setdefault(mesh.material, []).append(scene_object)
    return found


def hide(scene_object: bpy.types.Object) -> None:
    scene_object[ASSEMBLY_HIDDEN_PROPERTY] = True
    scene_object.hide_render = True
    try:
        scene_object.hide_set(True)
    except RuntimeError:  # not in the view layer; hide_render and the tag still apply
        logger.warning(f'"{scene_object.name}" is not in the view layer')


def apply(
    assembly: Assembly,
    instance_name: str,
    readers: dict[str, Any],
    logic_node_for: dict[str, Any],
    wire: bool = True,
    warnings: list[str] | None = None,
) -> AssemblyImportResult:
    """Wire textures and hide meshes for an already imported instance. ``readers``: DNA role -> reader."""
    result = AssemblyImportResult(instance_name=instance_name, warnings=list(warnings or []))
    result.warnings.extend(manifest.dna_mismatches(assembly))
    objects: dict[str, list[bpy.types.Object]] = {}
    for dna, reader in readers.items():
        for name, found in mesh_objects(instance_name, reader, dna, assembly).items():
            objects.setdefault(name, []).extend(found)

    plan = manifest.texture_plan(assembly)
    by_material: dict[str, list[TextureStatus]] = {}
    for entry in plan:
        by_material.setdefault(entry.material, []).append(entry)
    for name, entries in by_material.items():
        source = assembly.materials[name]
        if entries[0].status == "deferred" or source.hidden:
            result.statuses.extend(entries)
            continue
        if not wire:
            result.statuses.extend(
                with_status(e, "skipped", "Materials was off in the import options")
                if e.status in ("connected", "loaded")
                else e
                for e in entries
            )
            continue
        blender_materials = []
        for scene_object in objects.get(name, []):
            material = scene_object.active_material
            if material is not None and material not in blender_materials:
                blender_materials.append(material)
        if not blender_materials:
            result.statuses.extend(
                with_status(e, "failed", "no imported mesh uses this material")
                if e.status in ("connected", "loaded")
                else e
                for e in entries
            )
            continue
        outcome = entries
        for material in blender_materials:
            outcome = materials.wire_material(
                material, source, entries, prefix=instance_name, logic_node_for=logic_node_for.get(source.type)
            )
        result.statuses.extend(outcome)

    for dna, reader in readers.items():
        for mesh in assembly.hidden_meshes(dna):
            if mesh.mesh_index >= reader.getMeshCount():
                continue
            scene_object = bpy.data.objects.get(f"{instance_name}_{reader.getMeshName(mesh.mesh_index)}")
            if scene_object is not None:
                hide(scene_object)
                result.hidden_objects.append(scene_object.name)
    result.report_text = manifest.format_report(assembly, result.statuses, result.hidden_objects, result.warnings)
    write_report(result)
    return result


def write_report(result: AssemblyImportResult) -> bpy.types.Text:
    text = bpy.data.texts.get(result.report_name) or bpy.data.texts.new(result.report_name)
    text.clear()
    text.write(result.report_text)
    logger.info(result.report_text)
    return text


def import_assembly(manifest_path: Path, properties: Any, include_body: bool = True) -> AssemblyImportResult:
    """Import the character a manifest describes. Raises ``ManifestError`` or ``RuntimeError``."""
    from .. import operators
    from ..ui import callbacks

    assembly = manifest.load_manifest(manifest_path)
    head = assembly.dna["head"]
    if not head.is_file():
        raise manifest.ManifestError(f"The head DNA is missing: {head}")
    body = assembly.dna.get("body")
    body = body if include_body and body is not None and body.is_file() else None
    imported = operators.import_character(head, properties, body)
    if not imported.valid:
        raise RuntimeError("; ".join(message for level, message in imported.messages if level == "ERROR"))
    warnings = [] if body is not None or not assembly.dna.get("body") else ["The body was not imported"]
    readers = {"head": imported.head.dna_reader}
    if imported.body is not None:
        readers["body"] = imported.body.dna_reader
    result = apply(
        assembly,
        imported.head.name,
        readers,
        logic_node_for={"head": callbacks.get_head_texture_logic_node, "body": callbacks.get_body_texture_logic_node},
        wire=bool(properties.import_materials),
        warnings=warnings,
    )
    return result
