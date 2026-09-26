"""Read a MetaHuman "Export Character For DCC" folder through its ``CharacterAssemblyManifest.json``.

The folder is written by Poly Hammer Interchange (an Unreal plugin). Only its *output* is read here,
from a real export (schema version 2); see ``dev-docs/FINDINGS.md`` "Character Assembly Slice 0".

* ``dna`` names the head and body DNA files.
* ``dna_geometry[].meshes[]`` gives every DNA mesh a material (by name) and a ``profile``;
  ``"hidden"`` means the mesh isn't rendered (saliva, cartilage, the eyelash card mesh).
* ``materials[]`` lists each material's textures by ``role`` with the colour space to read them in.
  Textures are wired from these roles, never from file names.
* ``components[]`` are the grooms (Alembic, Slice 2: ``grooms.py`` and ``assembly/grooms.py``) and
  clothing (FBX, Slice 3).

Every path is relative to the folder. A path that is absolute or leaves the folder is refused.

:func:`texture_plan` says, per material and role, where Slice 1 connects the texture, or why it
doesn't. The Blender side carries it out and reports the outcome with the same records.
"""

import hashlib
import json

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_NAME = "CharacterAssemblyManifest.json"
SCHEMA_VERSION = 2
COLOR_SPACES = ("sRGB", "Non-Color")
DNA_ROLES = ("head", "body")

# Capabilities in the real v2 export. Anything else is reported, since the file relies on it.
KNOWN_CAPABILITIES = frozenset(
    {
        "semantic_components",
        "source_slots",
        "retained_rigs",
        "surface_materials",
        "section_filter",
        "dna_provenance",
        "skin_visibility",
        "slot_aliases",
        "groom_physics_groups",
    }
)

_SRMF = "Principled Specular IOR Level (R), Roughness (G), Metallic (B); A (probably fuzz) not connected"

# Where Slice 1 connects each texture role, by material type. The target names are the ones the
# Blender side builds (``assembly/materials.py``).
CONNECTED_ROLES: dict[str, dict[str, str]] = {
    "head": {
        "base_color": "Texture Logic Color_MAIN",
        "base_color_animated_cm1": "Texture Logic Color_CM1",
        "base_color_animated_cm2": "Texture Logic Color_CM2",
        "base_color_animated_cm3": "Texture Logic Color_CM3",
        "normal": "Texture Logic Normal_MAIN (with the detail normal)",
        "normal_animated_wm1": "Texture Logic Normal_WM1",
        "normal_animated_wm2": "Texture Logic Normal_WM2",
        "normal_animated_wm3": "Texture Logic Normal_WM3",
        "detail_normal": "Texture Logic Normal_MAIN (tiled, blended into the normal)",
        "srmf": _SRMF,
        "scatter": "Principled Subsurface Weight",
    },
    "body": {
        "base_color": "Texture Logic Color_MAIN",
        "normal": "Texture Logic Normal_MAIN (with the detail normal)",
        "detail_normal": "Texture Logic Normal_MAIN (tiled, blended into the normal)",
        "srmf": _SRMF,
        "scatter": "Principled Subsurface Weight",
    },
    "teeth": {
        "base_color": "Principled Base Color",
        "normal": "Principled Normal",
    },
    "eye_ball": {
        "sclera_base_color": "Principled Base Color (outside the iris)",
        "iris_base_color": "Principled Base Color (inside the iris)",
        "sclera_normal": "Principled Normal (outside the iris)",
        "iris_normal": "Principled Normal (inside the iris)",
        "veins": "Principled Base Color (multiplies the sclera)",
    },
    "clothes": {
        "ambient_occlusion": "Base Color (multiplies; red channel)",
        "normal": "Normal (DirectX)",
        "stitch_mask": "Base Color (stitch colour where the mask is set)",
        "micro_normal": "Normal (tiled micro normal)",
        "micro_height": "Normal (tiled bump)",
        "macro_variation": "Base Color (tiled variation)",
    },
}

# Roles that are loaded (right image, right colour space) but not connected, and why.
UNCONNECTED_ROLES: dict[tuple[str, str], str] = {
    ("teeth", "teeth_mask_001"): "channel meaning not verified (teeth / tongue masks)",
    ("teeth", "teeth_mask_002"): "channel meaning not verified (occlusion / edge masks)",
    ("eye_ball", "dust"): "how Unreal applies it is not verified",
}

