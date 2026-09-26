# 08: Character Assembly (Render-Ready Materials, Hair and Clothing)

**Depends on:** 01 (rig instance, import). Independent of 02-07; do it after the rig works.
**Confidence:** MEDIUM on the input format, now checked against one real export (Slice 0, 2026-09-25; see `dev-docs/FINDINGS.md` "Character Assembly Slice 0"). Still LOW on how Poly Hammer's own Assembly addon behaves, which we don't copy anyway.

## Purpose
Turn an imported MetaHuman from "a rig that evaluates" into something **render-ready** in Blender: correct materials, hair and clothing.

**Status: complete (2026-09-26).** Slices 0-3 are merged; see `dev-docs/FINDINGS.md` "Character Assembly: complete". **Out of scope, by decision:** hair physics (section D) and the lighting and camera rig (section E). Both sections are kept below as reference only.

## Input: the "Export Character For DCC" folder (verified, Slice 0)
Produced by Poly Hammer Interchange 0.2.1 on UE 5.8.3 (closed-source freeware; we read its *output* only). One folder per character:

| Path | What it is |
|---|---|
| `CharacterAssemblyManifest.json` | **The entry point.** `schema_version: 2`. Lists DNAs, per-mesh materials, components (clothing and grooms) and every material's textures and parameters. All paths are **relative to the folder**, with `/` separators. |
| `ExportManifest.json` | MetaHuman Creator's file, extended: `metaHumanName`, `exportPluginVersion`, `exportEngineVersion`, `exportedAt` (can be **empty**), `dna{head,body}`, `folders{maps}`, `files{maps[]}`. Not needed if the assembly manifest is present. |
| `ExportPlan.json` | Interchange's Unreal-side build plan (Blueprint class names, sockets, used slots). **Ignore it**; the assembly manifest carries everything useful in cleaner form. |
| `head.dna`, `body.dna` | Standard DNAs; read cleanly with `dna_core` (head: 8 LODs, 870 joints, 50 meshes, 782 blend-shape channels / 858 targets; body: 4 LODs, 342 joints, 4 meshes, no blend shapes, 72 RBF solvers). |
| `Geometry/head.json`, `Geometry/body.json` | Per-mesh extras: `faces`, `uvs`, `source_slots` and **`visible_triangles`** (the skin-culling mask under clothes: body LOD0 keeps 47,392 of 60,816 triangles). Hash-checked against the DNA (`dna_sha256`, `geometry_sha256`). |
| `Grooms/*.abc` | Alembic curves, one file per groom: hair, eyebrows, eyelashes, beard, mustache, fuzz (peach fuzz). **Z-up, centimetres.** |
| `Clothing/outfits.fbx` | All garments in one skinned FBX (one mesh, own 341-bone armature rooted at `pelvis`). |
| `Maps/*.png` | Baked textures, named `<Part>_<Map>.png`. 38 files in the sample. |
| `Meshes/` | Present but **empty** in the sample. Don't depend on it. |

### Manifest v2 keys that matter
- `dna{head, body}`: DNA paths.
- `rigs{head|body}.capabilities{valid, joints, meshes, lods}`: a cheap sanity check against the loaded DNA.
- `dna_geometry[]`, one per DNA: `{role, path (Geometry json), dna_sha256, geometry_sha256, meshes[]}`. Each mesh has `{mesh_index, lod, skin, material{slot, name, type, profile, occlusion}}`. `profile: "hidden"` means the mesh is not rendered (saliva, cartilage, and the eyelash *card* mesh, replaced by the eyelash groom).
- `materials[]`: `{name, type, slot, display_name, profile, textures[], skin?, fabric?, hair_color?}`.
  - `textures[]`: `{role, path, color_space ("sRGB" | "Non-Color"), recovery_source?}`. **Link textures by `role` from here instead of guessing file names.**
  - `hair_color`: `melanin`, `redness`, `tint`, `white_amount`, `roughness`, `color` and colour `ramps` (`root_to_tip`, `variation`, `white_strands`). This maps well onto Blender's Principled Hair BSDF (melanin model).
  - `fabric`: `color`, `stitch_color`, `normal_strength`, `micro_normal_strength`, `micro_scale`, `macro_scale`.
- `components[]`: `{id, name, type ("fbx" | "alembic"), path, role ("clothing" | "hair"), attach_to ("body" | "head"), binding ("auto" | "surface"), representation, skinned, transform[16], materials[] (with `region`: scalp, brows, beard, lashes, fuzz), groom{…}, groom_groups[]{group_id, physics{…}}}`. Every transform in the sample is identity.
- `required_capabilities[]`: a feature list. **Refuse or warn on any capability we don't know**, rather than guessing.
- `diagnostics[]`: exporter warnings (empty in the sample). Show them in the import report.

