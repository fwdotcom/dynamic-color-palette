# SPDX-License-Identifier: GPL-3.0-or-later
"""GPU-based texture generation for Dynamic Color Palette.

All palette images are rendered off-screen using Blender's ``gpu`` module
(OpenGL / Metal / Vulkan depending on the platform) and stored as packed
``bpy.types.Image`` datablocks.  No external image-editing library is required.

Three images are produced on each generation pass:

``dcp_albedo``
    Full-size texture sheet containing the colour palette for all three
    quadrants (Solid, Metal, Emission) plus an info/copyright area.
    Sampled by the ``dcp_multicol`` material's first ``TexImage`` node.

``dcp_material``
    Same layout as ``dcp_albedo`` but encodes PBR data:
    R = Roughness, G = Metalness, B = normalised emission strength.
    Sampled by the ``dcp_multicol`` material's second ``TexImage`` node
    (colour-space set to *Non-Color*).

``dcp_picker``
    Enlarged version of the colour palette (no info area, 1.5× cell size)
    used by the Image Editor colour-picker modal operator.

Rendering pipeline
------------------
1. :func:`_render_to_buffer` sets up a ``GPUOffScreen``, draws all geometry
   and text into it, and reads back the pixel buffer as a flat float list.
2. :func:`_create_image` converts the buffer into a packed
   ``bpy.types.Image`` datablock.
3. :func:`_save_image` optionally writes the image to disk as PNG.
4. :func:`_render_sheet` orchestrates steps 1–3 for both albedo and material
   textures.
5. :func:`_render_picker_image` runs a simplified version of step 1 for the
   picker image.
6. :func:`_build_picker_preview` copies picker image pixels into a Blender
   preview collection (``PColl``) used to render the thumbnail in the UI.
"""
from __future__ import annotations

import os
from typing import Optional

import bpy
import blf
import gpu
import mathutils
from gpu_extras.batch import batch_for_shader

from .. import VERSION, DEFAULT_FONT_SIZE, PICKER_IMAGE_NAME
from .palette import (
    hex_color, get_layout, get_picker_cell_size,
    get_emission_layout, _invalidate_emission_cache,
)


# ============================================================================
# MODULE-LEVEL CACHE
# ============================================================================

_picker_previews: Optional[object] = None
"""Module-level holder for the picker PColl (``bpy.utils.previews`` collection).

Accessed only through :func:`_get_picker_previews` and
:func:`_set_picker_previews` so that :func:`~__init__.unregister` can free
the collection without importing the whole module at the top level.
"""


def _get_picker_previews():
    """Return the current picker preview collection, or ``None``.

    Returns:
        The ``bpy.utils.previews.ImagePreviewCollection`` instance, or
        ``None`` if it has not been created yet.
    """
    return _picker_previews


def _set_picker_previews(value) -> None:
    """Replace the module-level picker preview collection reference.

    Args:
        value: A ``bpy.utils.previews.ImagePreviewCollection`` instance,
            or ``None`` to clear the reference after the collection has
            been freed.
    """
    global _picker_previews
    _picker_previews = value


# ============================================================================
# GPU DRAWING PRIMITIVES
# ============================================================================

def _ortho_matrix(width: int, height: int) -> mathutils.Matrix:
    """Build a column-major orthographic projection matrix for a 2-D canvas.

    Maps pixel coordinates ``(0, 0)`` → ``(-1, -1)`` and
    ``(width, height)`` → ``(+1, +1)`` in clip space, matching the OpenGL
    convention used by Blender's ``gpu.matrix`` module.

    Args:
        width: Canvas width in pixels.
        height: Canvas height in pixels.

    Returns:
        A 4×4 ``mathutils.Matrix`` orthographic projection.
    """
    return mathutils.Matrix([
        [2.0 / width, 0, 0, -1.0],
        [0, 2.0 / height, 0, -1.0],
        [0, 0, -1, 0.0],
        [0, 0, 0, 1.0],
    ])


