"""``dna_core`` must never import Blender modules (CLAUDE.md rule)."""

import ast
import subprocess
import sys

from pathlib import Path

from conftest import ADDON_FOLDER, DNA_CORE_FOLDER


FORBIDDEN = {"bpy", "bmesh", "mathutils", "bpy_extras", "gpu"}


def _imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_dna_core_source_has_no_blender_imports():
    offenders = {
        path.name: sorted(_imported_roots(path) & FORBIDDEN)
        for path in DNA_CORE_FOLDER.rglob("*.py")
        if _imported_roots(path) & FORBIDDEN
    }
    assert not offenders, f"dna_core imports Blender modules: {offenders}"


def test_importing_dna_core_never_loads_bpy():
    """Import every dna_core module in a fresh interpreter where importing bpy raises."""
    script = f"""
import importlib, pkgutil, sys

class BlockBlender:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {sorted(FORBIDDEN)!r}:
            raise ImportError(f"dna_core must not import {{name}}")
        return None

sys.meta_path.insert(0, BlockBlender())
sys.path.insert(0, {str(ADDON_FOLDER)!r})
import dna_core
for module in pkgutil.walk_packages(dna_core.__path__, "dna_core."):
    importlib.import_module(module.name)
assert not {{"bpy", "bmesh", "mathutils"}} & set(sys.modules)
print("OK")
"""
    result = subprocess.run(  # noqa: S603 (runs our own fixed script with this interpreter)
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
