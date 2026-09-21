"""Load DNA files into OpenRigLogic readers."""

from pathlib import Path
from typing import Any

from ._bindings import dna_module


class DnaReadError(RuntimeError):
    """Raised when a DNA file can't be read."""


def load(path: str | Path, *, layer: str = "All") -> Any:
    """Read a DNA file and return a ``dna.BinaryStreamReader``.

    ``layer`` names a ``dna.DataLayer_*`` constant, e.g. ``"All"``, ``"Behavior"`` or
    ``"Geometry"``. The reader keeps its stream alive; release both together.
    """
    dna = dna_module()
    path = Path(path)
    if not path.is_file():
        raise DnaReadError(f'DNA file not found: "{path}"')

    stream = dna.FileStream(str(path), dna.FileStream.AccessMode_Read, dna.FileStream.OpenMode_Binary)
    reader = dna.BinaryStreamReader(stream, getattr(dna, f"DataLayer_{layer}"))
    reader.read()
    if not dna.Status.isOk():
        raise DnaReadError(f'Could not read "{path}": {dna.Status.get().message}')
    # The reader only holds a raw pointer to the stream, so keep the stream alive with it.
    reader._dna_core_stream = stream  # noqa: SLF001
    return reader
