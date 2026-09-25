"""Regression check for KI-1: pose-picker filters must never change or apply the selected pose.

Usage (the ``bpy`` module or a Blender binary):
    python scripts/ci/pose_picker_check.py
    blender --background --factory-startup --python-exit-code 1 --python scripts/ci/pose_picker_check.py

Selects a pose, then changes the tag filters, match mode and category so that pose is filtered out,
and checks after each change that the selection (and its stored value) is unchanged and still listed,
so Blender shows it. The bug reassigned the selection, and assigning it is what applies a pose to the
face board; with no character loaded here nothing is applied either way, so that the face really
stays put is checked interactively with a character (docs/FINDINGS). Exits non-zero on failure.
"""

import sys

from pathlib import Path

import bpy


ADDONS_FOLDER = Path(__file__).resolve().parents[2] / "src" / "addons"


def fail(message: str) -> None:
    raise RuntimeError(message)


def main() -> None:
    sys.path.insert(0, str(ADDONS_FOLDER))
    import character_dna

    from character_dna.ui import callbacks

    character_dna.register()
    try:
        face_board = bpy.context.scene.character_dna.face_board
        metadata = callbacks.ensure_face_pose_metadata()
        tag_properties = {tag: name for name, tag in callbacks.get_face_pose_tag_property_map().items()}

        # A pose without the jaw_open tag, from the emotions category.
        pose = next(e for e in metadata if e["category"] == "emotions" and "jaw_open" not in e["tags"])
        face_board.face_pose_previews = pose["id"]
        print(f"Selected {pose['name']!r} (value {pose['value']})")

        def check(step: str) -> None:
            listed = [item[0] for item in callbacks.get_face_pose_previews_items(face_board, bpy.context)]
            print(f"{step}: selection={face_board.face_pose_previews == pose['id']}, listed={len(listed)}")
            if face_board.face_pose_previews != pose["id"]:
                fail(f"{step}: the selected pose changed to {face_board.face_pose_previews!r}")
            if face_board.get("face_pose_previews") != pose["value"]:
                fail(f"{step}: the stored pose value changed")
            if pose["id"] not in listed:
                fail(f"{step}: the selected pose is missing from the list, so Blender would show a blank")

        setattr(face_board, tag_properties["jaw_open"], True)
        check("jaw_open tag on")
        face_board.tag_match_mode = "ALL"
        check("match ALL")
        face_board.category = "visemes"
        check("category visemes")
        # Two tags no single pose carries: nothing matches the filters at all.
        face_board.category = "ALL"
        for tag in ("tongue", "neck"):
            if tag in tag_properties:
                setattr(face_board, tag_properties[tag], True)
        filtered = callbacks._filter_face_pose_metadata(  # noqa: SLF001
            metadata, "ALL", tuple(sorted(callbacks.get_enabled_face_pose_tags(face_board))), "ALL"
        )
        print(f"Poses matching every filter: {len(filtered)}")
        check("filters matching nothing")

        # Clearing the filters keeps the selection too, and choosing a pose still selects it.
        for name in tag_properties.values():
            setattr(face_board, name, False)
        face_board.tag_match_mode = "ANY"
        check("filters cleared")
        other = next(e for e in metadata if e["id"] != pose["id"])
        face_board.face_pose_previews = other["id"]
        if face_board.face_pose_previews != other["id"]:
            fail("Selecting a pose no longer works")
        print("POSE_PICKER_OK")
    finally:
        character_dna.unregister()


if __name__ == "__main__":
    main()
