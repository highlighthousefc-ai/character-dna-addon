"""Check the addon loads real OpenRigLogic bindings and can round-trip and evaluate a DNA.

Runs in a headless Blender (the ``bpy`` module or a Blender binary) with the staged bindings
already copied to ``src/addons/character_dna/bindings/<os>/<arch>/py313``:

    python scripts/ci/bindings_in_addon.py
    blender --background --factory-startup --python-exit-code 1 --python scripts/ci/bindings_in_addon.py

Uses a synthetic DNA (``tests_core/synthetic.py``), never Epic-owned files. Exits non-zero on failure.
"""

import sys
import tempfile

from pathlib import Path

import bpy


REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    sys.path.insert(0, str(REPO_ROOT / "src" / "addons"))
    sys.path.insert(0, str(REPO_ROOT / "tests_core"))
    import synthetic

    import character_dna

    from character_dna import bindings, dna_core

    print(f"Blender {bpy.app.version_string}, Python {sys.version.split()[0]}, {sys.executable}")
    print(f"Bindings folder: {bindings.combo_folder}")
    for module in (bindings.dna, bindings.riglogic):
        if getattr(module, "__is_fake__", False):
            raise RuntimeError(f"The addon fell back to a fake {module.__name__} module; bindings not loaded")
    leaked = sorted(name for name in ("dna", "riglogic") if name in sys.modules)
    print(f"Bare binding names left in sys.modules: {leaked or 'none'}")

    character_dna.register()
    try:
        with tempfile.TemporaryDirectory() as folder:
            source = synthetic.write_jaw_rig(bindings.dna, Path(folder) / "jaw.dna")
            copy = Path(folder) / "copy.dna"
            dna_core.write_copy(dna_core.load(source), copy)
            if copy.read_bytes() != source.read_bytes():
                raise RuntimeError("Round trip is not byte-identical")
            reader = dna_core.load(copy)
            for jaw_open, expected in ((0.0, 0.0), (0.5, 12.5), (1.0, 25.0)):
                rotation = synthetic.jaw_rotation_x(bindings.riglogic, reader, jaw_open)
                print(f"jawOpen={jaw_open} -> jaw rotation X = {rotation}")
                if abs(rotation - expected) > 1e-4:
                    raise RuntimeError(f"Expected {expected}, got {rotation}")
    finally:
        character_dna.unregister()
    print("BINDINGS_IN_ADDON_OK")


if __name__ == "__main__":
    main()
