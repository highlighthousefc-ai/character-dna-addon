"""Write DNA data back to disk."""

from pathlib import Path
from typing import Any

from ._bindings import dna_module


class DnaWriteError(RuntimeError):
    """Raised when a DNA file can't be written."""


def write_copy(reader: Any, path: str | Path) -> None:
    """Write everything ``reader`` holds to ``path`` unchanged (a round trip)."""
    dna = dna_module()
    path = Path(path)
    stream = dna.FileStream(str(path), dna.FileStream.AccessMode_Write, dna.FileStream.OpenMode_Binary)
    writer = dna.BinaryStreamWriter(stream)
    writer.setFrom(reader)
    writer.write()
    if not dna.Status.isOk():
        raise DnaWriteError(f'Could not write "{path}": {dna.Status.get().message}')
    # Release the writer before its stream so the file is flushed and closed.
    del writer, stream
