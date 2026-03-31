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
- Auto-export of `dcp_albedo.png` and `dcp_material.png` on Generate
- Regeneration safety: warns before changes that shift UV coordinates
- All settings stored per .blend file — each project has its own palette

---

## Godot 4 Shader

A matching spatial shader is available as a separate download (MIT) at:
https://fwdotcom.itch.io/dynamic-color-palette