def _draw_rect(shader, x0, y0, x1, y1, color) -> None:
    """Draw a solid-colour axis-aligned rectangle.

    Submits two triangles forming the rectangle to the GPU via
    ``batch_for_shader``.  The shader must already be bound and the projection
    matrix set before calling this function.

    Args:
        shader: A bound ``gpu.types.GPUShader`` using the ``UNIFORM_COLOR``
            built-in.
        x0: Left edge in pixels.
        y0: Bottom edge in pixels.
        x1: Right edge in pixels.
        y1: Top edge in pixels.
        color: RGBA tuple with components in ``[0.0, 1.0]``.
    """
    verts = [(x0, y0), (x1, y0), (x1, y1), (x0, y0), (x1, y1), (x0, y1)]
    batch = batch_for_shader(shader, "TRIS", {"pos": verts})
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_palette_tile(shader, ox, oy, colors, cs, cols, rows) -> None:
    """Render the colour palette grid into the current framebuffer.

    Draws ``cols × rows`` coloured rectangles of size ``cs × cs`` pixels,
    starting at pixel origin ``(ox, oy)``.  Row 0 of *colors* is rendered at
    the **top** of the tile (highest y) and row ``rows-1`` at the bottom, so
    the visual layout matches the DCP UV convention.

    Args:
        shader: A bound ``UNIFORM_COLOR`` shader.
        ox: X origin of the tile in pixels.
        oy: Y origin of the tile in pixels.
        colors: 2-D list of RGBA tuples indexed ``[row][col]``.
        cs: Cell side length in pixels.
        cols: Number of columns.
        rows: Number of rows.
    """
    for row in range(rows):
        for col in range(cols):
            x = ox + col * cs
            y = oy + (rows - 1 - row) * cs
            _draw_rect(shader, x, y, x + cs, y + cs, colors[row][col])


def _draw_material_tile(shader, ox, oy, roughness, metalness,
                        is_emission, props, cs) -> None:
    """Render the PBR data tile for one quadrant into the current framebuffer.

    For non-emission quadrants each cell is a uniform rectangle coloured
    ``(roughness, metalness, 0.0, 1.0)``.

    For the emission quadrant each cell is subdivided into horizontal strips.
    Strip heights are taken from :func:`~palette.get_emission_layout`.  The
    blue channel of each strip encodes the strip's normalised emission strength
    relative to the maximum strength in the collection (so that ``1.0`` in the
    blue channel always represents the brightest configured strip).

    Args:
        shader: A bound ``UNIFORM_COLOR`` shader.
        ox: X origin of the tile in pixels.
        oy: Y origin of the tile in pixels.
        roughness: Roughness value for this quadrant ``[0.0, 1.0]``.
        metalness: Metalness value for this quadrant ``[0.0, 1.0]``.
        is_emission: ``True`` when rendering the emission quadrant.
        props: ``DCPProperties`` instance; supplies strip values and grid
            dimensions.
        cs: Cell side length in pixels.
    """
    if is_emission:
        el           = get_emission_layout(props)
        max_strength = max((e.value for e in props.emission_strengths), default=1.0)
        for row in range(props.color_rows):
            for col in range(props.color_columns):
                x         = ox + col * cs
                y         = oy + (props.color_rows - 1 - row) * cs
                current_y = y
                for strip, strip_h in zip(props.emission_strengths,
                                          el.strip_heights):
                    b     = strip.value / max_strength if max_strength > 0 else 0.0
                    _draw_rect(shader, x, current_y,
                               x + cs, current_y + strip_h,
                               (roughness, metalness, b, 1.0))
                    current_y += strip_h
    else:
        for row in range(props.color_rows):
            for col in range(props.color_columns):
                x = ox + col * cs
                y = oy + (props.color_rows - 1 - row) * cs
                _draw_rect(shader, x, y, x + cs, y + cs,
                           (roughness, metalness, 0.0, 1.0))


# ============================================================================
# TEXTURE SHEET RENDERER
# ============================================================================

def _build_info_lines(props) -> list[str]:
    """Compose the list of text lines for the info/copyright quadrant.

    Non-empty user info lines (``info_line_1/2/3``) are prepended to a fixed
    footer line containing the addon name and version.  If all user lines are
    blank only the footer is shown.

    Args:
        props: ``DCPProperties`` instance.

    Returns:
        A list of strings to be rendered top-to-bottom in the info quadrant.
    """
    footer = f"Dynamic Color Palette v{VERSION}"
    user_lines = [l for l in [props.info_line_1, props.info_line_2, props.info_line_3] if l.strip()]
    return (user_lines + ["", footer]) if user_lines else [footer]


