"""Offset wrinkle maps (dna_core.wrinkles): areas, detection, and the blend formula."""

import numpy as np
import pytest

from dna_core.wrinkles import AREAS, GAMMA, are_offsets, area_of, blend


# The 41 region-mask inputs of the head's Texture Logic node (materials.blend), in order.
MASKS = [
    *(f"wm1.head_wm13_lips_{s}_msk" for s in ("DL", "DR", "UL", "UR")),
    *(f"wm1.head_wm1_{n}_{s}_msk" for n in ("blink", "browsRaiseInner", "browsRaiseOuter", "chinRaise") for s in "LR"),
    "wm1.head_wm1_jawOpen_msk",
    *(f"wm1.head_wm1_purse_{s}_msk" for s in ("DL", "DR", "UL", "UR")),
    *(f"wm1.head_wm1_squintInner_{s}_msk" for s in "LR"),
    *(
        f"wm2.head_wm2_{n}_{s}_msk"
        for n in ("browsDown", "browsLateral", "mouthStretch", "neckStretch", "noseWrinkler")
        for s in "LR"
    ),
    *(
        f"wm3.head_wm3_{n}_{s}_msk"
        for n in ("cheekRaiseInner", "cheekRaiseOuter", "cheekRaiseUpper", "smile")
        for s in "LR"
    ),
    *(f"wm3.head_wm13_lips_{s}_msk" for s in ("DL", "DR", "UL", "UR")),
]


def test_every_region_mask_has_an_area():
    assert len(MASKS) == 41
    assert {mask: area_of(mask) for mask in MASKS if area_of(mask) is None} == {}
    assert area_of("wm1.head_wm1_browsRaiseInner_L_msk") == "Brows"
    assert area_of("wm1.head_wm1_squintInner_R_msk") == "Eyes"
    assert area_of("wm3.head_wm3_smile_L_msk") == "Cheeks"
    assert area_of("wm1.head_wm13_lips_UL_msk") == "Mouth"
    assert area_of("wm1.head_wm1_jawOpen_msk") == "Chin & Jaw"
    assert area_of("wm2.head_wm2_neckStretch_R_msk") == "Neck"
    assert {area_of(mask) for mask in MASKS} == set(AREAS)


@pytest.mark.parametrize(
    ("color", "normal", "offsets"),
    [
        ((0.496, 0.495, 0.496), (0.498, 0.498, 0.497), True),  # the real UE 5.8 export (Slice 0/1 stats)
        ((0.61, 0.43, 0.34), (0.50, 0.50, 0.999), False),  # full colour and normal maps
        ((0.496, 0.495, 0.496), (0.50, 0.50, 0.99), False),  # offset colour but a full normal map
        ((0.60, 0.50, 0.50), (0.50, 0.50, 0.50), False),  # colour not centred
    ],
)
def test_offset_detection(color: tuple, normal: tuple, offsets: bool):
    assert are_offsets(np.array(color), np.array(normal)) is offsets


def test_blend_adds_weighted_offsets():
    base = np.array([0.4, 0.3, 0.2])
    np.testing.assert_allclose(blend(base, [1, 1, 1], [np.full(3, 0.5)] * 3), base)  # 0.5 = no change
    maps = [np.array([0.6, 0.5, 0.4]), np.full(3, 0.5), np.array([0.45, 0.45, 0.45])]
    np.testing.assert_allclose(blend(base, [1.0, 1.0, 0.5], maps), [0.475, 0.275, 0.075], atol=1e-12)
    np.testing.assert_allclose(blend(base, [1.0, 0, 0], maps, gain=2.0), [0.6, 0.3, 0.0], atol=1e-12)
    assert blend(np.array([0.05]), [1, 0, 0], [np.array([0.2]), np.array([0.5]), np.array([0.5])]).item() == 0.0


def test_colour_offsets_are_summed_in_srgb():
    base = np.array([0.33, 0.155, 0.1])  # linear skin
    crease = [np.array([0.41, 0.41, 0.435]), np.full(3, 0.5), np.full(3, 0.5)]  # darker, as in CM1's creases
    srgb = blend(base, [1, 0, 0], crease, srgb=True)
    expected = np.power(np.power(base, 1 / GAMMA) + (crease[0] - 0.5), GAMMA)
    np.testing.assert_allclose(srgb, expected)
    # In sRGB the crease darkens every channel alike; in linear space green and blue collapse (orange creases).
    linear = blend(base, [1, 0, 0], crease)
    spread = lambda result: (result / base).max() / (result / base).min()  # noqa: E731
    assert spread(srgb) < 1.3
    assert spread(linear) > 2.0
