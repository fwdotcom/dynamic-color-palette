# Dynamic Color Palette — Blender Addon

![Version](https://img.shields.io/badge/version-2.0.7-blue)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)
![Blender](https://img.shields.io/badge/Blender-4.2%2B-orange)

Blender addon for generating palette textures and assigning colors to mesh faces via UV lookup.

---

## Requirements

- Blender **4.2 or later** (uses the Extension System)

---

## Installation

1. Drag and drop `dynamic_color_palette.zip` into Blender.
2. Enable the addon. A `Installed "dynamic_color_palette"` message appears in the system console.

The DCP panel is now available in the **3D Viewport N-Panel → DCP tab**, visible in both Object Mode and Edit Mode.

---

## Quick Start

### 1. Generate the palette

1. Open the **DCP** tab in the N-Panel (`N` key in 3D Viewport).
2. Click **Configure…** to open the palette configuration dialog.
3. Adjust columns, rows, PBR values, and emission strips as needed (defaults work fine for a first try).
4. Click **Generate / Regenerate Palette** inside the dialog (or close it and click **Generate Palette** in the panel).

DCP creates three images in `bpy.data.images`:

| Image | Purpose |
|---|---|
| `dcp_albedo` | HSV color palette (sRGB) |
| `dcp_material` | PBR data: R=Roughness, G=Metalness, B=Emission Strength |
| `dcp_picker` | Larger picker image shown in the Image Editor |

It also creates one material: `dcp_multicol` — a Principled BSDF driven entirely by UV lookup.

### 2. Pick and assign colors

Open an Image Editor alongside the 3D Viewport. Click **Pick From Image Editor** in the DCP panel — DCP automatically displays `dcp_picker` there. Click any cell to preview the color, or to assign it immediately as **Multicolor Material** if faces or objects are selected. Press Esc or click the button again to stop.

Alternatively, set the quadrant (Solid / Metal / Emission) and Cell X / Cell Y manually in the panel.

**Multicolor workflow** (one material, UV-driven):

1. Select faces in Edit Mode or objects in Object Mode.
2. Choose a color cell via the picker or the Cell X / Cell Y controls.
3. Click **Assign Multicolor Material**. DCP places UV islands at the exact palette cell center and assigns `dcp_multicol`.

**Singlecolor workflow** (dedicated material, baked flat color):

Use this when a face needs its own material — for example so it can be controlled independently in the engine (visibility, runtime swap, animation) — while its initial color and PBR values should come from the DCP palette.

1. Choose a color cell first — via the picker or Cell X / Cell Y — **without** anything selected. (If faces or objects are already selected when you click in the Image Editor, the picker assigns Multicolor instead.)
2. Select the faces in Edit Mode or objects in Object Mode.
3. Click **Assign Singlecolor Material**. DCP creates or reuses a flat Principled BSDF material (`dcp_singlecol_<hex>`) with all values baked in. No UVs or textures required.

### 3. Export

If you set an **Export Path** in the Configure dialog, DCP writes `dcp_albedo.png` and `dcp_material.png` to that directory automatically on every Generate run. `dcp_picker` is an internal Blender UI image and is not exported. To save the textures manually, use **Image → Save As** in the Image Editor.

### 4. Cleanup

**Cleanup Unused Slots** removes empty material slots and DCP singlecolor materials not referenced by any object. Respects Fake User.

---

## Configure Dialog

Opened via the **Configure…** button. Changes apply immediately to the scene. Close with OK.

| Setting | Description |
|---|---|
| Columns / Rows | Grid size of each quadrant (1–32 × 2–32) |
| Saturation | HSV saturation shift towards pastel (0 = off, 1 = full pastel) |
| Shadow | HSV value reduction for the bottom shadow row |
| Solid / Metal / Emission Roughness + Metalness | PBR values baked into `dcp_material` per quadrant |
| Emission Factor | Global emission multiplier applied in the Blender shader node tree |
| Strips | Emission strength levels (1–5 strips); each strip occupies a vertical band in the emission quadrant |
| Export Path | Directory for auto-saving `dcp_albedo.png` and `dcp_material.png` on every Generate run |

**Regeneration safety:** if you change columns, rows, saturation, shadow, any PBR value, or the emission strip list, and a palette already exists, DCP asks for confirmation before regenerating — because those changes shift UV coordinates or alter baked PBR values on existing meshes.

Settings that do **not** trigger a confirmation: emission factor, export path, info quadrant text and colors.

---

## Advanced: Constants in `__init__.py`

All user-facing settings live in the N-Panel and are stored per .blend file. A small set of **developer constants** in [`__init__.py`](__init__.py) control behavior that has no UI control. Edit these before packaging the addon if you need to customize them.

| Constant | Default | Effect |
|---|---|---|
| `MAX_EMISSION_STRIPS` | `5` | Hard upper limit on the number of emission strips. Increase if you need more than 5 strength levels. |
| `DEFAULT_CELL_SIZE_MIN` | `9` | Minimum pixel height of a palette cell. The actual cell height is `max(DEFAULT_CELL_SIZE_MIN, n_strips * 5)` — it grows automatically with strip count. Raise this if you need larger cells for better visual clarity. |
| `DEFAULT_FONT_SIZE` | `10` | Font size (in points) used to render text in the info quadrant. |
| `DEFAULT_*` values | various | Fallback values applied when **Reset to Defaults** is clicked. Changing these customizes what "factory defaults" means for your team or project template. |

These constants do not affect running instances — they are read at class-definition time. After editing, reload the addon (disable → enable in Preferences, or press F8 in the Text Editor).

---

## License

GPLv3 — see [LICENSE](LICENSE).

---

*© 2026 Frank Winter | [www.frankwinter.com](https://www.frankwinter.com)*
