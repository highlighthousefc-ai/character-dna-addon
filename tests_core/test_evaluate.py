"""Evaluate a synthetic rig with RigLogic after a ``dna_core`` round trip (needs the bindings)."""

from pathlib import Path
from types import ModuleType

import dna_core
import pytest
import synthetic


@pytest.mark.parametrize(("jaw_open", "expected"), [(0.0, 0.0), (0.5, 12.5), (1.0, 25.0)])
def test_jaw_open_drives_jaw_rotation(
    riglogic: ModuleType, synthetic_dna_file: Path, tmp_path: Path, jaw_open: float, expected: float
):
    # Evaluate the written-back copy, so this covers read -> write -> read -> evaluate.
    copy_path = tmp_path / "copy.dna"
    dna_core.write_copy(dna_core.load(synthetic_dna_file), copy_path)
    reader = dna_core.load(copy_path)
    assert synthetic.jaw_rotation_x(riglogic, reader, jaw_open) == pytest.approx(expected)


def test_evaluation_is_deterministic(riglogic: ModuleType, synthetic_dna_file: Path):
    reader = dna_core.load(synthetic_dna_file)
    first = synthetic.jaw_rotation_x(riglogic, reader, 0.7)
    second = synthetic.jaw_rotation_x(riglogic, reader, 0.7)
    assert first == second