def _render_to_buffer(
    props,
    draw_fn,
    colors: list,
) -> tuple[int, int, list[float]]:
    """Render one complete texture sheet to an off-screen pixel buffer.

    Sets up a ``GPUOffScreen`` at the required dimensions, fills it with the
    background colour, draws the three quadrant tiles and their labels via
    *draw_fn*, then renders the info-quadrant text.  The raw pixel data is
    read back as a flat list of floats.

    The image width is determined dynamically to accommodate the widest info
    line, ensuring the copyright text is never clipped.

    Args:
        props: ``DCPProperties`` instance; provides colours, text, and layout
            parameters.
        draw_fn: Callable with signature
            ``draw_fn(shader, positions, colors) -> None``.
            *positions* is a list of three ``(px_offset, py_offset)`` tuples
            for the Solid, Metal, and Emission quadrant origins.  The callable
            is responsible for rendering the colour or PBR tiles.
        colors: 2-D list of RGBA tuples (the palette colour grid) forwarded
            unchanged to *draw_fn*.

    Returns:
        ``(image_width, image_height, pixels)`` where *pixels* is a flat
        RGBA float list of length ``image_width * image_height * 4``.
    """
    layout = get_layout(props)

    bg = hex_color(props.bg_hex)
    fg = hex_color(props.fg_hex)

    info_lines = _build_info_lines(props)

    font_id = 0
    blf.size(font_id, DEFAULT_FONT_SIZE)
    _, lh      = blf.dimensions(font_id, "Ag")
    line_h     = lh
    line_gap   = lh * 0.4
    max_info_w = max(blf.dimensions(font_id, l)[0] for l in info_lines)

    q4_width    = int(max(layout.palette_width, max_info_w + layout.margin))
    image_width = int(layout.margin + layout.palette_width + layout.margin
                      + q4_width + layout.margin)

    offscreen = gpu.types.GPUOffScreen(image_width, layout.image_height)
    try:
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=bg)
            gpu.state.blend_set("ALPHA")

            with gpu.matrix.push_pop():
                gpu.matrix.load_projection_matrix(
                    _ortho_matrix(image_width, layout.image_height))
                gpu.matrix.load_identity()

                shader = gpu.shader.from_builtin("UNIFORM_COLOR")
                shader.bind()

                positions = [
                    (layout.margin, layout.panel_height),
                    (layout.margin + layout.palette_width + layout.margin,
                     layout.panel_height),
                    (layout.margin, 0),
                ]
                draw_fn(shader, positions, colors)

                labels = ["SO", "ME", "EM"]
                for idx, (px_off, py_off) in enumerate(positions):
                    label  = labels[idx]
                    lw, lh = blf.dimensions(font_id, label)
                    blf.color(font_id, *fg)
                    blf.position(font_id,
                                 px_off + (layout.palette_width - lw) / 2,
                                 py_off + (layout.text_height - lh) / 2, 0)
                    blf.draw(font_id, label)

                q4_x    = layout.margin + layout.palette_width + layout.margin
                y_start = layout.text_height + (len(info_lines) - 1) * (line_h + line_gap)
                blf.color(font_id, *fg)
                for i, line in enumerate(info_lines):
                    blf.position(font_id, q4_x,
                                 y_start - i * (line_h + line_gap), 0)
                    blf.draw(font_id, line)

            buf = fb.read_color(0, 0, image_width, layout.image_height,
                                4, 0, "FLOAT")
            buf.dimensions = image_width * layout.image_height * 4
            pixels = list(buf)

        return image_width, layout.image_height, pixels
    finally:
        offscreen.free()


def _create_image(name: str, w: int, h: int, pixels: list) -> bpy.types.Image:
    """Create a packed ``bpy.types.Image`` from a raw pixel buffer.

    If an image with the given *name* already exists in ``bpy.data.images``
    it is removed first so the new image starts with a clean state.

    Args:
        name: The datablock name for the new image.
        w: Image width in pixels.
        h: Image height in pixels.
        pixels: Flat RGBA float list of length ``w * h * 4``.

    Returns:
        The newly created and packed ``bpy.types.Image`` datablock.
    """
    old = bpy.data.images.get(name)
    if old:
        bpy.data.images.remove(old)
    img        = bpy.data.images.new(name, width=w, height=h, alpha=True)
    img.pixels = pixels
    img.pack()
    return img


def _save_image(img: bpy.types.Image, save_path, name: str) -> None:
    """Optionally save *img* to disk as a PNG file.

    If *save_path* is falsy (empty string or ``None``) the function is a
    no-op and the image remains Blender-internal only.

    Args:
        img: The image datablock to save.
        save_path: Absolute directory path, or falsy to skip saving.
        name: Base filename without extension (e.g. ``"dcp_albedo"``).
    """
    if not save_path:
        print(f"[{name}] Kept in Blender only.")
        return
    out = os.path.join(save_path, name + ".png")
    img.filepath_raw = out
    img.file_format  = "PNG"
    img.save()
    print(f"[{name}] Saved: {out}")


