"""Read and replace one blend shape target's deltas in a DNA file.

Everything here is in the DNA's own space (Maya Y-up, the DNA's translation unit). Converting to
and from Blender (Z-up, metres) is the caller's job. A commit writes the whole DNA again with only
one target changed, via ``BinaryStreamWriter.setFrom``: a ``setFrom`` round trip of Ada's head is
byte-identical to the source (docs/FINDINGS), so an unchanged target leaves an identical file.
"""

import os
import shutil
import tempfile
import time

from pathlib import Path
from typing import Any

import numpy as np

from ._bindings import dna_module
from .reader import load
from .writer import DnaWriteError


# Deltas closer than this to the stored ones (in DNA units, cm for MetaHumans) count as unchanged:
# Blender keeps shape keys as float32 metres, so an unedited key comes back a few 1e-6 cm off.
UNCHANGED_TOLERANCE = 1e-4


def mesh_index(reader: Any, name: str) -> int:
    for index in range(reader.getMeshCount()):
        if reader.getMeshName(index) == name:
            return index
    raise KeyError(f'Mesh "{name}" is not in the DNA')


def target_index(reader: Any, mesh: int, channel: int) -> int | None:
    """The target on ``mesh`` that ``channel`` drives, or ``None`` when it has none there."""
    for target in range(reader.getBlendShapeTargetCount(mesh)):
        if reader.getBlendShapeChannelIndex(mesh, target) == channel:
            return target
    return None


def target_deltas(reader: Any, mesh: int, target: int) -> tuple[np.ndarray, np.ndarray]:
    """A target's sparse ``(vertex_indices, deltas)``: ``int64 (n,)`` and ``float32 (n, 3)``."""
    indices = np.asarray(reader.getBlendShapeTargetVertexIndices(mesh, target), dtype=np.int64)
    deltas = np.empty((len(indices), 3), dtype=np.float32)
    if len(indices):
        deltas[:, 0] = reader.getBlendShapeTargetDeltaXs(mesh, target)
        deltas[:, 1] = reader.getBlendShapeTargetDeltaYs(mesh, target)
        deltas[:, 2] = reader.getBlendShapeTargetDeltaZs(mesh, target)
    return indices, deltas


def dense(indices: np.ndarray, deltas: np.ndarray, vertex_count: int) -> np.ndarray:
    """Sparse deltas as a ``float64 (vertex_count, 3)`` array, zero where the target is silent."""
    out = np.zeros((vertex_count, 3), dtype=np.float64)
    out[indices] = deltas
    return out


def merge(
    original: tuple[np.ndarray, np.ndarray],
    edited: np.ndarray,
    tolerance: float = UNCHANGED_TOLERANCE,
) -> tuple[np.ndarray, np.ndarray]:
    """Sparse deltas for an edited target that keep every unedited vertex bit-for-bit.

    ``edited`` is the full ``(vertex_count, 3)`` delta array read back from Blender. A vertex whose
    edited delta is within ``tolerance`` of the stored one keeps the stored value (and stays in or out
    of the target as before); a vertex that really changed takes the edited value, and is dropped
    only if it became zero within ``tolerance``.

    Vertices already in the target keep their stored order (MetaHuman DNAs don't store them sorted,
    and reordering alone would change the file's bytes); newly added vertices follow, ascending.
    """
    indices, deltas = original
    stored = dense(indices, deltas, len(edited))
    changed = np.abs(edited - stored).max(axis=1) > tolerance
    member = np.zeros(len(edited), dtype=bool)
    member[indices] = True
    keep = np.where(changed, np.abs(edited).max(axis=1) > tolerance, member)
    values = np.where(changed[:, None], edited, stored).astype(np.float32)
    existing = indices[keep[indices]]
    added = np.flatnonzero(keep & ~member)
    keep_indices = np.concatenate([existing, added]).astype(np.int64)
    # float32 -> float64 -> float32 is exact, so unchanged vertices keep their stored bits.
    return keep_indices, values[keep_indices]


def write_with_target(
    reader: Any, path: str | Path, mesh: int, target: int, indices: np.ndarray, deltas: np.ndarray
) -> None:
    """Write all of ``reader`` to ``path`` with one target's deltas replaced."""
    dna = dna_module()
    stream = dna.FileStream(str(path), dna.FileStream.AccessMode_Write, dna.FileStream.OpenMode_Binary)
    writer = dna.BinaryStreamWriter(stream)
    writer.setFrom(reader)
    writer.setBlendShapeTargetVertexIndices(mesh, target, [int(index) for index in indices])
    writer.setBlendShapeTargetDeltas(mesh, target, np.asarray(deltas, dtype=np.float64).tolist())
    writer.write()
    if not dna.Status.isOk():
        raise DnaWriteError(f'Could not write "{path}": {dna.Status.get().message}')
    # Release the writer before its stream so the file is flushed and closed.
    del writer, stream


def backup_path(path: Path, folder: Path | None = None) -> Path:
    """``<folder or path's folder>/backups/<stem>.<timestamp>.dna``, never an existing file."""
    folder = (folder or path.parent / "backups").resolve()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    candidate = folder / f"{path.stem}.{stamp}{path.suffix}"
    counter = 1
    while candidate.exists():
        candidate = folder / f"{path.stem}.{stamp}-{counter}{path.suffix}"
        counter += 1
    return candidate


def commit_target(
    path: str | Path,
    mesh: int,
    target: int,
    indices: np.ndarray,
    deltas: np.ndarray,
    backup_folder: Path | None = None,
) -> Path:
    """Replace one target in the DNA at ``path``, in place, after backing the file up.

    The new DNA is written next to the original first and then swapped in with ``Path.replace``,
    so a failure leaves the original untouched. The reader used for the write is released before
    the swap: on Windows an open reader keeps the file locked. Callers must release their own
    readers of ``path`` first for the same reason. Returns the backup's path.
    """
    path = Path(path)
    backup = backup_path(path, backup_folder)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".dna", dir=path.parent)
    os.close(handle)
    try:
        reader = load(path)
        try:
            write_with_target(reader, temporary, mesh, target, indices, deltas)
        finally:
            release(reader)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return backup


def release(reader: Any) -> None:
    """Destroy a reader from :func:`dna_core.load`, then its stream, closing the file now.

    The bindings only destroy their C++ objects from ``__del__``; this does it deterministically,
    reader first because it points at the stream (the same order ``dna_io.release_dna_handle`` uses).
    """
    stream = getattr(reader, "_dna_core_stream", None)
    reader._dna_core_stream = None  # noqa: SLF001
    for handle in (reader, stream):
        instance = getattr(handle, "_instance", None)
        if instance is not None:
            type(handle).destroy(instance)
            handle._instance = None  # noqa: SLF001
        if getattr(handle, "_args", None):
            handle._args = ()  # noqa: SLF001
