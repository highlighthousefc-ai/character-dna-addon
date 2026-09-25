"""Left/right naming and delta mirroring (dna_core.symmetry)."""

import numpy as np
import pytest

from dna_core.symmetry import NotSymmetricError, mirror, mirror_map, opposite_in, opposite_name


@pytest.mark.parametrize(
    ("name", "opposite"),
    [
        ("brow_down_L", "brow_down_R"),
        ("mouth_funnel_UL", "mouth_funnel_UR"),
        ("mouth_funnel_DR", "mouth_funnel_DL"),
        ("mouth_press_ML", "mouth_press_MR"),
        ("Braise_Ewiden_INL", "Braise_Ewiden_INR"),
        ("Braise_Ewiden_OUTR", "Braise_Ewiden_OUTL"),
        ("brow_raiseOuter_left", "brow_raiseOuter_right"),
        ("mouth_lipsSticky_L_ph2", "mouth_lipsSticky_R_ph2"),
        # direction words mirror too: the left eye looking left mirrors to the right eye looking right
        ("eye_lookLeft_L", "eye_lookRight_R"),
        ("ElookUp_ElookRight_R", "ElookUp_ElookLeft_L"),
        ("tongue_left_IN", "tongue_right_IN"),
        ("jaw_sideways_left", "jaw_sideways_right"),
        (
            "Mfunnel_MupperLipRaise_MlowerLipDepress__funnelWide_UL",
            "Mfunnel_MupperLipRaise_MlowerLipDepress__funnelWide_UR",
        ),
        ("eyeLeft_lod0_mesh", "eyeRight_lod0_mesh"),
    ],
)
def test_opposite_names(name: str, opposite: str):
    assert opposite_name(name) == opposite
    assert opposite_name(opposite) == name


@pytest.mark.parametrize(
    "name", ["jaw_open", "mouth_sticky_UC", "nose_wrinkle_cor", "tongue_up_IN", "mouth_up", "head_lod0_mesh", "LipL"]
)
def test_centre_names_have_no_opposite(name: str):
    assert opposite_name(name) is None


def test_opposite_must_exist():
    assert opposite_in("brow_down_L", {"brow_down_L", "brow_down_R"}) == "brow_down_R"
    assert opposite_in("brow_down_L", {"brow_down_L"}) is None


def _grid(noise: float = 0.0, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """A 9 x 5 grid spanning x = -4..4 (unit spacing), with optional per-vertex noise."""
    xs, ys = np.meshgrid(np.arange(-4, 5, dtype=float), np.arange(5, dtype=float))
    positions = np.stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)], axis=1)
    positions += np.random.default_rng(seed).uniform(-noise, noise, positions.shape)
    index = np.arange(xs.size).reshape(xs.shape)
    across = np.stack([index[:, :-1].ravel(), index[:, 1:].ravel()], 1)
    down = np.stack([index[:-1].ravel(), index[1:].ravel()], 1)
    edges = np.concatenate([across, down])
    return positions, edges


def test_symmetric_mesh_pairs_exactly():
    positions, edges = _grid()
    mapping = mirror_map(positions, edges=edges)
    assert mapping.max_distance == pytest.approx(0.0)
    assert (mapping.source[mapping.source] == np.arange(len(positions))).all()
    # vertex 0 is at x = -4, its partner at x = +4 in the same row
    assert positions[mapping.source[0]].tolist() == pytest.approx([4.0, 0.0, 0.0])


def test_topology_fixes_what_nearest_vertices_get_wrong():
    """Scanned faces are a little asymmetric: nearest-vertex partners stop agreeing, topology doesn't."""
    positions, edges = _grid(noise=0.45, seed=3)
    nearest = mirror_map(positions, tolerance=2.0)
    topological = mirror_map(positions, edges=edges, tolerance=2.0)
    identity = np.arange(len(positions))
    assert (nearest.source[nearest.source] != identity).any()  # the noise breaks the nearest map
    assert (topological.source[topological.source] == identity).all()
    clean = mirror_map(_grid()[0], edges=edges)
    assert (topological.source == clean.source).all()  # and recovers the exact symmetric pairing


def test_mirror_moves_a_delta_to_the_partner_with_x_negated():
    positions, edges = _grid(noise=0.3, seed=1)
    mapping = mirror_map(positions, edges=edges, tolerance=2.0)
    deltas = np.zeros_like(positions)
    deltas[10] = (0.5, 0.2, -0.1)
    mirrored = mirror(deltas, mapping)
    partner = mapping.source[10]
    assert np.flatnonzero(np.abs(mirrored).max(1)).tolist() == [partner]
    assert mirrored[partner].tolist() == pytest.approx([-0.5, 0.2, -0.1])
    np.testing.assert_allclose(mirror(mirrored, mapping), deltas)  # mirroring twice gives it back


def test_mirroring_between_two_meshes():
    """The eyes are separate meshes: the left eye's deltas mirror onto the right eye."""
    left = np.array([[2.0, 0.0, 0.0], [3.0, 0.0, 0.0], [2.5, 1.0, 0.0]])
    right = left[[2, 0, 1]] * [-1, 1, 1] + 0.01
    mapping = mirror_map(left, right)
    assert mapping.source.tolist() == [2, 0, 1]
    deltas = np.array([[0.1, 0.0, 0.0], [0.0, 0.2, 0.0], [0.0, 0.0, 0.3]])
    np.testing.assert_allclose(mirror(deltas, mapping), [[0.0, 0.0, 0.3], [-0.1, 0.0, 0.0], [0.0, 0.2, 0.0]])


def test_a_mesh_off_the_centre_line_cannot_be_flipped_in_place():
    left_eye = np.array([[2.0, 0.0, 0.0], [3.0, 0.0, 0.0], [2.5, 1.0, 0.0]])
    with pytest.raises(NotSymmetricError, match="mirror-symmetric"):
        mirror_map(left_eye)
