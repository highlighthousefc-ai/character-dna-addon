"""Check an installed ``character_dna`` extension loads and works with no path hacks.

Run after ``blender --command extension install-file -r user_default -e <zip>`` in a throwaway
profile (``BLENDER_USER_RESOURCES`` pointing at an empty folder), *without* ``--factory-startup``
so the installed extension is enabled from the saved preferences:

    blender --background --python-exit-code 1 --python scripts/ci/installed_extension_check.py

It never touches ``sys.path``: the addon, its bindings and its wheel must all come from the
installed extension. The synthetic-DNA helper is loaded by file path for the same reason.
Exits non-zero on failure.
"""

import importlib
import importlib.util
import os
import sys
import tempfile

from pathlib import Path
from types import ModuleType

import addon_utils
import bpy


MODULE = "bl_ext.user_default.character_dna"
REPO_ROOT = Path(__file__).resolve().parents[2]


def fail(message: str) -> None:
    raise RuntimeError(message)


def load_synthetic() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_synthetic", REPO_ROOT / "tests_core" / "synthetic.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_blend_shape_import(synthetic: ModuleType, bindings: ModuleType, dna_core: ModuleType, folder: Path) -> None:
    """Import a synthetic DNA's blend shapes onto a Blender mesh and check every key's deltas."""
    dna_io = importlib.import_module(f"{MODULE}.dna_io")
    reader = dna_core.load(synthetic.write_blend_shape_mesh(bindings.dna, folder / "shapes.dna"))
    centimetres = 0.01

    def to_blender(x: float, y: float, z: float) -> tuple[float, float, float]:
        return (x * centimetres, -z * centimetres, y * centimetres)  # Y-up cm -> Z-up m (+90 deg about X)

    mesh = bpy.data.meshes.new("ci_shapes")
    mesh.from_pydata([to_blender(*vertex) for vertex in synthetic.BLEND_SHAPE_VERTICES], [], [(0, 1, 2)])
    mesh_object = bpy.data.objects.new("ci_shapes", mesh)
    for _ in range(2):  # a second import must replace the keys, not stack duplicates
        created = dna_io.import_blend_shapes(mesh_object, reader, 0, synthetic.BLEND_SHAPE_MESH, centimetres)
    blocks = mesh_object.data.shape_keys.key_blocks
    names = [block.name for block in blocks]
    channels = synthetic.BLEND_SHAPE_TARGETS
    expected = ["Basis"] + [dna_core.shape_key_name(synthetic.BLEND_SHAPE_MESH, channel) for channel in channels]
    print(f"Blend shapes imported: {created} -> {names}")
    if created != len(channels) or names != expected:
        fail(f"Expected shape keys {expected}")
    for block, deltas in zip(list(blocks)[1:], channels.values(), strict=True):
        for index, basis in enumerate(blocks[0].data):
            want = to_blender(*deltas.get(index, (0.0, 0.0, 0.0)))
            got = block.data[index].co - basis.co
            if max(abs(g - w) for g, w in zip(got, want, strict=True)) > 1e-6:
                fail(f"{block.name} vertex {index}: delta {tuple(got)} != {want}")
        if block.value != 0.0 or not block.lock_shape:
            fail(f"{block.name} should start at 0 and be locked")
    bpy.data.objects.remove(mesh_object)
    bpy.data.meshes.remove(mesh)


class _StandInCharacter(dict):
    """Just the attributes ``missing_addon_notice.ensure`` reads from a rig instance."""

    def __init__(self, name: str, head_mesh: bpy.types.Object) -> None:
        super().__init__()
        self.name = name
        self.head_mesh = head_mesh


def check_missing_addon_notice() -> None:
    """The notice a saved file shows without the add-on: built, placed above the head, hidden."""
    notice_module = importlib.import_module(f"{MODULE}.missing_addon_notice")
    mesh = bpy.data.meshes.new("ci_head")
    mesh.from_pydata([(-0.1, -0.1, 1.5), (0.1, 0.1, 1.8), (0.1, -0.1, 1.5)], [], [(0, 1, 2)])
    head = bpy.data.objects.new("ci_head", mesh)
    notice = notice_module.ensure(_StandInCharacter("ci", head))
    print(f"Missing add-on notice: {notice.name} at {tuple(round(v, 3) for v in notice.location)}")
    if "ci" not in notice.data.body or not notice.data.materials or not notice.hide_render:
        fail("The missing add-on notice is incomplete")
    if notice.location.z <= 1.8 or abs(notice.location.x + 0.1) > 1e-6:
        fail("The missing add-on notice is not above the head")
    tree = notice.data.materials[0].node_tree
    if sorted(node.type for node in tree.nodes) != ["EMISSION", "OUTPUT_MATERIAL"] or len(tree.links) != 1:
        fail("The missing add-on notice material is not emission -> output")
    if notice_module.ensure(_StandInCharacter("ci", head)) != notice:
        fail("A second ensure() must reuse the notice")
    notice_module.set_visible(True)
    if notice.hide_viewport:
        fail("set_visible(True) did not show the notice")
    notice_module.set_visible(False)
    bpy.data.objects.remove(notice)
    bpy.data.objects.remove(head)
    bpy.data.meshes.remove(mesh)


