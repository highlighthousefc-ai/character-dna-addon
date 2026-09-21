"""Register and unregister the addon in a headless Blender (the ``bpy`` module or a Blender binary).

Usage:
    python scripts/ci/register_smoke.py
    blender --background --factory-startup --python-exit-code 1 --python scripts/ci/register_smoke.py

Exits non-zero if registration or unregistration raises. Bindings are optional: without them the
addon still registers, and DNA import stays disabled.
"""

import sys

from pathlib import Path

import bpy


ADDONS_FOLDER = Path(__file__).resolve().parents[2] / "src" / "addons"


def main() -> None:
    sys.path.insert(0, str(ADDONS_FOLDER))
    import character_dna

    print(f"Blender {bpy.app.version_string}, Python {sys.version.split()[0]}")
    character_dna.register()
    operator_count = len(dir(bpy.ops.character_dna))
    if operator_count == 0:
        raise RuntimeError("No character_dna operators were registered.")
    print(f"Registered {operator_count} operators.")
    character_dna.unregister()
    print("Unregistered.")


if __name__ == "__main__":
    main()