# Components no slice imports yet.
DEFERRED_COMPONENTS: dict[str, str] = {}
# Hair material textures: Blender's Principled Hair BSDF has no input for them.
GROOM_UNCONNECTED = "loaded, not connected: the Principled Hair BSDF has no input for it"


class ManifestError(ValueError):
    """The manifest can't be used: unreadable, the wrong schema, or a bad path."""


@dataclass(frozen=True)
class Texture:
    role: str
    path: Path
    color_space: str

    @property
    def exists(self) -> bool:
        return self.path.is_file()


@dataclass(frozen=True)
class Material:
    name: str
    type: str
    slot: str
    display_name: str
    profile: str
    textures: tuple[Texture, ...] = ()
    # Hair materials: melanin, redness, tint, roughness, white_amount, color, ramps (as exported).
    hair_color: dict[str, Any] = field(default_factory=dict)
    # Garments: color, stitch_color, normal_strength, micro_normal_strength, micro_scale, macro_scale.
    fabric: dict[str, Any] = field(default_factory=dict)

    @property
    def hidden(self) -> bool:
        return self.profile == "hidden"

    def texture(self, role: str) -> Texture | None:
        return next((texture for texture in self.textures if texture.role == role), None)


@dataclass(frozen=True)
class MeshEntry:
    """One DNA mesh: which DNA (``head`` or ``body``), its index in that DNA, and its material."""

    dna: str
    mesh_index: int
    lod: int
    material: str
    profile: str

    @property
    def hidden(self) -> bool:
        return self.profile == "hidden"


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    type: str
    path: Path
    role: str
    attach_to: str
    materials: tuple[str, ...] = ()
    region: str = ""  # grooms: scalp, brows, lashes, beard or fuzz (the first material's region)
    # Grooms: Unreal's component settings, e.g. width (cm, the width override), root_scale, tip_scale.
    groom: dict[str, Any] = field(default_factory=dict)

    @property
    def is_groom(self) -> bool:
        return self.type == "alembic"

    @property
    def is_clothing(self) -> bool:
        return self.type == "fbx"


@dataclass(frozen=True)
class Assembly:
    root: Path
    name: str
    schema_version: int
    dna: dict[str, Path]
    dna_sha256: dict[str, str]
    meshes: tuple[MeshEntry, ...]
    materials: dict[str, Material]
    components: tuple[Component, ...]
    required_capabilities: tuple[str, ...]
    diagnostics: tuple[str, ...]
    rig_capabilities: dict[str, dict[str, Any]] = field(default_factory=dict)
    # DNA role -> its Geometry/<role>.json (per-mesh extras such as the faces under the clothes).
    geometry: dict[str, Path] = field(default_factory=dict)

    def grooms(self) -> list[Component]:
        return [component for component in self.components if component.is_groom]

    def clothing(self) -> list[Component]:
        return [component for component in self.components if component.is_clothing]

    def unknown_capabilities(self) -> list[str]:
        return [name for name in self.required_capabilities if name not in KNOWN_CAPABILITIES]

    def hidden_meshes(self, dna: str) -> list[MeshEntry]:
        return [mesh for mesh in self.meshes if mesh.dna == dna and mesh.hidden]

    def mesh_material(self, dna: str, mesh_index: int) -> Material | None:
        for mesh in self.meshes:
            if mesh.dna == dna and mesh.mesh_index == mesh_index:
                return self.materials.get(mesh.material)
        return None


