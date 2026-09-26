"""File > Import > MetaHuman Assembly: import a character from its CharacterAssemblyManifest.json."""

import logging

from pathlib import Path

import bpy

from bpy_extras.io_utils import ImportHelper  # type: ignore[import-not-found]

from .. import utilities
from ..constants import ToolInfo
from ..dna_core.assembly import MANIFEST_NAME, ManifestError
from ..properties import CharacterImportProperties
from . import importer


logger = logging.getLogger(__name__)


class CHARACTER_DNA_OT_import_assembly(bpy.types.Operator, ImportHelper, CharacterImportProperties):
    """Import a MetaHuman exported with "Export Character For DCC": head and body DNA with every texture wired from the manifest"""  # noqa: E501

    bl_idname = f"{ToolInfo.NAME}.import_assembly"
    bl_label = "Import MetaHuman Assembly"
    bl_options = {"UNDO", "PRESET"}
    filename_ext = ".json"

    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})  # pyright: ignore[reportInvalidTypeForm]
    import_grooms: bpy.props.BoolProperty(
        name="Grooms",
        default=True,
        description=(
            "Import the hair, brows, lashes, beard and peach fuzz as hair curves attached to the head. "
            "The eyelash card mesh is hidden only when the eyelash groom imports"
        ),
    )  # pyright: ignore[reportInvalidTypeForm]
    match_unreal_widths: bpy.props.BoolProperty(
        name="Match Unreal Widths",
        default=False,
        description=(
            "Use each groom's Unreal width override and root-to-tip taper (e.g. hair 0.012 cm, tip at 45%) "
            "instead of the per-strand widths stored in the groom files"
        ),
    )  # pyright: ignore[reportInvalidTypeForm]

    def draw(self, _context: object) -> None:
        layout = self.layout
        if layout is None:
            return
        layout.label(text=f"Pick the export's {MANIFEST_NAME}")
        layout.prop(self, "include_body")
        layout.prop(self, "import_shape_keys")
        layout.prop(self, "import_materials")
        layout.prop(self, "import_grooms")
        row = layout.row()
        row.enabled = self.import_grooms
        row.prop(self, "match_unreal_widths")
        layout.prop(self, "import_face_board")

    def execute(self, context: bpy.types.Context) -> set[str]:
        file_path = Path(bpy.path.abspath(self.filepath))
        if file_path.is_file() and file_path.name != MANIFEST_NAME:
            self.report({"ERROR"}, f'Pick "{MANIFEST_NAME}" (got "{file_path.name}")')
            return {"CANCELLED"}
        if round(context.scene.unit_settings.scale_length, 2) != 1.0:
            self.report({"ERROR"}, "The scene unit scale must be set to 1.0")
            return {"CANCELLED"}
        try:
            result = importer.import_assembly(
                file_path,
                self.properties,
                include_body=self.include_body,
                grooms=self.import_grooms,
                match_unreal_widths=self.match_unreal_widths,
            )
        except (ManifestError, RuntimeError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        failed = result.count("failed") or result.count("missing") or any(not g.ok for g in result.grooms)
        level = "WARNING" if failed or result.warnings else "INFO"
        self.report({level}, result.summary())
        return {"FINISHED"}

    @classmethod
    def poll(cls, _context: object) -> bool:
        return utilities.dependencies_are_valid()


classes = (CHARACTER_DNA_OT_import_assembly,)
