<!-- itch.io — Devlog entry: DCP 2.1 -->

# DCP 2.1: Shaders and Config Exported Directly from Blender

The Godot side of the pipeline is now fully automated — shader files, layout config, and a GDScript utility class are written straight into your Godot project on every palette generate.

---

## What changed

**Four independent export paths**
The single export directory is replaced by four separate fields in the Configure dialog — Textures, JSON Config, GDShader, and GDScript Util. Each can be set or left empty independently. Point them at your Godot project directory and the files land there automatically on every Generate run.

**Two Godot shaders**
`dcp_multicol.gdshader` is the UV-driven shader for meshes where all faces share the DCP palette material — same as before, now exported automatically and renamed to match DCP conventions.

`dcp_singlecol.gdshader` is new: it computes the palette UV at runtime from integer uniforms (`quadrant`, `cell_x`, `cell_y`, `emission_strip`), with layout constants baked in at export time. Use this when you need to change a mesh's color from code without touching its UVs.

**GDScript utility class**
`dcp_util.gd` (`class_name DCPUtil`, extends `RefCounted`) exports the same layout constants as typed GDScript values — columns, rows, cell size, emission factor, strip values, image names, info lines. No more manual copy-paste from a JSON file.

**JSON config**
`dcp_config.json` is still written alongside the shaders for tooling that prefers JSON over GDScript.

---

## No separate shader download

The `dynamic_color_palette_godot_shader.zip` package is retired. Everything the Godot side needs is now generated directly from the addon. The `godot_4_shader/` directory in the repository now only contains the MIT license for reference.

---

## What's next

Multi-palette support (v3) remains on the horizon — multiple palette configurations per project, each with its own prefix and independent settings.

*— Frank*

---

<!-- itch.io — Devlog entry: DCP 2.0 -->

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
