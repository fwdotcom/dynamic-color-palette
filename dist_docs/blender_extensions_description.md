Generate palette textures and assign colors to mesh faces via UV lookup — built for low-poly and stylized game workflows.

DCP creates two GPU-rendered textures inside Blender: an HSV color palette (albedo) and a PBR data map (roughness, metalness, emission). All faces on a mesh share one material; color is determined by UV position in the palette. One mesh, one material, one draw call in the game engine.

---

## Workflows

**Multicolor — UV-driven color**
All faces use `dcp_multicol`. The included Godot 4 shader reads both textures at the UV coordinate and resolves color and PBR values at runtime.

**Singlecolor — Baked flat color**
DCP creates a standalone Principled BSDF with color and PBR values baked in. No texture or UV setup required in the engine. Both workflows coexist in the same project.

---

## Features

- HSV palette with configurable columns, rows, pastel saturation, and shadow row
- PBR data texture with three independent quadrants: Solid, Metal, Emission
- Emission strips: up to 5 strength levels per emission cell
- Interactive picker in the Image Editor; works in Edit Mode and Object Mode
- One-click Assign for both Multicolor and Singlecolor workflows
- Material cleanup removes unused slots and orphaned materials
- Auto-export to four independent directories: Textures, JSON Config, GDShader (`dcp_multicol.gdshader`, `dcp_singlecol.gdshader`), GDScript Util (`dcp_util.gd`)
- Regeneration safety: warns before changes that shift UV coordinates
- All settings stored per .blend file — each project has its own palette

---

## Godot 4 Shaders

As of v2.1, two Godot 4 spatial shaders are exported directly from the DCP Configure dialog — no separate download needed:

- **`dcp_multicol.gdshader`** — reads both palette textures at the mesh UV coordinate and resolves color, roughness, metalness, and emission at runtime. Use this on meshes where all faces share the UV-driven `dcp_multicol` material.
- **`dcp_singlecol.gdshader`** — computes the palette UV at runtime from integer uniforms (`quadrant`, `cell_a_x`, `cell_a_y`, `cell_b_x`, `cell_b_y`, `emission_strip`); supports smooth blending between two palette cells via `mix_a_b` (0.0 = Color A, 1.0 = Color B); layout constants are baked in at export time. Use this when you need to change or blend a mesh's palette color from code without modifying its UVs.

A GDScript utility class (`dcp_util.gd`, `class_name DCPUtil`) with typed layout constants is also exported alongside the shaders.
