"""Import a character assembly: the DNAs through the existing importer, then textures and visibility.

Steps: read the manifest (``dna_core.assembly``), import head and body into one rig instance
(``operators.import_character``), wire every texture by role into the materials the DNA importer
built (``materials``), import the grooms onto the head (``grooms``), hide the meshes the manifest
marks hidden, and write a report to a Text datablock ``<instance>_assembly_report``.

The eyelash card mesh is marked hidden because the eyelash groom replaces it, so it's only hidden
when that groom was imported.
"""

import logging

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import bpy

from ..constants import ASSEMBLY_HIDDEN_PROPERTY
from ..dna_core import assembly as manifest, clothing as clothing_data
from ..dna_core.assembly import Assembly, TextureStatus, with_status
from . import clothing as clothing_import, grooms as groom_import, materials, wrinkles


logger = logging.getLogger(__name__)


@dataclass
class AssemblyImportResult:
    instance_name: str = ""
    statuses: list[TextureStatus] = field(default_factory=list)
    hidden_objects: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    grooms: list[groom_import.GroomResult] = field(default_factory=list)
    clothing: list[clothing_import.ClothingResult] = field(default_factory=list)
    body_faces_hidden: int = 0
    body_faces_margin: int = 0
    notes: list[str] = field(default_factory=list)
    report_text: str = ""

    def count(self, status: str) -> int:
        return sum(1 for entry in self.statuses if entry.status == status)

    def summary(self) -> str:
        parts = [f"{self.count(s)} {s}" for s in ("connected", "loaded", "missing", "failed") if self.count(s)]
        hidden = f", {len(self.hidden_objects)} meshes hidden" if self.hidden_objects else ""
        imported = sum(1 for groom in self.grooms if groom.ok)
        grooms = f", {imported} of {len(self.grooms)} grooms" if self.grooms else ""
        if self.clothing:
            grooms += f", {sum(1 for c in self.clothing if c.ok)} of {len(self.clothing)} outfits"
        return f'Textures: {", ".join(parts) or "none"}{grooms}{hidden}. Report: Text "{self.report_name}"'

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
    grooms: bool = True,
    match_unreal_widths: bool = False,
    clothing: bool = True,
    hide_under_clothes: bool = True,
) -> AssemblyImportResult:
    """Wire textures, import grooms and clothing, hide meshes. ``readers``: DNA role -> reader."""
    result = AssemblyImportResult(instance_name=instance_name, warnings=list(warnings or []))
    result.warnings.extend(manifest.dna_mismatches(assembly))
    by_material: dict[str, list[TextureStatus]] = {}
    for entry in manifest.texture_plan(assembly):
        by_material.setdefault(entry.material, []).append(entry)
    _wire_textures(assembly, instance_name, readers, logic_node_for, by_material, wire, result)
    if wire and "head" in logic_node_for:
        head = head_surface(assembly, instance_name, readers.get("head"))
        material = head.active_material if head is not None else None
        note = wrinkles.apply_if_offsets(logic_node_for["head"](material), instance_name) if material else None
        if note:
            result.notes.append(note)
    if grooms:
        _import_grooms(assembly, instance_name, readers, by_material, result, match_unreal_widths)
    else:
        for component in assembly.grooms():
            entries = [e for name in component.materials for e in by_material.get(name, [])]
            result.statuses.extend(with_status(e, "skipped", "Grooms was off in the import options") for e in entries)
    if clothing:
        _import_clothing(assembly, instance_name, readers, by_material, result, hide_under_clothes)
    else:
        for component in assembly.clothing():
            entries = [e for name in component.materials for e in by_material.get(name, [])]
            result.statuses.extend(with_status(e, "skipped", "Clothing was off in the import options") for e in entries)
    _hide_meshes(assembly, instance_name, readers, result)
    result.report_text = manifest.format_report(assembly, result.statuses, result.hidden_objects, result.warnings)
    if result.grooms:
        result.report_text += "\nGrooms (guides removed, (x, -y, z) / 100, radius = width / 2):\n"
        result.report_text += "\n".join(groom.line() for groom in result.grooms) + "\n"
        unmapped = sorted({key for groom in result.grooms for key in groom.unmapped_hair_color})
        if unmapped:
            result.report_text += f"Hair colour settings with no Principled Hair input: {', '.join(unmapped)}\n"
    if result.clothing:
        result.report_text += "\nClothing (FBX, bound to the body rig):\n"
        result.report_text += "\n".join(item.line() for item in result.clothing) + "\n"
    result.report_text += "".join(f"Note: {note}\n" for note in result.notes)
    write_report(result)
    return result