def _render_sheet(props, name: str, draw_fn, colors: list,
                  save_path) -> bpy.types.Image:
    """Render, pack, and optionally save one full texture sheet.

    Convenience wrapper that chains :func:`_render_to_buffer`,
    :func:`_create_image`, and :func:`_save_image`.

    Args:
        props: ``DCPProperties`` instance.
        name: Datablock name for the resulting image (e.g.
            ``"dcp_albedo"``).
        draw_fn: Draw callback forwarded to :func:`_render_to_buffer`.
        colors: Palette colour grid forwarded to :func:`_render_to_buffer`.
        save_path: Absolute directory path, or falsy to skip saving.

    Returns:
        The packed ``bpy.types.Image`` datablock.
    """
    w, h, pixels = _render_to_buffer(props, draw_fn, colors)
    img = _create_image(name, w, h, pixels)
    _save_image(img, save_path, name)
    return img


# ============================================================================
# PICKER IMAGE
# ============================================================================

def _render_picker_image(props, colors: list) -> bpy.types.Image:
    """Render the enlarged picker image and store it as ``dcp_picker``.

    The picker image contains only the colour palette (no info quadrant, no
    PBR data).  Each cell is drawn at :func:`~palette.get_picker_cell_size`
    pixels with a half-cell border on all sides, making it easy to click
    individual colours in the Image Editor.

    Args:
        props: ``DCPProperties`` instance; provides grid dimensions, colours,
            and background colour.
        colors: 2-D list of RGBA tuples (the palette colour grid).

    Returns:
        The packed ``bpy.types.Image`` datablock for the picker.
    """
    pcs    = get_picker_cell_size(props)
    border = pcs // 2
    cols   = props.color_columns
    rows   = props.color_rows
    width  = cols * pcs + pcs
    height = rows * pcs + pcs

    bg = hex_color(props.bg_hex)

    offscreen = gpu.types.GPUOffScreen(width, height)
    try:
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=bg)
            gpu.state.blend_set("ALPHA")

            with gpu.matrix.push_pop():
                gpu.matrix.load_projection_matrix(_ortho_matrix(width, height))
                gpu.matrix.load_identity()
                shader = gpu.shader.from_builtin("UNIFORM_COLOR")
                shader.bind()
                _draw_palette_tile(shader, border, border, colors,
                                   pcs, cols, rows)

            buf = fb.read_color(0, 0, width, height, 4, 0, "FLOAT")
            buf.dimensions = width * height * 4
            pixels = list(buf)

        img = _create_image(PICKER_IMAGE_NAME, width, height, pixels)
        print(f"[DCP] Picker image created ({width}\xd7{height}px).")
        return img
    finally:
        offscreen.free()


def _build_picker_preview() -> None:
    """Populate the picker PColl with pixel data from ``dcp_picker``.

    Creates (or recreates) the module-level ``_picker_previews`` collection
    and copies ``dcp_picker``'s pixel data into a preview item named
    ``"picker"``.  The PColl is used by the N-Panel to render a thumbnail of
    the picker image; it is not currently exposed in the UI but is maintained
    for forward compatibility.

    If ``dcp_picker`` does not exist in ``bpy.data.images`` the function
    returns silently without modifying the PColl.
    """
    import bpy.utils.previews as _previews
    global _picker_previews

    if _picker_previews is not None:
        _previews.remove(_picker_previews)
    _picker_previews = _previews.new()

    img = bpy.data.images.get(PICKER_IMAGE_NAME)
    if img is None:
        return
    w, h                          = img.size
    preview                       = _picker_previews.new("picker")
    preview.image_size            = [w, h]
    preview.image_pixels_float[:] = list(img.pixels)
    print(f"[DCP] Picker preview built ({w}\xd7{h}px).")


def get_render_font_metrics(font_id: int, info_lines: list):
    """Return font metrics for the given info lines at the configured font size.

    Convenience helper for callers that need to pre-compute text layout
    dimensions before rendering (e.g. to determine image width).

    Args:
        font_id: BLF font identifier (typically ``0`` for the default font).
        info_lines: List of strings whose maximum rendered width is measured.

    Returns:
        ``(line_h, line_gap, max_info_w)`` where *line_h* is the height of
        one text line, *line_gap* is the recommended inter-line spacing
        (``0.4 * line_h``), and *max_info_w* is the pixel width of the
        widest line.  Returns ``max_info_w = 0.0`` if *info_lines* is empty.
    """
    import blf as _blf
    _blf.size(font_id, DEFAULT_FONT_SIZE)
    _, lh    = _blf.dimensions(font_id, "Ag")
    line_h   = lh
    line_gap = lh * 0.4
    max_w    = max(_blf.dimensions(font_id, l)[0] for l in info_lines) if info_lines else 0.0
    return line_h, line_gap, max_w