## Sub-features

### A. Materials
- Drive texture linking from `materials[].textures[].role`, with the colour space from the manifest. Fall back to the existing `Maps/` file-name convention only when there is no manifest.
- Map names the current importer already finds: `Head_Basecolor`, `Head_Normal`, CM1-3 and WM1-3 (the wrinkle maps), `Body_Basecolor`, `Body_Normal`, `Teeth_Color`, `Teeth_Normal`.
- **Reality differs from the old assumption for eyes:** the importer expects `Eyes_Color` / `Eyes_Normal`, but the export has `Eyes_ScleraBasecolor`, `Eyes_IrisBasecolor`, `Eyes_ScleraNormal`, `Eyes_IrisNormal`, `Eyes_Veins` and `Eyes_Dust`. **This is the cause of the "eyes import without textures" report.** There is no `Eyelashes_Color` either; lashes are a groom now.
- Maps not wired yet:
  - head and body: `SRMF`, `Scatter`, `DetailNormal`;
  - teeth: `Mask001`, `Mask002`;
  - clothing: AO, Normal, StitchMask, MicroHeight, MicroNormal, MacroVariation;
  - hair: `Hair_HighlightsMask`.
  - SRMF, worked out from the images (FINDINGS "Slice 1"): R Specular, G Roughness, B Metallic (0 on skin), A probably a fuzz mask (not connected). Scatter goes to Subsurface Weight, and the detail normal is a tiling pore map (tiling not in the export).
- Skin keeps the rig's wrinkle-map masks (Texture Logic node, unchanged). This export's CM1-3 and WM1-3 are *offset* maps (centred on 0.5). They're detected, and blended as offsets (colour in sRGB space) with a strength per facial area; see FINDINGS "Wrinkle offsets".
- Hide meshes whose material `profile` is `"hidden"`, in the viewport and render, and keep them hidden across LOD switches. The eyelash card mesh is hidden only when the eyelash groom imports (Slice 2).
- Build a **texture-linking report**: for each material, the roles found, missing or unused.

