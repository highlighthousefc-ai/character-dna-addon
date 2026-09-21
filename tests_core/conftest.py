"""Tests for the pure ``dna_core`` layer. These run with plain CPython 3.13, without Blender.

``dna_core`` is imported as a top-level package from ``src/addons/character_dna`` so the addon's
``__init__`` (which imports ``bpy``) never runs. OpenRigLogic bindings are found either on
``PYTHONPATH`` or in ``CHARACTER_DNA_BINDINGS_DIR/<os>/<arch>/py313``; tests that need them are
skipped when they are missing.
"""

import os
import platform
import sys

from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
ADDON_FOLDER = REPO_ROOT / "src" / "addons" / "character_dna"
DNA_CORE_FOLDER = ADDON_FOLDER / "dna_core"

sys.path.insert(0, str(ADDON_FOLDER))

_bindings_dir = os.environ.get("CHARACTER_DNA_BINDINGS_DIR")
if _bindings_dir:
    _os_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
    _arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    sys.path.insert(0, str(Path(_bindings_dir) / _os_name / _arch / "py313"))


@pytest.fixture
def dna() -> ModuleType:
    """Epic's ``dna`` bindings, or skip the test if they aren't available."""
    return pytest.importorskip("dna", reason="OpenRigLogic dna bindings not found")


@pytest.fixture
def synthetic_dna_file(dna: ModuleType, tmp_path: Path) -> Path:
    """A tiny DNA file built in memory, so no Epic-owned DNA is needed."""
    path = tmp_path / "synthetic.dna"
    stream = dna.FileStream(str(path), dna.FileStream.AccessMode_Write, dna.FileStream.OpenMode_Binary)
    writer = dna.BinaryStreamWriter(stream)
    writer.setName("synthetic")
    writer.setMetaData("source", "tests_core")
    writer.setLODCount(1)
    writer.setJointName(0, "root")
    writer.setJointName(1, "child")
    writer.setJointHierarchy([0, 0])
    writer.write()
    assert dna.Status.isOk(), dna.Status.get().message
    del writer, stream
    return path
