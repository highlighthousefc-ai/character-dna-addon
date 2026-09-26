"""Minimal read-only Alembic (Ogawa) reader: enough for static groom curves, in numpy.

Alembic files written by Unreal / Maya for grooms are Ogawa archives: a tree of *groups* (lists of
child offsets) and *data* blocks. The layout, from the Alembic reference implementation
(BSD-3, lib/Alembic/Ogawa and lib/Alembic/AbcCoreOgawa):

* File header (16 bytes): ``b"Ogawa"``, a frozen flag, a 2-byte version, then the root group's offset.
* Group at ``pos``: ``uint64`` child count, then one ``uint64`` per child. Bit 63 set means a data
  child (offset in the low bits, 0 = empty); otherwise a group (0 = empty).
* Data at ``pos``: ``uint64`` size, then that many bytes.
* Archive root group: [0] file version, [1] library version, [2] the top object, [3] archive
  metadata, [4] time samplings, [5] indexed metadata.
* Object group: [0] its properties (a compound), [1..n-2] child objects, [n-1] child headers
  (then 32 bytes of hashes).
* Compound group: one group per property, in header order, then [last] the property headers.
* Array property group: per sample, [2i] data (16-byte hash key, then the values) and [2i+1] its
  dimensions (``uint64`` each; empty means ``len(values) / extent``).

Only what grooms need is read: sample 0 of array properties, and property/object metadata.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

import numpy as np


_DATA_BIT = 1 << 63
# Alembic POD types, by index (Alembic::Util::PlainOldDataType).
_POD_DTYPES = [
    np.dtype(np.bool_),
    np.dtype("<u1"),
    np.dtype("<i1"),
    np.dtype("<u2"),
    np.dtype("<i2"),
    np.dtype("<u4"),
    np.dtype("<i4"),
    np.dtype("<u8"),
    np.dtype("<i8"),
    np.dtype("<f2"),
    np.dtype("<f4"),
    np.dtype("<f8"),
    None,  # string
    None,  # wstring
]
_STRING_POD = 12


class AlembicError(ValueError):
    """Not an Alembic Ogawa file, or not laid out as expected."""


class _Reader:
    def __init__(self, buffer: bytes):
        self.buffer = buffer
        self.size = len(buffer)

    def u64(self, pos: int) -> int:
        if pos + 8 > self.size:
            raise AlembicError(f"Read past the end of the file at {pos}")
        return int.from_bytes(self.buffer[pos : pos + 8], "little")

    def group(self, pos: int) -> list[int]:
        if pos == 0:
            return []
        count = self.u64(pos)
        if count == 0 or count > self.size // 8:
            return []
        return np.frombuffer(self.buffer, dtype="<u8", count=count, offset=pos + 8).tolist()

    def data(self, child: int) -> memoryview:
        """The bytes of a data child (``child`` is the raw child entry, with bit 63 set)."""
        if not child & _DATA_BIT:
            raise AlembicError("Expected a data block, found a group")
        pos = child & ~_DATA_BIT
        if pos == 0:
            return memoryview(b"")
        size = self.u64(pos)
        if pos + 8 + size > self.size:
            raise AlembicError("Data block runs past the end of the file")
        return memoryview(self.buffer)[pos + 8 : pos + 8 + size]


@dataclass
class Property:
    name: str
    kind: str  # "compound", "scalar" or "array"
    pod: int
    extent: int
    metadata: dict[str, str]
    samples: int
    _reader: _Reader = field(repr=False)
    _group: int = field(repr=False)
    _indexed_metadata: list[dict[str, str]] = field(repr=False)

    def compound(self) -> "Compound":
        if self.kind != "compound":
            raise AlembicError(f'"{self.name}" is not a compound property')
        return Compound(self._reader, self._group, self._indexed_metadata)

    def values(self) -> np.ndarray | list[str]:
        """Sample 0: an array of shape (n, extent) (or (n,) for extent 1), or a list of strings."""
        if self.kind == "compound":
            raise AlembicError(f'"{self.name}" is a compound property')
        children = self._reader.group(self._group)
        if not children:
            return [] if self.pod == _STRING_POD else np.zeros((0,), _POD_DTYPES[self.pod] or np.uint8)
        data = self._reader.data(children[0])
        payload = data[16:] if len(data) >= 16 else memoryview(b"")
        if self.pod == _STRING_POD:
            return [text.decode("utf-8") for text in bytes(payload).split(b"\0")[:-1]]
        dtype = _POD_DTYPES[self.pod]
        if dtype is None:
            raise AlembicError(f'"{self.name}" has an unsupported type')
        values = np.frombuffer(payload, dtype=dtype).copy()
        return values.reshape(-1, self.extent) if self.extent > 1 else values


class Compound:
    """A compound property: named child properties."""

    def __init__(self, reader: _Reader, group: int, indexed_metadata: list[dict[str, str]]):
        self._reader = reader
        self._indexed_metadata = indexed_metadata
        children = reader.group(group)
        self.properties: dict[str, Property] = {}
        if not children or not children[-1] & _DATA_BIT:
            return
        headers = _property_headers(reader.data(children[-1]), indexed_metadata)
        for index, (name, kind, pod, extent, metadata, samples) in enumerate(headers):
            self.properties[name] = Property(
                name, kind, pod, extent, metadata, samples, reader, children[index], indexed_metadata
            )

    def __contains__(self, name: str) -> bool:
        return name in self.properties

    def __getitem__(self, path: str) -> Property:
        """A property by name, or a path through nested compounds (``".geom/.arbGeomParams/x"``)."""
        head, _, rest = path.partition("/")
        if head not in self.properties:
            raise KeyError(path)
        prop = self.properties[head]
        return prop.compound()[rest] if rest else prop

    def get(self, path: str) -> Property | None:
        try:
            return self[path]
        except KeyError:
            return None


class AlembicObject:
    def __init__(self, reader: _Reader, group: int, name: str, metadata: dict[str, str], indexed: list[dict[str, str]]):
        self._reader = reader
        self._indexed_metadata = indexed
        self.name = name
        self.metadata = metadata
        self._children = reader.group(group)

    @property
    def properties(self) -> Compound:
        first = self._children[0] if self._children else 0
        return Compound(self._reader, 0 if first & _DATA_BIT else first, self._indexed_metadata)

    def children(self) -> list["AlembicObject"]:
        if len(self._children) < 2 or not self._children[-1] & _DATA_BIT:
            return []
        headers = _object_headers(self._reader.data(self._children[-1]), self._indexed_metadata)
        groups = self._children[1:-1]
        return [
            AlembicObject(self._reader, group, name, metadata, self._indexed_metadata)
            for group, (name, metadata) in zip(groups, headers, strict=False)
        ]

    def walk(self, path: str = "") -> list[tuple[str, "AlembicObject"]]:
        found = []
        for child in self.children():
            child_path = f"{path}/{child.name}"
            found.append((child_path, child))
            found.extend(child.walk(child_path))
        return found


class Archive:
    """An Alembic Ogawa file, read into memory (a groom is tens of MB; arrays come back as copies)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._bytes = self.path.read_bytes()
        header = self._bytes[:16]
        if len(header) < 16 or header[:5] != b"Ogawa":
            raise AlembicError(f"{self.path.name} is not an Alembic (Ogawa) file")
        self._reader = _Reader(self._bytes)
        root = self._reader.group(int.from_bytes(header[8:16], "little"))
        if len(root) < 6 or root[2] & _DATA_BIT:
            raise AlembicError(f"{self.path.name} has no top object")
        self.indexed_metadata = _indexed_metadata(self._reader.data(root[5]))
        self.top = AlembicObject(self._reader, root[2], "ABC", {}, self.indexed_metadata)

    def close(self) -> None:
        self._bytes = b""
        self._reader = _Reader(b"")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _metadata(text: str) -> dict[str, str]:
    pairs = (item.split("=", 1) for item in text.split(";") if "=" in item)
    return dict(pairs)


