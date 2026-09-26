"""Wrinkle maps stored as offsets: detection, facial areas, and the blend (a numpy reference). No ``bpy``.

The head's wrinkle maps are three colour maps (CM1-3) and three normal maps (WM1-3), blended over the
base maps by 41 region masks the rig drives (``head_wm1_browsRaiseInner_L_msk`` and so on).

Older MetaHuman exports store them as full maps, and the inherited Texture Logic *mixes towards*
them. Exports from Unreal 5.6 and later (e.g. Poly Hammer Interchange, UE 5.8) store **offsets from
the base, centred on 0.5**: CM1-3 average 0.495 in every channel, and WM1-3 have a blue channel near
0.5 instead of about 1 (dev-docs/FINDINGS.md "Character Assembly Slice 1"). Mixing towards those turns
wrinkles flat grey. :func:`blend` is the offset formula ``assembly/wrinkles.py`` builds in nodes:

    result = base + sum_i(weight_i * (map_i - 0.5)) * gain

Colour offsets are summed in sRGB (display) space: they were authored against the 8-bit sRGB
texture. Summed in linear space, the same offsets darken dim channels far more than bright ones and
the creases of a brow raise turn orange (FINDINGS "Wrinkle offsets"). Normal offsets stay in their
encoded (0..1) form.
"""

import numpy as np


GAMMA = 2.2  # sRGB, approximately

# Facial area -> words in the region mask names. Each area gets one strength.
AREAS: dict[str, tuple[str, ...]] = {
    "Brows": ("browsRaise", "browsDown", "browsLateral"),
    "Eyes": ("blink", "squint"),
    "Nose": ("noseWrinkler",),
    "Cheeks": ("cheekRaise", "smile"),
    "Mouth": ("purse", "lips", "mouthStretch"),
    "Chin & Jaw": ("chinRaise", "jawOpen"),
    "Neck": ("neckStretch",),
}

# How far from 0.5 the mean of an offset map may be.
_OFFSET_TOLERANCE = 0.05


def area_of(mask_name: str) -> str | None:
    """The facial area of a region mask (``wm1.head_wm1_browsRaiseInner_L_msk`` -> ``Brows``)."""
    for area, words in AREAS.items():
        if any(word in mask_name for word in words):
            return area
    return None


def are_offsets(color_mean: np.ndarray, normal_mean: np.ndarray) -> bool:
    """Whether a wrinkle colour map and normal map (mean RGB of their stored values) are offsets.

    Offsets: every colour channel near 0.5, and the normal's blue near 0.5. A full normal map's
    blue is near 1, since its normals point out of the surface.
    """
    color_mean = np.asarray(color_mean, dtype=float)[:3]
    normal_mean = np.asarray(normal_mean, dtype=float)[:3]
    return bool(
        np.all(np.abs(color_mean - 0.5) < _OFFSET_TOLERANCE) and abs(normal_mean[2] - 0.5) < 2 * _OFFSET_TOLERANCE
    )


def blend(
    base: np.ndarray,
    weights: list[float],
    maps: list[np.ndarray],
    gain: float = 1.0,
    srgb: bool = False,
) -> np.ndarray:
    """Offset blend of up to three wrinkle maps over ``base`` (values, not images).

    ``srgb``: ``base`` is linear colour and the sum happens in sRGB space, then back to linear.
    """
    base = np.asarray(base, dtype=float)
    value = np.power(np.maximum(base, 0.0), 1.0 / GAMMA) if srgb else base
    offset = sum(weight * (np.asarray(map_, dtype=float) - 0.5) for weight, map_ in zip(weights, maps, strict=True))
    value = np.maximum(value + offset * gain, 0.0)
    return np.power(value, GAMMA) if srgb else value
