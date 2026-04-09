[![Dynamic Color Palette Cover](https://github.com/fwdotcom/dynamic-color-palette/raw/main/images/cover.png)](https://github.com/fwdotcom/dynamic-color-palette/blob/main/images/cover.png)

# Dynamic Color Palette

![Version](https://img.shields.io/badge/version-2.1.1-blue)
![License](https://img.shields.io/badge/license-GPL--3.0-blue)
![Blender](https://img.shields.io/badge/Blender-4.2%2B-orange)
![Godot](https://img.shields.io/badge/Godot-4.x-orange)

**One palette. Two textures. Zero material sprawl.**

Dynamic Color Palette is a Blender addon and Godot 4 shader that gives low-poly and stylized artists a complete, draw-call-efficient color pipeline — from palette generation to in-engine rendering — without juggling dozens of materials or textures.

---

## The Problem It Solves

Low-poly and stylized 3D workflows need lots of colors. The naive approach — one material per color — produces hundreds of materials and hundreds of draw calls. A hand-crafted atlas solves the draw-call problem but is tedious to build and painful to iterate on.

Dynamic Color Palette generates a structured HSV color palette as a GPU texture directly inside Blender. Every face on your mesh points its UV at a specific cell in that palette. In the game engine, a single material and a single draw call cover the entire mesh, no matter how many colors it uses.

---

## Two Workflows, One Tool

### Multicolor — One material, UV-driven color

All faces share a single material (`dcp_multicol`). Color is determined by where the UV island sits in the palette texture. The Godot shader reads both textures at the same UV coordinate and resolves color, roughness, metalness, and emission. One mesh, one material, one draw call.

### Singlecolor — Baked flat color, dedicated material per face

For faces that need a dedicated material — for example to allow code-side control in the engine (visibility toggles, runtime swaps, animation targets) — while still using the palette's initial color and PBR values, DCP creates a standalone Principled BSDF material with all values baked in. No texture lookup, no UVs needed. DCP caches these materials by palette cell so identical colors are never duplicated. No shader setup required in Godot.

Both workflows coexist in the same project.

---

## Feature Highlights

- **Procedural palette generation** — HSV grid with configurable columns, rows, pastel saturation, and shadow row; generated as a GPU-rendered texture inside Blender
- **PBR data texture** — a second texture encodes roughness, metalness, and emission strength per cell; three independent quadrants (Solid / Metal / Emission) with their own PBR values
- **Emission strips** — the emission quadrant is subdivided into vertical strength strips (up to 5 levels), letting you vary emission intensity without extra cells
- **Interactive color picker** — click a cell in the Blender Image Editor to assign it to selected faces or objects instantly; works in both Edit Mode and Object Mode
- **Multicolor assign** — sets UV islands for selected faces (Edit Mode) or all face UVs (Object Mode) to the chosen palette cell in one click
- **Singlecolor assign** — creates or reuses a baked material for the selected cell and assigns it to selected faces or objects
- **Material cleanup** — removes unused material slots and orphaned DCP materials in one click; respects Fake User
- **Info quadrant** — bottom-right corner of the texture renders your project name, studio, and license as a watermark, configurable per .blend file
- **Auto-export** — four independent export paths (Textures, JSON Config, GDShader, GDScript Util); each can be set or left empty; files are written on every Generate run
- **Regeneration safety** — if changes would shift UV coordinates or alter PBR values, DCP asks for confirmation before overwriting the existing palette
- **Per-.blend settings** — all palette configuration is stored on the Blender Scene, not in global preferences; each project has its own settings

---

## What's New in v2.1

The Godot 4 shader and GDScript utility class are now exported **directly from the DCP Configure dialog** — no more separate shader package. Four independent export paths replace the single export directory:

| Path | Written file(s) |
|---|---|
| Textures | `dcp_albedo.png`, `dcp_material.png` |
| JSON Config | `dcp_config.json` (layout constants, strip values, info lines) |
| GDShader | `dcp_multicol.gdshader` (UV-driven, reads palette at mesh UV), `dcp_singlecol.gdshader` (computes palette UV from int uniforms at runtime — no UV editing needed for color changes) |
| GDScript Util | `dcp_util.gd` (`class_name DCPUtil`, typed constants) |

All files are written on every Generate run. Point the paths at your Godot project directory and the pipeline is fully automated.

---

## What's New in v2.0

v1.x was a single Python script run with Alt+P; configuration meant editing constants at the top of the file. v2.0 is a proper Blender **addon** — install the `.zip` once via the Extension Manager and the panel persists across sessions with all settings stored per `.blend` file.

Configuration has moved entirely into the N-Panel: a **Configure dialog** replaces constant-editing, and the **Assign Multicolor Material** operator places UV islands at the correct palette cell in one click rather than requiring manual UV placement.

---

## Repository Structure

```
dynamic_color_palette/    ← Blender addon (GPLv3)
godot_4_shader/           ← LICENSE only (shader is now exported from the addon)
images/                   ← Screenshots and example textures
CHANGELOG.md
```

- [Addon — Installation & Usage](dynamic_color_palette/README.md)
- [Godot Shader — Migration notes](godot_4_shader/README.md)

---

## License

- Blender addon — **GPLv3** — [`dynamic_color_palette/LICENSE`](dynamic_color_palette/LICENSE)
- Exported Godot shader / GDScript files — **MIT** — [`godot_4_shader/LICENSE`](godot_4_shader/LICENSE)

---

*© 2026 Frank Winter | [www.frankwinter.com](https://www.frankwinter.com)*