def _wire_textures(
    assembly: Assembly,
    instance_name: str,
    readers: dict[str, Any],
    logic_node_for: dict[str, Any],
    by_material: dict[str, list[TextureStatus]],
    wire: bool,
    result: AssemblyImportResult,
) -> None:
    """The DNA meshes' materials: each texture by role (``materials.wire_material``)."""
    objects: dict[str, list[bpy.types.Object]] = {}
    for dna, reader in readers.items():
        for name, found in mesh_objects(instance_name, reader, dna, assembly).items():
            objects.setdefault(name, []).extend(found)
    groom_materials = {name for component in (*assembly.grooms(), *assembly.clothing()) for name in component.materials}
    for name, entries in by_material.items():
        source = assembly.materials[name]
        if name in groom_materials:
            continue  # the grooms' own step
        if entries[0].status == "deferred" or source.hidden:
            result.statuses.extend(entries)
            continue
        blender_materials = []
        for scene_object in objects.get(name, []):
            material = scene_object.active_material
            if material is not None and material not in blender_materials:
                blender_materials.append(material)
        reason = "" if wire else "Materials was off in the import options"
        if wire and not blender_materials:
            reason = "no imported mesh uses this material"
        if reason:
            status = "skipped" if not wire else "failed"
            result.statuses.extend(
                with_status(e, status, reason) if e.status in ("connected", "loaded") else e for e in entries
            )
            continue
        outcome = entries
        for material in blender_materials:
            outcome = materials.wire_material(
                material, source, entries, prefix=instance_name, logic_node_for=logic_node_for.get(source.type)
            )
        result.statuses.extend(outcome)


def _import_grooms(
    assembly: Assembly,
    instance_name: str,
    readers: dict[str, Any],
    by_material: dict[str, list[TextureStatus]],
    result: AssemblyImportResult,
    match_unreal_widths: bool = False,
) -> None:
    head = head_surface(assembly, instance_name, readers.get("head"))
    if assembly.grooms():
        # Render > Curves > Shape: Strip draws strands at their real width. The default (Strand) draws
        # every strand at least a pixel wide, so fine hair turns heavy and peach fuzz a frost in EEVEE.
        bpy.context.scene.render.hair_type = "STRIP"
        result.notes.append("Render > Curves > Shape set to Strip (real strand widths in EEVEE)")
    for component in assembly.grooms():
        entries = [e for name in component.materials for e in by_material.get(name, [])]
        groom = groom_import.import_groom(component, assembly, head, instance_name, entries, match_unreal_widths)
        result.grooms.append(groom)
        result.statuses.extend(groom.statuses)
        if not groom.ok:
            result.warnings.append(f'Groom "{component.name}" not imported: {groom.error}')