### B. Hair import
The DCC export **does include hair**, as standard Alembic `ICurves` (`/Groom/Curves`).
- **Per strand:** `uv` (the root UV, in the head's LOD0 UV layout, not flipped), `groom_guide`, `groom_group_id` (always 0 in the sample), `groom_id`, and `groom_sim_*`.
- **Per point:** `P`, `width`, and `groom_color` (hair only).
- There is **no `groom_root_uv`**: Interchange uses the standard `uv` parameter.
- **Basis:** linear, with 4-45 points per strand.
- **Axes:** file (x, y, z) cm → Blender (x, −y, z) / 100 m. This is a mirror, not a 180° turn: proven by matching root UVs to the head surface, 0.05-0.3 cm median error against 3-9 cm for the rotation.
- **Blender 5.1's own Alembic importer is not enough.** It keeps position and radius (= width / 2) only. It drops `uv`, `groom_guide`, `groom_id`, `groom_group_id`, `groom_color` and every `groom_sim_*`. It also applies a Y-up conversion (x, −z, y) with no cm→m scale, so it needs a fix-up rotation and scale.
- **Importer requirements:**
  - Drop guide strands (`groom_guide == 1`). In eyelashes and fuzz they are collapsed to the origin.
  - Clamp negative widths to 0 (the beard has 67 of them).
  - Keep the root UV as a `surface_uv_coordinate` attribute, so strands can attach to the head through Blender's Curves surface.
- **Cost:** hair is 112,776 strands and 1.72 M points; fuzz is 75,737 strands. Offer per-groom toggles and a viewport strand percentage.
- Hair shading uses the manifest's `hair_color`, on the Principled Hair BSDF (melanin, for Cycles). EEVEE renders that far lighter and redder, so an EEVEE output uses Unreal's resolved `color`. `white_amount` and the ramps have no input.

### C. Clothing
- One FBX with every garment, skinned to its own 341-bone armature (body DNA has 342 joints: the extra is `root`). Every FBX bone is in the body rig by name, rest within 0.008 mm.
- Rebind the garment to the body rig by bone name.
- Material slots: 8 in the FBX (`…_Short`, `…_Shirt`, `…_Short_2` … `…_Shirt_7`) against 2 in the manifest. **Verified:** only the first two have faces; `_2` … `_7` are empty and dropped.
- Apply the body skin-culling mask from `Geometry/body.json` `visible_triangles` so skin doesn't poke through: a face with none of its triangles listed is covered. The mask fits the rest pose, so the import widens it by up to 3 rings of neighbours the garment covers at rest (FINDINGS "Slice 3").

### D. Hair dynamics: OUT OF SCOPE
**Decided (2026-09-26): not built.** Grooms import static, and the manifest's physics settings are ignored. The notes below are kept as reference in case this is ever reopened.
- The manifest gives Unreal's per-group physics (`simulate` is false for every groom in the sample): sub_steps, iteration_count, air_drag, bend damping and stiffness, collision_radius, gravity.
- Blender's **XPBD Solver** and Hair Dynamics assets exist only in **Blender 5.2+**, and are experimental there. Convert only settings with a real equivalent, and mark the feature unsupported on 5.1. **Decided:** minimum Blender stays 5.1; physics is gated to 5.2+ and disabled with a clear message on 5.1.

### E. Lighting: OUT OF SCOPE
**Decided (2026-09-26): not built.** No lighting or camera presets; use your own scene lighting. The note below is reference only.
Simple review presets (a 3-point rig and HDRI) that make skin and hair readable. Our own minimal scope.

## Slices
| Slice | Scope | Status |
|---|---|---|
| 0 | Inspect a real export | **Done** (2026-09-25) |
| 1 | Import from the manifest: head and body through the existing importer, every texture wired by manifest role and colour space (no file-name guessing), the eye-texture fix, hidden meshes hidden, texture report, capability check | Merged (PR #10); see FINDINGS "Slice 1" |
| 2 | Static grooms: our own Alembic curve reader, guide filtering, axis and scale, root-UV surface attachment, hair shader. Fuzz imports hidden in the viewport, enabled for render, with a one-click toggle | Merged (PR #12). A numpy Ogawa reader (hair in 52 ms), so no native library; see FINDINGS "Slice 2" |
| 3 | Clothing FBX, rebound to the body rig, with body-under-clothes hiding (skin culling) | Merged (PR #14). LOD0, fabric from the manifest, hiding toggle; no poke-through at rest or posed; see FINDINGS "Slice 3" |
| 4 | Full materials: SRMF, scatter, detail normal, eyes, teeth masks, fabric | **Covered by slices 1 and 3.** SRMF (RGB), scatter, detail normal, eyes and fabric are wired. Loaded but not connected (meaning not verified): teeth masks, eye dust, SRMF alpha, hair highlight mask |
| 5 | Hair physics (XPBD), Blender 5.2+ | **Out of scope** (decided 2026-09-26) |
| 6 | Lighting and camera presets | **Out of scope** (decided 2026-09-26) |

### Slice 1 assumptions checked against the export
- **Held:** there is one manifest per character; DNAs are next to it; `Maps/` is next to the DNAs, which the existing importer already searches; wrinkle-map file names match the existing importer exactly; both DNAs load cleanly.
- **Changed:**
  - The manifest also carries texture roles, colour spaces and hidden-mesh flags. Use them instead of hard-coded names.
  - Eye texture names differ from the importer's, so Slice 1 must map them.
  - Hair *is* in the export, as Alembic.
  - Extra files exist: `ExportPlan.json`, `Geometry/*.json`, and an empty `Meshes/`.
  - `exportedAt` can be empty.

## Implementation notes
- Keep this an optional module, so the rig core has no dependency on it.
- The manifest reader belongs in `dna_core` (no `bpy`), with synthetic manifests in CI. **Never commit a real export**; `.gitignore` blocks `*.abc`, `*.dna` (except the old fixtures), the manifests and `tests/assembly_exports/`.
- Reuse the rig-instance concept from 01, so materials, hair and clothing belong to one character instance. The GPL `Scene.character_assembly.rig_instance_proxies` hook already records `manifest_path` and `components[].source_path`.
- Clean-room rules from `00-overview.md` apply. The Assembly addon is a separate commercial Poly Hammer product, and Interchange is closed; build from behaviour and from the files only.

## Acceptance criteria
- Importing a manifest yields textured skin, eyes, teeth and hidden helper meshes, with a report of missing and unused textures.
- Wrinkle maps respond to expressions driven from the face board.
- Grooms appear on the head in the right place (roots within 0.5 cm of the scalp), with guides removed.
- Clothing follows the body rig, and no skin shows through it at rest or in a posed test (arm raised, knee bent).
- ~~Hair dynamics run without artifacts during a head-turn test~~: out of scope.
