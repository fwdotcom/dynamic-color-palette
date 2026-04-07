# Changelog

All notable changes to Dynamic Color Palette are documented here.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed
- Pick From Image Editor is now reset to OFF when a blend file is opened —
  previously a saved ON state would show the button as active without a running
  modal operator

### Added
- Export now writes a `dcp_config.json` alongside the palette textures when an
  export path is set; contains `albedo_image_name`, `material_image_name`,
  `emission_strips`, `emission_factor`, `color_columns`, `color_rows`,
  `cell_size`, `info_line1`, `info_line2`, and `info_line3`; emission strip
  values are rounded to 2 decimal places
- Export also writes a `dcp_config.gd` GDScript class (`class_name DCPConfig`,
  extends `RefCounted`) with the same values as typed constants
  (`ALBEDO_IMAGE_NAME`, `MATERIAL_IMAGE_NAME`, `COLOR_COLUMNS`, `COLOR_ROWS`,
  `CELL_SIZE`, `EMISSION_FACTOR`, `EMISSION_STRIPS`, `INFO_LINE1/2/3`);
  ready to use in Godot 4 without manual copy-paste

## [2.0.7] – 2026-03-31

### Fixed
- Multicol and Singlecol materials now render identical colors for the same
  palette cell — `dcp_albedo` TexImage colorspace set to `"Non-Color"` so the
  linear GPU-rendered pixel values are no longer incorrectly treated as sRGB
- After palette generation / regeneration the panel state is reset to defaults:
  quadrant → Solid, Cell X/Y → 0, pick mode stopped cleanly; also fixes the
  "picker not found" issue that required a Pick-from-Image-Editor toggle after
  regeneration

## [2.0.6] – 2026-03-31

### Fixed
- Unregistering the addon now resets `palette_generated`, `multicol_mat`,
  `singlecol_mats`, and `pick_from_image_editor` on all scenes before removing
  the property type — prevents stale DCP state from reappearing after
  reinstall

## [2.0.5] – 2026-03-30

### Fixed
- Assign Multicolor (Edit Mode): unselected faces no longer sample arbitrary
  palette cells when `dcp_multicol` is added to a mesh for the first time —
  they are initialised to white (Solid quadrant, column `0`, last row)
- Assign Multicolor (Edit Mode): removed misplaced operator docstring tooltip
  from the Generate / Regenerate Palette button

### Added
- Assign Multicolor automatically creates a `UVMap` UV layer if the mesh has
  none — applies in both Edit Mode and Object Mode, eliminating the previous
  "No UV layer" warning for fresh meshes

## [2.0.0] – 2026-03-26

### Added
- Full Blender addon structure (install via Extension Manager, settings stored per .blend)
- HSV palette with Solid, Metal, Emission quadrants
- UV lookup textures: albedo and PBR material map
- Picker image rendered at configurable cell size; works in Edit Mode and Object Mode
- N-Panel with Configure dialog (invoke_props_dialog) and Image Editor pick workflow
- Multicolor UV-mapped Principled BSDF material
- Singlecolor baked Principled BSDF material with pointer-based cache
- Snapshot mechanism for regeneration safety confirmation
- Per-.blend info quadrant (project name, studio, license watermark)
- Auto-export of `dcp_albedo.png` and `dcp_material.png` on Generate
- Object Mode panel: assign materials to selected mesh objects
- Multi-object Edit Mode: assign to faces across all objects in the edit session
- Status bar hint while pick mode is active
- Dynamic button labels reflecting live selection count and object count

### Changed
- Cleanup Unused Slots operates on all objects in the edit session (Edit Mode)
  or all selected objects (Object Mode)
- Assign and Cleanup buttons disabled when no valid selection exists

### Fixed
- N-Panel disappearing when Image Editor was closed while pick mode was active
- Face count in Edit Mode panel incorrect with multi-object edit sessions
- Modal pick-guard checked only active object, blocking picks on non-active participants

> **Note:** v1.x was a single-file Python script (Alt+P, constants-based configuration).
> The v2.0 rewrite is a proper addon and is not backwards-compatible with v1.x setups.