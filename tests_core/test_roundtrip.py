"""Round-trip a synthetic DNA through ``dna_core`` (needs the OpenRigLogic bindings)."""

from pathlib import Path
from types import ModuleType

import dna_core
import pytest
import synthetic


def test_load_reads_synthetic_dna(synthetic_dna_file: Path):
    reader = dna_core.load(synthetic_dna_file)
    assert reader.getName() == "synthetic_jaw"
    assert reader.getMetaDataValue("source") == "tests_core"
    assert reader.getJointCount() == 2
    assert reader.getJointName(1) == synthetic.JAW_JOINT
    assert reader.getRawControlName(0) == synthetic.JAW_OPEN_CONTROL


def test_write_copy_is_byte_identical(synthetic_dna_file: Path, tmp_path: Path):
    copy_path = tmp_path / "copy.dna"
    dna_core.write_copy(dna_core.load(synthetic_dna_file), copy_path)
    assert copy_path.read_bytes() == synthetic_dna_file.read_bytes()


def test_load_missing_file_raises(dna: ModuleType, tmp_path: Path):  # noqa: ARG001
    with pytest.raises(dna_core.DnaReadError):
        dna_core.load(tmp_path / "missing.dna")
