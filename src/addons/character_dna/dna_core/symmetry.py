"""Left/right pairing of MetaHuman blend shape names, and mirroring deltas across the face.

Naming (checked on all 782 channels of Ada's head DNA):

* a side token at the end: ``_L``/``_R``, ``_UL``/``_UR``, ``_DL``/``_DR``, ``_ML``/``_MR``,
  ``_INL``/``_INR``, ``_OUTL``/``_OUTR``, ``_left``/``_right``;
* or as a whole token inside the name: ``mouth_lipsSticky_L_ph1``;
* plus direction words, which mirror too: the mirror image of ``eye_lookLeft_L`` (left eye looking
  left) is ``eye_lookRight_R``, and of ``tongue_left_IN`` is ``tongue_right_IN``.

:func:`opposite_name` swaps all of them. A name with none, or whose swap names nothing that exists,
has no opposite. Mesh names follow the same rule (``eyeLeft_lod0_mesh`` <-> ``eyeRight_lod0_mesh``).

Geometry: MetaHuman faces are scanned, so the neutral mesh is not exactly symmetric (Ada's head:
mirrored vertices land up to 1.8 mm from a vertex, and nearest-vertex partners disagree for 5% of
vertices). The topology is symmetric, so :func:`mirror_map` pairs vertices along the mesh's edges
(an involution: mirroring twice returns the original); :func:`mirror` then gives each destination
vertex its partner's delta with the lateral component negated. Deltas, not positions, are mirrored,
so the face's own asymmetry is never baked into a shape.
"""

import re

from dataclasses import dataclass

import numpy as np


# Side tokens that stand alone between underscores (or at the ends of the name).
_SIDE_TOKENS = {
    "L": "R",
    "R": "L",
    "UL": "UR",
    "UR": "UL",
    "DL": "DR",
    "DR": "DL",
    "ML": "MR",
    "MR": "ML",
    "INL": "INR",
    "INR": "INL",
    "OUTL": "OUTR",
    "OUTR": "OUTL",
    "left": "right",
    "right": "left",
}
# Direction words inside camelCase tokens: lookLeft, ElookRight, eyeLeft.
_DIRECTION = re.compile(r"(?<=[a-z])(Left|Right)(?=[A-Z_]|$)")

# Mirrored vertices farther than this (in the mesh's units) from any vertex mean the mesh isn't
# mirror-symmetric where it matters: 5 mm for MetaHuman meshes in centimetres.
DEFAULT_TOLERANCE = 0.5


class NotSymmetricError(ValueError):
    """The mesh (or mesh pair) is too far from mirror-symmetric to mirror deltas across it."""

    def __init__(self, distance: float, tolerance: float) -> None:
        super().__init__(
            f"The mesh isn't mirror-symmetric: a mirrored vertex lands {distance:.3g} units "
            f"from its partner (limit {tolerance:g})"
        )
        self.distance = distance
        self.tolerance = tolerance


def opposite_name(name: str) -> str | None:
    """The mirror-image name of a shape, channel or mesh, or ``None`` when it has no side."""
    tokens = name.split("_")
    swapped = [_SIDE_TOKENS.get(token, token) for token in tokens]
    result = _DIRECTION.sub(lambda match: "Right" if match.group(1) == "Left" else "Left", "_".join(swapped))
    return result if result != name else None


def opposite_in(name: str, names: "set[str] | list[str]") -> str | None:
    """:func:`opposite_name`, only when that opposite is one of ``names``."""
    opposite = opposite_name(name)
    return opposite if opposite is not None and opposite in names else None


@dataclass(frozen=True)
class MirrorMap:
    """``source[i]`` is the source vertex that mirrors onto destination vertex ``i``."""

    source: np.ndarray  # int64 (destination vertex count,)
    distance: np.ndarray  # float64: how far each destination vertex's mirror image is from its partner

    @property
    def max_distance(self) -> float:
        return float(self.distance.max()) if len(self.distance) else 0.0


