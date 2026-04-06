## SPDX-License-Identifier: MIT
##
## Dynamic Color Palette — UV Utility
## Version 2.0.8
## (C) 2026 Frank Winter
## https://fwdotcom.itch.io/dynamic-color-palette
##
## Static utility for setting DCP palette UV coordinates on an ArrayMesh.
## Mirrors cell_to_albedo_uv() from the DCP Blender addon (core/palette.py).
##
## Usage:
##   # Once at startup — reads texture dimensions from the ShaderMaterial:
##   DCPUtil.setup(shader_material, color_columns, color_rows, n_emission_strips)
##
##   # Per mesh — returns the modified ArrayMesh:
##   mesh = DCPUtil.setColor(mesh, DCPUtil.Quadrant.SOLID,    cell_x, cell_y)
##   mesh = DCPUtil.setColor(mesh, DCPUtil.Quadrant.METAL,    cell_x, cell_y)
##   mesh = DCPUtil.setColor(mesh, DCPUtil.Quadrant.EMISSION, cell_x, cell_y, emission_strip)

class_name DCPUtil

# ── Quadrant enum ────────────────────────────────────────────────────────────
enum Quadrant { SOLID, METAL, EMISSION }

# ── Static state (set by setup()) ────────────────────────────────────────────
static var _img_w: int = 0
static var _img_h: int = 0
static var _cols: int = 12
static var _rows: int = 12
static var _cs: int = 9   # cell_size
static var _margin: int = 9
static var _pal_w: int = 0
static var _pal_h: int = 0
static var _text_h: int = 0
static var _panel_h: int = 0
static var _strip_h: Array[int] = []


## Read texture dimensions from the ShaderMaterial's albedo_tex parameter
## and compute the internal layout.  Call once before any setColor() call.
##
## [param mat]      ShaderMaterial using dynamic_color_palette.gdshader.
## [param cols]     color_columns from Blender (default 12).
## [param rows]     color_rows from Blender (default 12).
## [param n_strips] Number of emission strips — len(emission_strengths) in Blender (default 1).
static func setup(mat: ShaderMaterial, cols: int = 12, rows: int = 12, n_strips: int = 1) -> void:
	var tex: Texture2D = mat.get_shader_parameter("albedo_tex") as Texture2D
	if tex == null:
		push_error("DCPUtil.setup: albedo_tex not set on ShaderMaterial.")
		return
	_img_w = tex.get_width()
	_img_h = tex.get_height()
	_cols = max(1, cols)
	_rows = max(2, rows)
	_build_layout(max(1, n_strips))


## Set every UV vertex on surface 0 of [param mesh] to the palette cell
## coordinate and return the modified ArrayMesh.
##
## [param mesh]     ArrayMesh to modify.
## [param quadrant] DCPUtil.Quadrant.SOLID, .METAL, or .EMISSION.
## [param x]        Column index [0, cols-1].
## [param y]        Row index    [0, rows-1] — 0 is the top row (same as Blender).
## [param emission] Emission strip index [0, n_strips-1]. Ignored for SOLID/METAL.
## [param surface]  Surface index to modify (default 0).
static func setColor(
		mesh: ArrayMesh,
		quadrant: Quadrant,
		x: int,
		y: int,
		emission: int = 0,
		surface: int = 0,
) -> ArrayMesh:
	if _img_w <= 0 or _img_h <= 0:
		push_error("DCPUtil.setColor: call setup() first.")
		return mesh

	var uv: Vector2 = _cell_to_uv(quadrant, x, y, emission)
	_write_uv(mesh, surface, uv)
	return mesh


# ── Internal ──────────────────────────────────────────────────────────────────

static func _build_layout(n_strips: int) -> void:
	# Matches get_cell_size() + get_layout() in palette.py.
	# DEFAULT_CELL_SIZE_MIN = 9, minimum 5 px per strip.
	_cs = max(9, n_strips * 5)
	_margin = _cs
	_pal_w = _cols * _cs
	_pal_h = _rows * _cs
	_text_h = _cs * 2
	_panel_h = _pal_h + _text_h

	# Strip heights — matches get_emission_layout() in palette.py.
	# Surplus pixels distributed to the first strips.
	_strip_h.clear()
	var base: int = _cs / n_strips
	var rem: int = _cs % n_strips
	for i in n_strips:
		_strip_h.append(base + (1 if i < rem else 0))


static func _cell_to_uv(quadrant: Quadrant, x: int, y: int, emission: int) -> Vector2:
	x = clampi(x, 0, _cols - 1)
	y = clampi(y, 0, _rows - 1)
	emission = clampi(emission, 0, _strip_h.size() - 1)

	# Quadrant origins (px from bottom-left) — matches quad_origins[] in palette.py.
	var ox: int
	var oy: int
	match quadrant:
		Quadrant.SOLID:
			ox = _margin
			oy = _panel_h + _text_h
		Quadrant.METAL:
			ox = _margin + _pal_w + _margin
			oy = _panel_h + _text_h
		Quadrant.EMISSION:
			ox = _margin
			oy = _text_h

	var px: float = ox + x * _cs + _cs * 0.5
	# y=0 is the topmost row → largest pixel-y value.
	var cell_bottom: float = oy + (_rows - 1 - y) * _cs

	var py: float
	if quadrant == Quadrant.EMISSION:
		var strip_bottom: int = 0
		for i in emission:
			strip_bottom += _strip_h[i]
		py = cell_bottom + strip_bottom + _strip_h[emission] * 0.5
	else:
		py = cell_bottom + _cs * 0.5

	return Vector2(px / _img_w, py / _img_h)


static func _write_uv(mesh: ArrayMesh, surface: int, uv: Vector2) -> void:
	if surface < 0 or surface >= mesh.get_surface_count():
		push_error("DCPUtil.setColor: surface %d out of range." % surface)
		return

	var arrays: Array = mesh.surface_get_arrays(surface)
	var verts: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	if verts == null or verts.is_empty():
		push_error("DCPUtil.setColor: mesh has no ARRAY_VERTEX.")
		return

	var uvs := PackedVector2Array()
	uvs.resize(verts.size())
	uvs.fill(uv)
	arrays[Mesh.ARRAY_TEX_UV] = uvs

	var flags := mesh.surface_get_format(surface)
	mesh.surface_remove(surface)
	mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays, [], {}, flags)
