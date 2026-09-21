# Type checking utilities for the Character DNA addon.

from typing import TYPE_CHECKING, ClassVar, Literal


if TYPE_CHECKING:
    import bpy

    from bpy.types import bpy_prop_collection, bpy_struct

    from .bindings.windows.x64.py313 import dna, riglogic  # pyright: ignore[reportAttributeAccessIssue] # noqa: TC004
    from .bindings.windows.x64.py313.dna import BinaryStreamReader, BinaryStreamWriter  # noqa: TC004
    from .components.body import CharacterComponentBase, CharacterComponentBody  # noqa: TC004
    from .components.head import CharacterComponentHead  # noqa: TC004
    from .operators import BakeAnimationBase, DuplicateRigInstance  # noqa: TC004
    from .properties import (
        CharacterAddonProperties,
        CharacterFaceBoardProperties,  # noqa: TC004
        CharacterImportProperties,  # noqa: TC004
        CharacterOutputProperties,  # noqa: TC004
        CharacterSceneProperties,  # noqa: TC004
        CharacterViewOptionsProperties,  # noqa: TC004
        CharacterWindowManagerProperties as _CharacterWindowManagerProperties,
        ExtraDnaFolder,
        OutputData,  # noqa: TC004
    )
    from .rig_definition import (
        RigDefinition,  # noqa: TC004
        RigJointGroup,  # noqa: TC004
    )
    from .rig_instance import RigInstance as _RigInstanceBase

    ComponentType = Literal["head", "body", "all"]

    # =========================================================================
    # Custom Collections
    # =========================================================================
    class ExtraDnaFolders(bpy_prop_collection[ExtraDnaFolder], bpy_struct):
        def add(self) -> ExtraDnaFolder: ...
        def move(self, src_index: int, dst_index: int) -> None: ...
        def remove(self, index: int) -> None: ...
        def clear(self) -> None: ...

    # =========================================================================
    # Extended RigInstance with dynamically assigned properties
    # These are added at runtime in properties.py register() function
    # =========================================================================
    class RigInstance(_RigInstanceBase):
        """Extended RigInstance type with dynamically registered properties."""

        output: CharacterOutputProperties
        view_options: CharacterViewOptionsProperties

    CharacterWindowManagerProperties = _CharacterWindowManagerProperties

    # =========================================================================
    # Addon Preferences Types
    # =========================================================================
    class CharacterAddonPreferences(CharacterAddonProperties, bpy.types.AddonPreferences):
        """Typed addon preferences for Character DNA."""

        bl_idname: str
        extra_dna_folder_list: ExtraDnaFolders
        extra_dna_folder_list_active_index: int

    class _CharacterAddon(bpy.types.Addon):
        """Typed addon module reference."""

        preferences: CharacterAddonPreferences

    class _CharacterAddons(bpy.types.bpy_prop_collection[bpy.types.Addon]):
        """Typed addons collection with Character DNA addon."""

        def get(self, name: str, default: _CharacterAddon | None = None) -> _CharacterAddon | None: ...
        def __getitem__(self, name: str) -> _CharacterAddon: ...
        def __contains__(self, name: str) -> bool: ...

    # =========================================================================
    # Patch bpy.types.Preferences
    # =========================================================================
    class Preferences(bpy.types.Preferences):
        """Extended Preferences type with typed addons access."""

        addons: _CharacterAddons

    # =========================================================================
    # Patch bpy.types.Scene
    # =========================================================================
    class Scene(bpy.types.Scene):
        """Extended Scene type with Character DNA properties."""

        character_dna: CharacterSceneProperties

    # =========================================================================
    # Patch bpy.types.WindowManager
    # =========================================================================
    class WindowManager(bpy.types.WindowManager):
        """Extended WindowManager type with Character DNA properties."""

        character_dna: CharacterWindowManagerProperties

    # =========================================================================
    # Patch bpy.types.Context
    # =========================================================================
    class Context(bpy.types.Context):
        """Extended Context type with typed properties."""

        window_manager: WindowManager
        preferences: Preferences
        scene: Scene

    __all__ = [
        "BakeAnimationBase",
        "BakeAnimationBase",
        "BinaryStreamReader",
        "BinaryStreamWriter",
        "CharacterAddonPreferences",
        "CharacterComponentBase",
        "CharacterComponentBody",
        "CharacterComponentHead",
        "CharacterFaceBoardProperties",
        "CharacterImportProperties",
        "CharacterOutputProperties",
        "CharacterSceneProperties",
        "CharacterViewOptionsProperties",
        "CharacterWindowManagerProperties",
        "ClassVar",
        "ComponentType",
        "Context",
        "DuplicateRigInstance",
        "OutputData",
        "Preferences",
        "RigDefinition",
        "RigInstance",
        "RigJointGroup",
        "Scene",
        "WindowManager",
        "dna",
        "riglogic",
    ]
