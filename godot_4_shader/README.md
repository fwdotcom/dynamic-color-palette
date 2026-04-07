# Dynamic Color Palette — Godot 4 Shader

![Version](https://img.shields.io/badge/version-2.1-blue)
![License](https://img.shields.io/badge/license-MIT-blue)
![Godot](https://img.shields.io/badge/Godot-4.x-orange)

> **As of version 2.1**, the Godot shader files are exported directly from the DCP panel
> in Blender into your Godot project directory. This separate shader package is no longer
> needed. This directory only contains the license file for reference.

---

## Migrating from v2.0

In v2.0, `dynamic_color_palette.gdshader` and `dcp_util.gd` had to be copied manually
from this package into your Godot project.

As of v2.1, the DCP configuration dialog in Blender provides four separate export paths:

| Field | Exported file(s) |
|---|---|
| Textures | `dcp_albedo.png`, `dcp_material.png` |
| JSON Config | `dcp_config.json` |
| GDShader | `dcp_multicol.gdshader` |
| GDScript Util | `dcp_util.gd` |

The files are written automatically when you click **Generate / Regenerate Palette**.
Point the export paths to your Godot project directory (e.g. `res://dcp/`) and the files
will land there on every export.

---

## License

MIT — see [LICENSE](LICENSE).

---

*© 2026 Frank Winter | [www.frankwinter.com](https://www.frankwinter.com)*
