"""Replacing one blend shape target in a DNA file: no-op commits, single-target edits, backups."""

import filecmp

from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest
import synthetic

from dna_core import blend_shapes as bs, load, write_copy


@pytest.fixture
def dna_file(dna: ModuleType, tmp_path: Path) -> Path:
    # Normalise through one setFrom round trip, as every committed file is written that way.
    source = synthetic.write_corrective_rig(dna, tmp_path / "source.dna")
    path = tmp_path / "head.dna"
    write_copy(load(source), path)
    return path


def _all_targets(reader: Any) -> list[tuple[list[int], list[tuple[float, float, float]]]]:
    targets = []
    for target in range(reader.getBlendShapeTargetCount(0)):
        indices, deltas = bs.target_deltas(reader, 0, target)
        targets.append((indices.tolist(), deltas.tolist()))
    return targets


def test_lookup(dna_file: Path):
    reader = load(dna_file)
    mesh = bs.mesh_index(reader, synthetic.CORRECTIVE_MESH)
    assert mesh == 0
    assert bs.target_index(reader, mesh, 1) == 1
    assert bs.target_index(reader, mesh, 99) is None
    with pytest.raises(KeyError):
        bs.mesh_index(reader, "teeth_lod0_mesh")
    indices, deltas = bs.target_deltas(reader, 0, 1)
    assert indices.tolist() == [0, 3]
    np.testing.assert_allclose(deltas, [[0.1, 0.2, 0.3], [0.0, 0.0, -1.0]], rtol=0, atol=1e-6)


def test_unedited_commit_is_byte_identical(dna_file: Path, tmp_path: Path):
    before = dna_file.read_bytes()
    reader = load(dna_file)
    original = bs.target_deltas(reader, 0, 1)
    # Blender hands back float32 metres: simulate that round trip's noise on every vertex.
    noisy = bs.dense(*original, len(synthetic.CORRECTIVE_VERTICES)) + 3e-6
    indices, deltas = bs.merge(original, noisy)
    bs.release(reader)
    backup = bs.commit_target(dna_file, 0, 1, indices, deltas)
    assert dna_file.read_bytes() == before
    assert backup.read_bytes() == before
    assert backup.parent == tmp_path / "backups"


def test_edit_changes_only_that_target(dna_file: Path):
    reader = load(dna_file)
    before = _all_targets(reader)
    original = bs.target_deltas(reader, 0, 1)
    edited = bs.dense(*original, len(synthetic.CORRECTIVE_VERTICES))
    edited[3] += (0.0, 0.1, 0.0)  # move one vertex already in the target
    edited[2] = (0.25, 0.0, 0.0)  # and one that wasn't
    edited[0] = 0.0  # and zero one out
    bs.release(reader)
    bs.commit_target(dna_file, 0, 1, *bs.merge(original, edited))
    after = _all_targets(load(dna_file))
    assert after[0] == before[0]
    assert after[2] == before[2]
    assert after[1][0] == [3, 2]  # vertex 0 dropped, 3 kept in place, 2 appended
    np.testing.assert_allclose(after[1][1], [[0.0, 0.1, -1.0], [0.25, 0.0, 0.0]], rtol=0, atol=1e-6)


def test_merge_keeps_unchanged_values_exactly():
    original = (np.array([1, 4]), np.array([[0.1, 0.2, 0.3], [1.0, 0.0, 0.0]], dtype=np.float32))
    edited = bs.dense(*original, 6)
    edited[1] += 1e-6  # float noise: keep the stored value exactly
    edited[5] = (0.0, 0.0, 0.5)  # a real change
    indices, deltas = bs.merge(original, edited)
    assert indices.tolist() == [1, 4, 5]
    assert deltas[0].tolist() == original[1][0].tolist()
    assert deltas[2].tolist() == pytest.approx([0.0, 0.0, 0.5])


def test_failed_write_leaves_the_file_untouched(dna_file: Path, monkeypatch: pytest.MonkeyPatch):
    before = dna_file.read_bytes()

    def fail(*_args: object, **_kwargs: object) -> None:
        raise bs.DnaWriteError("disk full")

    monkeypatch.setattr(bs, "write_with_target", fail)
    with pytest.raises(bs.DnaWriteError):
        bs.commit_target(dna_file, 0, 1, np.array([0]), np.zeros((1, 3)))
    assert dna_file.read_bytes() == before
    assert sorted(p.name for p in dna_file.parent.iterdir() if p.name.startswith(".head")) == []


def test_backup_names_never_collide(dna_file: Path):
    first = bs.backup_path(dna_file)
    first.parent.mkdir()
    first.write_bytes(b"")
    assert bs.backup_path(dna_file) != first
    assert filecmp.cmp(dna_file, dna_file)


def test_merge_keeps_the_stored_vertex_order():
    """MetaHuman targets aren't stored sorted; reordering alone would change the file's bytes."""
    original = (np.array([4, 1, 3]), np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32))
    edited = bs.dense(*original, 6)
    unchanged = bs.merge(original, edited)
    assert unchanged[0].tolist() == [4, 1, 3]
    assert np.array_equal(unchanged[1], original[1])
    edited[1] = 0.0  # drop one
    edited[0] = (0.5, 0.0, 0.0)  # add one
    indices, _ = bs.merge(original, edited)
    assert indices.tolist() == [4, 3, 0]