def _indexed_metadata(data: memoryview) -> list[dict[str, str]]:
    found = [{}]
    raw, pos = bytes(data), 0
    while pos < len(raw):
        size = raw[pos]
        pos += 1
        found.append(_metadata(raw[pos : pos + size].decode("utf-8")))
        pos += size
    return found


def _uint(raw: bytes, pos: int, hint: int) -> tuple[int, int]:
    width = (1, 2, 4)[hint]
    return int.from_bytes(raw[pos : pos + width], "little"), pos + width


def _property_headers(data: memoryview, indexed: list[dict[str, str]]) -> list[tuple]:
    raw, pos, headers = bytes(data), 0, []
    while pos < len(raw):
        info = int.from_bytes(raw[pos : pos + 4], "little")
        pos += 4
        kind = ("compound", "scalar", "array", "array")[info & 0x3]
        hint = (info & 0xC) >> 2
        pod, extent, samples = 0, 0, 0
        if kind != "compound":
            pod = (info & 0xF0) >> 4
            extent = (info & 0xFF000) >> 12
            samples, pos = _uint(raw, pos, hint)
            if info & 0x200:  # first / last changed indices
                _, pos = _uint(raw, pos, hint)
                _, pos = _uint(raw, pos, hint)
            if info & 0x100:  # time sampling index
                _, pos = _uint(raw, pos, hint)
        size, pos = _uint(raw, pos, hint)
        name = raw[pos : pos + size].decode("utf-8")
        pos += size
        index = (info & 0xFF00000) >> 20
        if index == 0xFF:
            size, pos = _uint(raw, pos, hint)
            metadata = _metadata(raw[pos : pos + size].decode("utf-8"))
            pos += size
        else:
            metadata = indexed[index] if index < len(indexed) else {}
        headers.append((name, kind, pod, extent, metadata, samples))
    return headers


def _object_headers(data: memoryview, indexed: list[dict[str, str]]) -> list[tuple[str, dict[str, str]]]:
    raw = bytes(data)[:-32] if len(data) > 32 else b""  # the last 32 bytes are hashes
    pos, headers = 0, []
    while pos < len(raw):
        size = int.from_bytes(raw[pos : pos + 4], "little")
        pos += 4
        name = raw[pos : pos + size].decode("utf-8")
        pos += size
        index = raw[pos]
        pos += 1
        if index == 0xFF:
            size = int.from_bytes(raw[pos : pos + 4], "little")
            pos += 4
            metadata = _metadata(raw[pos : pos + size].decode("utf-8"))
            pos += size
        else:
            metadata = indexed[index] if index < len(indexed) else {}
        headers.append((name, metadata))
    return headers
