"""Names the add-on gives DNA data inside Blender."""

import hashlib


# Blender stores ID and shape key names in a 64-byte buffer (63 characters plus the terminator).
BLENDER_NAME_MAX_LENGTH = 63
_HASH_LENGTH = 8


def shape_key_name(mesh_name: str, channel_name: str) -> str:
    """Return the shape key name for one DNA blend shape target: ``{mesh}__{channel}``.

    Blender silently truncates longer names, which made MetaHuman targets such as
    ``head_lod0_mesh__Mfunnel_MupperLipRaise_MlowerLipDepress__funnelWide_UL`` (70 characters)
    collide with their siblings and fall out of every name lookup. A name over the limit keeps
    its first 54 characters and ends in ``~`` plus 8 hex digits of the full name's SHA-1, so it is
    still readable, fits in 63 characters, and is the same on every import.
    """
    name = f"{mesh_name}__{channel_name}"
    if len(name.encode("utf-8")) <= BLENDER_NAME_MAX_LENGTH:
        return name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:_HASH_LENGTH]  # noqa: S324 (a name, not security)
    keep = BLENDER_NAME_MAX_LENGTH - _HASH_LENGTH - 1
    head = name.encode("utf-8")[:keep].decode("utf-8", errors="ignore")
    return f"{head}~{digest}"
