"""Tests for the pure ``dna_core`` layer. These run with plain CPython 3.13, without Blender.

``dna_core`` is imported as a top-level package from ``src/addons/character_dna`` so the addon's
``__init__`` (which imports ``bpy``) never runs. OpenRigLogic bindings are found either on
``PYTHONPATH`` or in ``CHARACTER_DNA_BINDINGS_DIR/<os>/<arch>/py313``; tests that need them are
skipped when they are missing, unless ``CHARACTER_DNA_REQUIRE_BINDINGS=1`` makes that an error.
"""

import importlib
import os
import platform
import sys

from pathlib import Path
from types import ModuleType

import pytest
import synthetic


REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_FOLDER = REPO_ROOT / "src" / "addons" / "character_dna"
DNA_CORE_FOLDER = ADDON_FOLDER / "dna_core"

sys.path.insert(0, str(ADDON_FOLDER))

_bindings_dir = os.environ.get("CHARACTER_DNA_BINDINGS_DIR")
if _bindings_dir:
    _os_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
    _arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    sys.path.insert(0, str(Path(_bindings_dir) / _os_name / _arch / "py313"))


def _bindings_module(name: str) -> ModuleType:
    """Import a bindings module, or skip -- unless CI says the bindings must be present."""
    if os.environ.get("CHARACTER_DNA_REQUIRE_BINDINGS") == "1":
        return importlib.import_module(name)
    return pytest.importorskip(name, reason="OpenRigLogic bindings not found")


@pytest.fixture
def dna() -> ModuleType:
    """Epic's ``dna`` bindings."""
    return _bindings_module("dna")


@pytest.fixture
def riglogic(dna: ModuleType) -> ModuleType:  # noqa: ARG001 (dna must load first)
    """Epic's ``riglogic`` bindings."""
    return _bindings_module("riglogic")


@pytest.fixture
def synthetic_dna_file(dna: ModuleType, tmp_path: Path) -> Path:
    """A tiny jaw rig built in memory, so no Epic-owned DNA is needed."""
    return synthetic.write_jaw_rig(dna, tmp_path / "synthetic.dna")