def main() -> None:
    print(f"Blender {bpy.app.version_string}, Python {sys.version.split()[0]}")
    user_resources = os.environ.get("BLENDER_USER_RESOURCES", "")
    print(f"BLENDER_USER_RESOURCES={user_resources}")
    if not user_resources:
        fail("Run this with BLENDER_USER_RESOURCES set to a throwaway profile")

    # In CI the downloaded Blender lives inside the checkout, so ignore Blender's own paths
    # (everything under the folder holding its versioned "5.x" resources).
    blender_root = Path(bpy.utils.resource_path("LOCAL")).parent
    source_paths = [
        entry
        for entry in sys.path
        if Path(entry).is_relative_to(REPO_ROOT) and not Path(entry).is_relative_to(blender_root)
    ]
    if source_paths:
        fail(f"sys.path points into the source checkout: {source_paths}")

    enabled = [module.__name__ for module in addon_utils.modules() if addon_utils.check(module.__name__)[1]]
    print(f"Enabled add-ons: {enabled}")
    if MODULE not in enabled:
        fail(f"{MODULE} is not enabled")

    addon = importlib.import_module(MODULE)
    addon_folder = Path(addon.__file__).parent
    print(f"Extension folder: {addon_folder}")
    if not addon_folder.is_relative_to(Path(user_resources)):
        fail("The extension is not loaded from the throwaway profile")

    bindings = importlib.import_module(f"{MODULE}.bindings")
    dna_core = importlib.import_module(f"{MODULE}.dna_core")
    print(f"Bindings folder: {bindings.combo_folder}")
    for module in (bindings.dna, bindings.riglogic):
        if getattr(module, "__is_fake__", False):
            fail(f"The extension fell back to a fake {module.__name__} module")
    if not Path(bindings.combo_folder).is_relative_to(addon_folder):
        fail("Bindings were not loaded from inside the installed extension")
    leaked = sorted(name for name in ("dna", "riglogic") if name in sys.modules)
    if leaked:
        fail(f"Bare binding modules leaked into sys.modules: {leaked}")

    import ufbx  # from the pyufbx platform wheel, installed by Blender into the profile

    ufbx_folder = Path(ufbx.__file__).parent
    print(f"ufbx (pyufbx wheel) from: {ufbx_folder}")
    if not ufbx_folder.is_relative_to(Path(user_resources)):
        fail("ufbx was not installed into the throwaway profile")
    print(f"Registered operators: {len(dir(bpy.ops.character_dna))}")

    synthetic = load_synthetic()
    with tempfile.TemporaryDirectory() as folder:
        source = synthetic.write_jaw_rig(bindings.dna, Path(folder) / "jaw.dna")
        copy = Path(folder) / "copy.dna"
        dna_core.write_copy(dna_core.load(source), copy)
        if copy.read_bytes() != source.read_bytes():
            fail("Round trip is not byte-identical")
        reader = dna_core.load(copy)
        for jaw_open, expected in ((0.0, 0.0), (0.5, 12.5), (1.0, 25.0)):
            rotation = synthetic.jaw_rotation_x(bindings.riglogic, reader, jaw_open)
            print(f"jawOpen={jaw_open} -> jaw rotation X = {rotation}")
            if abs(rotation - expected) > 1e-4:
                fail(f"Expected {expected}, got {rotation}")
        check_blend_shape_import(synthetic, bindings, dna_core, Path(folder))
    check_missing_addon_notice()
    # Blender's own policy check (shown in the Extensions UI): flags extensions that add their
    # folders to sys.path or load bundled scripts as top-level modules. Private API, Blender 4.2+.
    addon_utils._is_first_reset()  # noqa: SLF001
    policy_warnings = addon_utils._extensions_warnings_get().get(MODULE, [])  # noqa: SLF001
    print(f"Extension policy warnings: {policy_warnings or 'none'}")
    if policy_warnings:
        fail(f"Blender reports policy violations: {policy_warnings}")
    print("INSTALLED_EXTENSION_OK")


if __name__ == "__main__":
    main()
