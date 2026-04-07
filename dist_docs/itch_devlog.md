<!-- itch.io — Devlog entry -->

# DCP 2.0: Full Blender Add-on

This is a full rewrite — and the last time you'll need to edit a Python file to change a color.

---

## What changed

v2.0 is a proper Blender addon — drag the ZIP into Blender 4.2 and it installs via the Extension Manager. The DCP panel lives in the N-Panel and persists across sessions. All settings are stored per .blend file, so each project has its own palette configuration without interfering with others.

The workflow is fundamentally different from v1.x:

**🖱️ Assign in one click**
Select faces in Edit Mode or objects in Object Mode, pick a color cell, click Assign. DCP places the UV islands at the exact cell center — no manual UV editing required.

**🎨 Interactive picker**
Open the Blender Image Editor alongside the 3D Viewport, enable Pick From Image Editor, and click directly on the palette. With a selection active, the assign happens immediately.

**📐 Two material workflows**
Multicolor: all faces share one UV-driven material — one draw call in the engine. Singlecolor: baked flat Principled BSDF per palette cell, cached and deduplicated — no shader or UV setup needed in Godot.

**⚡ Emission strips**
The emission quadrant is subdivided into vertical strength strips — up to 5 levels, each occupying its own UV band. Vary emission intensity without adding cells to the palette.

**🧹 Regeneration safety**
If you change columns, rows, saturation, or PBR values after assigning faces, DCP warns you before overwriting — because those changes shift UV coordinates on existing meshes.

---

## Godot shader

The Godot 4 spatial shader ships as a separate download (MIT license — use it freely in commercial projects). It reads both textures at the mesh UV and resolves color, roughness, metalness, and emission. An `emission_scale` uniform lets you animate or script emission intensity at runtime without touching the texture.

---

## What's next

The main thing on the horizon for v3 is multi-palette support — multiple palette configurations per project, each with its own prefix and independent settings. Useful for projects with distinct material families (e.g. environment vs. characters) that shouldn't share a palette.

If you run into anything unexpected or have workflow feedback, drop it in the comments.

*— Frank*