def _import_clothing(
    assembly: Assembly,
    instance_name: str,
    readers: dict[str, Any],
    by_material: dict[str, list[TextureStatus]],
    result: AssemblyImportResult,
    hide_under_clothes: bool,
) -> None:
    body_rig = bpy.data.objects.get(f"{instance_name}_body_rig")
    for component in assembly.clothing():
        entries = [e for name in component.materials for e in by_material.get(name, [])]
        if body_rig is None:
            result.statuses.extend(with_status(e, "failed", "no body rig to bind the clothes to") for e in entries)
            result.warnings.append(f'Clothing "{component.name}" not imported: the body was not imported')
            continue
        outfit = clothing_import.import_outfit(component, assembly, body_rig, instance_name, entries)
        result.clothing.append(outfit)
        result.statuses.extend(outfit.statuses)
        if not outfit.ok:
            result.warnings.append(f'Clothing "{component.name}" not imported: {outfit.error}')
        elif outfit.missing_bones:
            result.warnings.append(
                f'Clothing "{component.name}": bones not in the body rig: {outfit.missing_bones[:5]}'
            )
    if not any(c.ok for c in result.clothing) or "body" not in assembly.geometry or "body" not in readers:
        return
    try:
        covered = clothing_data.body_coverage(assembly.geometry["body"])
    except clothing_data.GeometryError as error:
        result.warnings.append(f"Body under the clothes not hidden: {error}")
        return
    bodies = []
    for name, coverage in covered.items():
        body = bpy.data.objects.get(f"{instance_name}_{name}")
        if body is None:
            continue
        garments = [bpy.data.objects[name] for c in result.clothing if c.ok for name in c.objects]
        hidden = coverage.hidden
        if len(body.data.polygons) == len(hidden):
            hidden = clothing_import.grow_under_clothes(body, garments, hidden)
            if coverage.lod == 0:
                result.body_faces_margin = int(hidden.sum() - coverage.hidden.sum())
        try:
            count = clothing_import.hide_under_clothes(body, hidden)
        except clothing_data.GeometryError as error:
            result.warnings.append(f"Body under the clothes not hidden on {body.name}: {error}")
            continue
        bodies.append(body)
        if coverage.lod == 0:
            result.body_faces_hidden = count
    clothing_import.set_body_hiding(bodies, hide_under_clothes)
    if bodies:
        state = "on" if hide_under_clothes else "off (toggle in the Clothing panel)"
        result.notes.append(
            f"Body under the clothes: {result.body_faces_hidden} LOD0 faces "
            f"({result.body_faces_hidden - result.body_faces_margin} from Geometry/body.json, "
            f"{result.body_faces_margin} covered neighbours as a margin), hiding {state}"
        )


def _hide_meshes(assembly: Assembly, instance_name: str, readers: dict[str, Any], result: AssemblyImportResult) -> None:
    """Hide the meshes marked hidden; the eyelash card only when the eyelash groom replaced it."""
    lashes = any(g.ok and g.region == groom_import.LASHES_REGION for g in result.grooms)
    for dna, reader in readers.items():
        for mesh in assembly.hidden_meshes(dna):
            if mesh.mesh_index >= reader.getMeshCount():
                continue
            scene_object = bpy.data.objects.get(f"{instance_name}_{reader.getMeshName(mesh.mesh_index)}")
            if scene_object is None:
                continue
            material = assembly.materials.get(mesh.material)
            if material is not None and material.type == "eyelashes" and not lashes:
                result.warnings.append(f'Kept "{scene_object.name}" visible: no eyelash groom was imported')
                continue
            hide(scene_object)
            result.hidden_objects.append(scene_object.name)


def head_surface(assembly: Assembly, instance_name: str, reader: Any) -> bpy.types.Object | None:
    """The head's LOD0 skin mesh, which the grooms attach to."""
    if reader is None:
        return None
    for mesh in assembly.meshes:
        material = assembly.materials.get(mesh.material)
        is_head_skin = mesh.dna == "head" and mesh.lod == 0 and material is not None and material.type == "head"
        if is_head_skin and mesh.mesh_index < reader.getMeshCount():
            return bpy.data.objects.get(f"{instance_name}_{reader.getMeshName(mesh.mesh_index)}")
    return None


def write_report(result: AssemblyImportResult) -> bpy.types.Text:
    text = bpy.data.texts.get(result.report_name) or bpy.data.texts.new(result.report_name)
    text.clear()
    text.write(result.report_text)
    logger.info(result.report_text)
    return text


def import_assembly(
    manifest_path: Path,
    properties: Any,
    include_body: bool = True,
    grooms: bool = True,
    match_unreal_widths: bool = False,
    clothing: bool = True,
    hide_under_clothes: bool = True,
) -> AssemblyImportResult:
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
        grooms=grooms,
        match_unreal_widths=match_unreal_widths,
        clothing=clothing,
        hide_under_clothes=hide_under_clothes,
    )
    return result
