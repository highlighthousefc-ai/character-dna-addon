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


def main() -> None:
    print(f"Blender {bpy.app.version_string}, Python {sys.version.split()[0]}")
    user_resources = os.environ.get("BLENDER_USER_RESOURCES", "")
    print(f"BLENDER_USER_RESOURCES={user_resources}")
    if not user_resources:
        fail("Run this with BLENDER_USER_RESOURCES set to a throwaway profile")

    source_paths = [entry for entry in sys.path if str(REPO_ROOT) in entry]
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