def _require(data: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise ManifestError(f'{where} has no "{key}"')
    return data[key]


def resolve(root: Path, relative: str) -> Path:
    """The file ``relative`` names inside ``root``. Absolute paths and ``..`` escapes are refused."""
    if not isinstance(relative, str) or not relative:
        raise ManifestError(f"Bad path in the manifest: {relative!r}")
    posix = PurePosixPath(relative.replace("\\", "/"))
    if posix.is_absolute() or ":" in posix.parts[0] or ".." in posix.parts:
        raise ManifestError(f'The manifest path "{relative}" points outside the export folder')
    return root.joinpath(*posix.parts)


def _texture(root: Path, data: Mapping[str, Any], where: str) -> Texture:
    color_space = _require(data, "color_space", where)
    if color_space not in COLOR_SPACES:
        raise ManifestError(f'{where}: unknown colour space "{color_space}"')
    return Texture(
        role=str(_require(data, "role", where)),
        path=resolve(root, _require(data, "path", where)),
        color_space=color_space,
    )


def _material(root: Path, data: Mapping[str, Any]) -> Material:
    name = str(_require(data, "name", "A material"))
    where = f'Material "{name}"'
    textures = tuple(_texture(root, texture, where) for texture in data.get("textures", []))
    return Material(
        name=name,
        type=str(_require(data, "type", where)),
        slot=str(data.get("slot", "")),
        display_name=str(data.get("display_name", "")),
        profile=str(data.get("profile", "creator")),
        textures=textures,
        hair_color=dict(data.get("hair_color") or {}),
        fabric=dict(data.get("fabric") or {}),
    )


def load_manifest(path: Path) -> Assembly:
    """Read and check ``CharacterAssemblyManifest.json`` (or the folder that holds it)."""
    path = Path(path)
    if path.is_dir():
        path = path / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ManifestError(f"Can't read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ManifestError(f"{path.name} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ManifestError(f"{path.name} is not a manifest object")
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ManifestError(
            f"{path.name} has schema version {version!r}; only version {SCHEMA_VERSION} is supported. "
            "Re-export the character with a current Interchange"
        )
    root = path.parent
    dna_paths = _require(data, "dna", "The manifest")
    dna = {role: resolve(root, dna_paths[role]) for role in DNA_ROLES if dna_paths.get(role)}
    if "head" not in dna:
        raise ManifestError("The manifest names no head DNA")

    materials = {m.name: m for m in (_material(root, entry) for entry in data.get("materials", []))}
    meshes: list[MeshEntry] = []
    dna_sha256: dict[str, str] = {}
    geometry_paths: dict[str, Path] = {}
    for geometry in data.get("dna_geometry", []):
        role = str(_require(geometry, "role", "A dna_geometry entry"))
        if geometry.get("dna_sha256"):
            dna_sha256[role] = str(geometry["dna_sha256"])
        if geometry.get("path"):
            geometry_paths[role] = resolve(root, geometry["path"])
        for mesh in geometry.get("meshes", []):
            material = mesh.get("material", {})
            meshes.append(
                MeshEntry(
                    dna=role,
                    mesh_index=int(_require(mesh, "mesh_index", f"A {role} mesh")),
                    lod=int(mesh.get("lod", 0)),
                    material=str(material.get("name", "")),
                    profile=str(material.get("profile", "creator")),
                )
            )
    components = tuple(
        Component(
            id=str(component.get("id", "")),
            name=str(component.get("name", "")),
            type=str(_require(component, "type", "A component")),
            path=resolve(root, _require(component, "path", "A component")),
            role=str(component.get("role", "")),
            attach_to=str(component.get("attach_to", "")),
            materials=tuple(str(m.get("name", "")) for m in component.get("materials", [])),
            region=str(next((m.get("region", "") for m in component.get("materials", [])), "")),
            groom=dict(component.get("groom") or {}),
        )
        for component in data.get("components", [])
    )
    rigs = data.get("rigs", {})
    return Assembly(
        root=root,
        name=str(data.get("name", root.name)),
        schema_version=version,
        dna=dna,
        dna_sha256=dna_sha256,
        geometry=geometry_paths,
        meshes=tuple(meshes),
        materials=materials,
        components=components,
        required_capabilities=tuple(str(c) for c in data.get("required_capabilities", [])),
        diagnostics=tuple(str(d) for d in data.get("diagnostics", [])),
        rig_capabilities={role: dict(rig.get("capabilities", {})) for role, rig in rigs.items()},
    )


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def dna_mismatches(assembly: Assembly) -> list[str]:
    """DNA files whose SHA-256 differs from the manifest's (edited or swapped since the export)."""
    return [
        f"{role}.dna differs from the exported file (edited since the export?)"
        for role, expected in assembly.dna_sha256.items()
        if role in assembly.dna and assembly.dna[role].is_file() and file_sha256(assembly.dna[role]) != expected
    ]


@dataclass(frozen=True)
class TextureStatus:
    """What happened (or will happen) to one texture of one material.

    ``status`` is ``connected``, ``loaded`` (image set up, not connected), ``missing`` (no file),
    ``deferred`` (a later slice imports it), ``hidden`` (its mesh isn't rendered), ``skipped``
    (materials weren't imported) or ``failed``. ``material`` is the manifest's material name,
    ``label`` its readable name (the Unreal material instance).
    """

    material: str
    label: str
    material_type: str
    role: str
    path: Path | None
    color_space: str
    status: str
    detail: str


def _label(material: Material) -> str:
    return material.display_name or material.name


def _dna_material_names(assembly: Assembly) -> list[str]:
    names: list[str] = []
    for mesh in assembly.meshes:
        if mesh.material in assembly.materials and mesh.material not in names:
            names.append(mesh.material)
    return names


def texture_plan(assembly: Assembly) -> list[TextureStatus]:
    """For every texture in the manifest: where Slice 1 connects it, or why it doesn't."""
    plan: list[TextureStatus] = []
    for name in _dna_material_names(assembly):
        material = assembly.materials[name]
        connected = CONNECTED_ROLES.get(material.type, {})
        for texture in material.textures:
            status, detail = "loaded", ""
            if material.hidden:
                status, detail = "hidden", "the mesh is not rendered"
            elif not texture.exists:
                status, detail = "missing", "file not found"
            elif texture.role in connected:
                status, detail = "connected", connected[texture.role]
            elif (material.type, texture.role) in UNCONNECTED_ROLES:
                detail = UNCONNECTED_ROLES[material.type, texture.role]
            elif material.type in CONNECTED_ROLES:
                detail = f'unknown role for a "{material.type}" material'
            else:
                detail = f'no shader for "{material.type}" materials yet'
            plan.append(
                TextureStatus(
                    name,
                    _label(material),
                    material.type,
                    texture.role,
                    texture.path,
                    texture.color_space,
                    status,
                    detail,
                )
            )
    dna_names = set(_dna_material_names(assembly))
    for component in assembly.components:
        status, reason = (
            "deferred",
            DEFERRED_COMPONENTS.get(component.type, f'"{component.type}" components are not supported'),
        )
        if component.is_groom:
            status, reason = "loaded", GROOM_UNCONNECTED
        for name in component.materials:
            material = assembly.materials.get(name)
            if material is None or name in dna_names:
                continue
            if component.is_clothing:
                connected = CONNECTED_ROLES.get(material.type, {})
                plan.extend(
                    TextureStatus(
                        name,
                        _label(material),
                        material.type,
                        texture.role,
                        texture.path,
                        texture.color_space,
                        "missing" if not texture.exists else "connected" if texture.role in connected else "loaded",
                        "file not found"
                        if not texture.exists
                        else connected.get(texture.role, f'unknown role for a "{material.type}" material'),
                    )
                    for texture in material.textures
                )
                continue
            plan.extend(
                TextureStatus(
                    name,
                    _label(material),
                    material.type,
                    texture.role,
                    texture.path,
                    texture.color_space,
                    status if texture.exists else "missing",
                    reason if texture.exists else "file not found",
                )
                for texture in material.textures
            )
    return plan


def with_status(entry: TextureStatus, status: str, detail: str) -> TextureStatus:
    return replace(entry, status=status, detail=detail)


def format_report(
    assembly: Assembly,
    statuses: Iterable[TextureStatus],
    hidden_objects: Iterable[str] = (),
    warnings: Iterable[str] = (),
) -> str:
    """A plain-text report: counts, then every texture grouped by status."""
    statuses = list(statuses)
    counts = {status: sum(1 for entry in statuses if entry.status == status) for status in _STATUS_ORDER}
    lines = [
        f"Character assembly import: {assembly.name}",
        f"Manifest: {assembly.root / MANIFEST_NAME} (schema {assembly.schema_version})",
        "Textures: " + ", ".join(f"{counts[status]} {status}" for status in _STATUS_ORDER if counts[status]),
    ]
    warnings = list(warnings)
    if unknown := assembly.unknown_capabilities():
        warnings.append("Unknown required capabilities (may not import fully): " + ", ".join(unknown))
    warnings.extend(f"Exporter diagnostic: {message}" for message in assembly.diagnostics)
    lines.extend(f"WARNING: {message}" for message in warnings)
    hidden_objects = list(hidden_objects)
    if hidden_objects:
        lines.append(f"Hidden meshes (profile 'hidden'): {len(hidden_objects)}")
        lines.extend(f"  {name}" for name in hidden_objects)
    for status in _STATUS_ORDER:
        entries = [entry for entry in statuses if entry.status == status]
        if not entries:
            continue
        lines.append("")
        lines.append(f"[{status}]")
        for entry in entries:
            file_name = entry.path.name if entry.path else "-"
            detail = f": {entry.detail}" if entry.detail else ""
            lines.append(
                f"  {entry.label} ({entry.material_type}) {entry.role} = {file_name} [{entry.color_space}]{detail}"
            )
    return "\n".join(lines) + "\n"


_STATUS_ORDER = ("failed", "missing", "skipped", "connected", "loaded", "hidden", "deferred")