def _nearest(points: np.ndarray, targets: np.ndarray, chunk: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """Index of, and distance to, the nearest target of every point (exact, float64)."""
    target_norms = (targets**2).sum(axis=1)
    index = np.empty(len(points), dtype=np.int64)
    for start in range(0, len(points), chunk):
        block = points[start : start + chunk]
        squared = (block**2).sum(axis=1)[:, None] - 2.0 * block @ targets.T + target_norms[None, :]
        index[start : start + chunk] = squared.argmin(axis=1)
    return index, np.linalg.norm(points - targets[index], axis=1)


def _components(neighbours: list[list[int]]) -> np.ndarray:
    """The connected part of each vertex, labelled by one of its vertices."""
    component = np.full(len(neighbours), -1, dtype=np.int64)
    for root in range(len(neighbours)):
        if component[root] >= 0:
            continue
        component[root] = root
        stack = [root]
        while stack:
            for neighbour in neighbours[stack.pop()]:
                if component[neighbour] < 0:
                    component[neighbour] = root
                    stack.append(neighbour)
    return component


def _topological_pairs(
    reflected: np.ndarray, positions: np.ndarray, nearest: np.ndarray, edges: np.ndarray
) -> np.ndarray:
    """Turn a nearest-vertex map of a mesh onto itself into a pairing that follows its edges.

    Scanned faces aren't exactly symmetric, so nearest-vertex partners are sometimes wrong. The
    topology is symmetric, though. Pairs grow breadth-first from seeds: in each connected part,
    the vertices on the centre line that are their own nearest mirror (or, for a part off the
    centre line, its best mutual nearest pair). A vertex next to a paired vertex ``u`` (partner
    ``u'``) must pair with a neighbour of ``u'``; among the free ones the closest to its mirror image
    wins. Where the topology is symmetric the result is an involution that maps edges to edges.
    """
    count = len(positions)
    neighbours: list[list[int]] = [[] for _ in range(count)]
    for a, b in edges.tolist():
        neighbours[a].append(b)
        neighbours[b].append(a)
    partner = np.full(count, -1, dtype=np.int64)
    distance = np.linalg.norm(reflected - positions[nearest], axis=1)
    mutual = nearest[nearest] == np.arange(count)

    def gap(vertex: int, candidate: int) -> float:
        return float(((positions[candidate] - reflected[vertex]) ** 2).sum())

    component = _components(neighbours)
    for root in np.unique(component):
        members = np.flatnonzero(component == root)
        # Seeds: centre-line vertices of this part that mirror onto themselves...
        seeds = [int(v) for v in members if nearest[v] == v]
        if not seeds:  # ...or a part off the centre line (and its twin): its best mutual pair.
            pairs = [int(v) for v in members if mutual[v]]
            if not pairs:
                continue
            seeds = [min(pairs, key=lambda v: distance[v])]
        queue = []
        for seed in seeds:
            if partner[seed] < 0 and partner[nearest[seed]] < 0:
                partner[seed] = nearest[seed]
                partner[nearest[seed]] = seed
                queue.extend([seed, int(nearest[seed])])
        head = 0
        while head < len(queue):
            vertex = queue[head]
            head += 1
            mirrored = int(partner[vertex])
            for neighbour in neighbours[vertex]:
                if partner[neighbour] >= 0:
                    continue
                candidates = [c for c in neighbours[mirrored] if partner[c] < 0 or c == neighbour]
                if not candidates:
                    continue
                best = min(candidates, key=lambda c: gap(neighbour, c))
                partner[neighbour] = best
                partner[best] = neighbour
                queue.append(neighbour)
                if best != neighbour:
                    queue.append(best)
    unpaired = partner < 0
    partner[unpaired] = nearest[unpaired]  # vertices no seed could reach keep their nearest vertex
    # A part seeded from a wrong mutual pair (repetitive shapes such as teeth) pairs worse than
    # plain nearest vertices; such parts keep the nearest-vertex pairing instead.
    topological = np.linalg.norm(reflected - positions[partner], axis=1)
    for root in np.unique(component):
        members = component == root
        if topological[members].mean() > distance[members].mean() * 1.5 + 1e-6:
            partner[members] = nearest[members]
    return partner


def mirror_map(
    source_positions: np.ndarray,
    destination_positions: np.ndarray | None = None,
    edges: np.ndarray | None = None,
    axis: int = 0,
    tolerance: float = DEFAULT_TOLERANCE,
) -> MirrorMap:
    """Pair every destination vertex with the source vertex that mirrors onto it.

    ``axis`` is the lateral (left/right) axis: 0 (X) both in DNA space and in Blender. Without
    ``destination_positions`` the mesh is mirrored onto itself (flip, or left-to-right on one
    mesh); then ``edges`` (``(n, 2)`` vertex index pairs) makes the pairing follow the topology
    so it is symmetric. Between two meshes (the eyes) the nearest vertex is used. Raises
    :class:`NotSymmetricError` when a pair is farther apart than ``tolerance``.
    """
    source = np.asarray(source_positions, dtype=np.float64)
    destination = source if destination_positions is None else np.asarray(destination_positions, dtype=np.float64)
    reflected = destination.copy()
    reflected[:, axis] *= -1.0
    # Centre the non-lateral axes: far from the origin (MetaHuman heads sit ~1.6 m up) the
    # distance expansion in _nearest loses digits.
    offset = source.mean(axis=0)
    offset[axis] = 0.0
    nearest, distance = _nearest(reflected - offset, source - offset)
    if destination_positions is None and edges is not None and len(edges):
        nearest = _topological_pairs(reflected, source, nearest, np.asarray(edges, dtype=np.int64))
        distance = np.linalg.norm(reflected - source[nearest], axis=1)
    result = MirrorMap(nearest, distance)
    if result.max_distance > tolerance:
        raise NotSymmetricError(result.max_distance, tolerance)
    return result


def mirror(deltas: np.ndarray, mapping: MirrorMap, axis: int = 0) -> np.ndarray:
    """Dense source deltas mirrored onto the destination vertices of ``mapping``."""
    result = np.asarray(deltas, dtype=np.float64)[mapping.source].copy()
    result[:, axis] *= -1.0
    return result
