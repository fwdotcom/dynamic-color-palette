# SPDX-License-Identifier: GPL-3.0-or-later
"""Palette colour computation, layout geometry, and UV helpers.

This module is the mathematical core of DCP.  It contains no Blender operator
or UI code; all functions operate on plain Python data structures or on
``DCPProperties`` instances.

Sections
--------
Data structures
    :class:`LayoutConfig` and :class:`EmissionLayout` are frozen dataclasses
    that describe the pixel geometry of the generated texture sheet.

Module-level cache
    ``_emission_layout_cache`` memoises :func:`get_emission_layout` results
    keyed on ``(cell_size, n_strips)`` so repeated calls during a single
    generation pass pay no recomputation cost.

Colour helpers
    :func:`hex_color`, :func:`rgb_to_hex` — conversions between hex strings
    and linear-float RGBA tuples.

Layout helpers
    :func:`get_cell_size`, :func:`get_picker_cell_size`, :func:`get_layout`,
    :func:`get_emission_layout` — derive pixel dimensions from ``DCPProperties``.

Palette computation
    :func:`_compute_palette_params`, :func:`_palette_cell_colors`,
    :func:`get_palette_colors`, :func:`cell_color_from_props`,
    :func:`pbr_from_quadrant` — generate the full colour / PBR table.

UV helpers
    :func:`cell_to_albedo_uv`, :func:`get_uv_islands_by_connectivity`,
    :func:`place_islands_at_uv` — map palette coordinates to UV space.
"""
from __future__ import annotations

import math
import colorsys
from dataclasses import dataclass
from typing import Optional, Sequence

import bpy

from .. import PREFIX, DEFAULT_CELL_SIZE_MIN


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass(frozen=True)
class LayoutConfig:
    """Immutable pixel-geometry descriptor for one generated texture sheet.

    All values are pre-computed by :func:`get_layout` from ``DCPProperties``
    and passed through the rendering pipeline so individual draw functions do
    not need to re-derive them.

    Attributes:
        cell_size (int): Side length of a single palette cell in pixels.
        color_columns (int): Number of hue columns in the palette grid.
        color_rows (int): Number of value/saturation rows in the palette grid.
        palette_width (int): ``color_columns * cell_size`` pixels.
        palette_height (int): ``color_rows * cell_size`` pixels.
        text_height (int): Height of the label strip below each quadrant
            (``2 * cell_size`` pixels).
        panel_height (int): ``palette_height + text_height`` pixels — the
            height of one complete quadrant panel (palette + label).
        image_height (int): Total image height covering all three quadrant
            panels (``cell_size + 2 * panel_height``).
        margin (int): Horizontal gap between quadrant panels (``cell_size``
            pixels).
    """

    cell_size     : int
    color_columns : int
    color_rows    : int
    palette_width : int
    palette_height: int
    text_height   : int
    panel_height  : int
    image_height  : int
    margin        : int


@dataclass(frozen=True)
class EmissionLayout:
    """Immutable strip-height descriptor for the emission quadrant.

    The emission quadrant subdivides each palette cell vertically into one
    horizontal strip per emission strength entry.  Because ``cell_size`` may
    not be evenly divisible by the number of strips, the surplus pixels are
    distributed to the first strips (floor + 1 for the first ``rem`` strips).

    Attributes:
        n_strength (int): Number of emission strips (``len(emission_strengths)``).
        strip_heights (tuple[int, ...]): Pixel height of each strip from bottom
            to top, such that ``sum(strip_heights) == cell_size``.
    """

    n_strength   : int
    strip_heights: tuple[int, ...]


# ============================================================================
# MODULE-LEVEL CACHE
# ============================================================================

_emission_layout_cache: dict[tuple, EmissionLayout] = {}
"""Memoisation cache for :func:`get_emission_layout`.

Key: ``(cell_size, n_strips)`` — both integers.
Value: The corresponding :class:`EmissionLayout` instance.
Invalidated by :func:`_invalidate_emission_cache` whenever the strip
configuration changes (add/remove strip or palette regeneration).
"""


def _invalidate_emission_cache() -> None:
    """Clear the emission layout memoisation cache.

    Must be called whenever the number of emission strips or the cell size
    changes so that stale geometry is not used during the next render pass.
    """
    _emission_layout_cache.clear()


# ============================================================================
# COLOUR HELPERS
# ============================================================================

def hex_color(hex_string: str, alpha: float = 1.0) -> tuple:
    """Convert a 6-digit hex colour string to a linear-float RGBA tuple.

    Args:
        hex_string: CSS-style hex colour, optionally prefixed with ``"#"``
            (e.g. ``"#1A2B3C"`` or ``"1A2B3C"``).  Must be exactly 6 hex
            digits.
        alpha: Alpha channel value in ``[0.0, 1.0]``.  Defaults to ``1.0``
            (fully opaque).

    Returns:
        ``(r, g, b, alpha)`` with each component in ``[0.0, 1.0]``.
        On any parse error the function returns opaque black
        ``(0.0, 0.0, 0.0, alpha)`` and logs a warning to the console.
    """
    try:
        h = hex_string.lstrip("#")
        if len(h) != 6:
            raise ValueError(f"Expected 6 hex digits, got '{h}'")
        r, g, b = (int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))
        return (r, g, b, alpha)
    except Exception as exc:
        print(f"[DCP] hex_color: {exc} \u2013 using black.")
        return (0.0, 0.0, 0.0, alpha)


def rgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert linear-float RGB components to an uppercase hex string.

    Args:
        r: Red channel in ``[0.0, 1.0]``.
        g: Green channel in ``[0.0, 1.0]``.
        b: Blue channel in ``[0.0, 1.0]``.

    Returns:
        Hex string with leading ``"#"``, e.g. ``"#FF8040"``.
        Components are clamped implicitly by ``int(x * 255)``.
    """
    return "#{:02X}{:02X}{:02X}".format(int(r * 255), int(g * 255), int(b * 255))


# ============================================================================
# LAYOUT HELPERS
# ============================================================================

def get_cell_size(props) -> int:
    """Calculate the pixel side length for one palette cell.

    The cell must be tall enough to accommodate all emission strips at a
    minimum of 5 pixels each, and never smaller than
    :data:`~__init__.DEFAULT_CELL_SIZE_MIN`.

    Args:
        props: ``DCPProperties`` instance from the active scene.

    Returns:
        Cell size in pixels: ``max(DEFAULT_CELL_SIZE_MIN, n_strips * 5)``.
    """
    n = max(1, len(props.emission_strengths))
    return max(DEFAULT_CELL_SIZE_MIN, n * 5)


def get_picker_cell_size(props) -> int:
    """Calculate the enlarged cell size used in the picker image.

    The picker image uses 1.5× the standard cell size so that individual
    cells are easy to click even at typical monitor resolutions.

    Args:
        props: ``DCPProperties`` instance from the active scene.

    Returns:
        Picker cell size in pixels: ``ceil(cell_size * 1.5)``.
    """
    return math.ceil(get_cell_size(props) * 1.5)


def get_layout(props) -> LayoutConfig:
    """Derive the complete pixel-geometry descriptor from ``DCPProperties``.

    This is the single authoritative source of layout numbers for the texture
    sheet renderer.  All other functions that need pixel positions should call
    this function rather than recomputing values independently.

    Args:
        props: ``DCPProperties`` instance from the active scene.

    Returns:
        A fully populated :class:`LayoutConfig` instance.
    """
    cs             = get_cell_size(props)
    cols           = props.color_columns
    rows           = props.color_rows
    palette_width  = cols * cs
    palette_height = rows * cs
    text_height    = cs * 2
    panel_height   = palette_height + text_height
    image_height   = cs + panel_height + panel_height
    return LayoutConfig(
        cell_size=cs, color_columns=cols, color_rows=rows,
        palette_width=palette_width, palette_height=palette_height,
        text_height=text_height, panel_height=panel_height,
        image_height=image_height, margin=cs,
    )


def get_emission_layout(props) -> EmissionLayout:
    """Derive strip heights for the emission quadrant, with memoisation.

    Divides ``cell_size`` pixels evenly among the configured emission strips.
    If the division is not exact the surplus pixels are distributed one per
    strip starting from the first strip (bottom-most).  The result is cached
    keyed on ``(cell_size, n_strips)`` so subsequent calls within the same
    generation pass are free.

    Args:
        props: ``DCPProperties`` instance from the active scene.

    Returns:
        :class:`EmissionLayout` with ``n_strength`` strips and their
        individual pixel heights.
    """
    n   = max(1, len(props.emission_strengths))
    cs  = get_cell_size(props)
    key = (cs, n)

    cached = _emission_layout_cache.get(key)
    if cached is not None:
        return cached

    base = cs // n
    rem  = cs % n
    if rem:
        print(f"[DCP] CELL_SIZE ({cs}) not evenly divisible by {n} strips; "
              f"distributing {rem}px.")
    heights = tuple(base + (1 if i < rem else 0) for i in range(n))
    result  = EmissionLayout(n_strength=n, strip_heights=heights)
    _emission_layout_cache[key] = result
    return result


# ============================================================================
# PALETTE COMPUTATION
# ============================================================================

def _compute_palette_params(
    cols: int, rows: int,
    pastel_sat: float, shadow_val: float,
) -> tuple[list[float], list[tuple[float, float]]]:
    """Compute per-column hue angles and per-row (saturation, value) pairs.

    The palette is laid out as follows (bottom row → top row in UV space):

    * Rows 0 … n-2: saturation sweeps from ``pastel_sat`` to ``1.0`` while
      value stays at ``1.0`` (the "pastel → vivid" ramp).
    * Rows n-2 … n-1: saturation stays at ``1.0`` while value sweeps from
      ``1.0`` down to ``shadow_val`` (the "vivid → shadow" ramp).
    * The last row (index ``rows - 1``) is a greyscale strip derived from
      ``_palette_cell_colors``.

    Args:
        cols: Number of hue columns.
        rows: Number of palette rows (must be ≥ 2).
        pastel_sat: Starting saturation for the top row (``[0.0, 1.0]``).
        shadow_val: Minimum value (brightness) for the bottom row
            (``[0.0, 1.0]``).

    Returns:
        A 2-tuple ``(hues, sat_val)`` where:

        * ``hues`` is a list of *cols* hue angles in degrees ``[0, 360)``.
        * ``sat_val`` is a list of *rows-1* ``(saturation, value)`` pairs
          in ``[0.0, 1.0]``.
    """
    hues    = [c / cols * 360.0 for c in range(cols)]
    n       = rows - 1
    sat_val = []
    for i in range(n):
        t = i / max(n - 1, 1)
        if t <= 0.5:
            tt = t / 0.5
            s  = pastel_sat + tt * (1.0 - pastel_sat)
            v  = 1.0
        else:
            tt = (t - 0.5) / 0.5
            s  = 1.0
            v  = 1.0 - tt * (1.0 - shadow_val)
        sat_val.append((s, v))
    return hues, sat_val


def _palette_cell_colors(
    hues: Sequence[float],
    sat_val: Sequence[tuple[float, float]],
    cols: int,
    rows: int,
) -> list[list[tuple]]:
    """Build a 2-D grid of RGBA colour tuples from hue/saturation/value tables.

    Args:
        hues: Sequence of *cols* hue angles in degrees.
        sat_val: Sequence of *rows-1* ``(saturation, value)`` pairs.
        cols: Number of palette columns.
        rows: Number of palette rows.

    Returns:
        A ``rows × cols`` nested list of ``(r, g, b, 1.0)`` tuples in
        linear-float space.  The last row (index ``rows - 1``) is a greyscale
        gradient from white (column 0) to black (column ``cols - 1``) and is
        generated when ``len(sat_val) < rows``.
    """
    result = []
    for row in range(rows):
        if row < len(sat_val):
            s, v = sat_val[row]
            result.append([
                colorsys.hsv_to_rgb(hues[c] / 360.0, s, v) + (1.0,)
                for c in range(cols)
            ])
        else:
            result.append([
                ((1.0 - c / max(cols - 1, 1),) * 3 + (1.0,))
                for c in range(cols)
            ])
    return result


def get_palette_colors(props) -> list[list[tuple]]:
    """Generate the full palette colour grid from ``DCPProperties``.

    Convenience wrapper around :func:`_compute_palette_params` and
    :func:`_palette_cell_colors` that reads all required parameters from
    *props*.

    Args:
        props: ``DCPProperties`` instance from the active scene.

    Returns:
        A ``color_rows × color_columns`` nested list of ``(r, g, b, 1.0)``
        tuples in linear-float space.
    """
    hues, sat_val = _compute_palette_params(
        props.color_columns, props.color_rows,
        props.pastel_saturation, props.shadow_value,
    )
    return _palette_cell_colors(hues, sat_val,
                                props.color_columns, props.color_rows)


def cell_color_from_props(props, cell_x: int, cell_y: int) -> tuple:
    """Return the RGBA colour for a specific palette cell.

    Coordinates are clamped to the valid grid range before lookup so no
    ``IndexError`` can occur even with out-of-range inputs.

    Args:
        props: ``DCPProperties`` instance from the active scene.
        cell_x: Column index (clamped to ``[0, color_columns - 1]``).
        cell_y: Row index (clamped to ``[0, color_rows - 1]``).

    Returns:
        ``(r, g, b, 1.0)`` in linear-float space.
    """
    colors = get_palette_colors(props)
    row    = max(0, min(cell_y, len(colors) - 1))
    col    = max(0, min(cell_x, len(colors[0]) - 1))
    return colors[row][col]


def pbr_from_quadrant(props, quadrant: int, emission_idx: int):
    """Return the PBR triple ``(roughness, metalness, emission)`` for a cell.

    For solid and metal quadrants the emission component is always ``0.0``.
    For the emission quadrant it is the normalised strip value at *emission_idx*
    (which the shader multiplies by ``emission_factor`` at render time).

    Args:
        props: ``DCPProperties`` instance from the active scene.
        quadrant: ``0`` = Solid, ``1`` = Metal, ``2`` = Emission.
        emission_idx: Strip index within the emission collection.  Clamped
            to ``[0, n_strips - 1]``.  Ignored when ``quadrant != 2``.

    Returns:
        ``(roughness, metalness, norm_emission)`` — all floats in
        ``[0.0, 1.0]`` except roughness/metalness which follow the
        property bounds.
    """
    if quadrant == 0:
        return props.solid_roughness, props.solid_metalness, 0.0
    if quadrant == 1:
        return props.metal_roughness, props.metal_metalness, 0.0
    # Emission
    strips  = list(props.emission_strengths)
    n       = len(strips)
    idx     = max(0, min(emission_idx, n - 1))
    norm_em = strips[idx].value if strips else 1.0
    return props.emission_roughness, props.emission_metalness, norm_em


def cell_to_albedo_uv(
    props,
    quadrant: int, cell_x: int, cell_y: int, emission_idx: int,
) -> Optional[tuple[float, float]]:
    """Convert a palette cell address to normalised UV coordinates.

    The UV point is placed at the pixel-centre of the requested cell (or strip
    within that cell for emission quadrant), then divided by the image
    dimensions to obtain values in ``[0.0, 1.0]``.

    Requires ``dcp_albedo`` to already exist in ``bpy.data.images`` so that
    its pixel dimensions are known.

    Args:
        props: ``DCPProperties`` instance from the active scene.
        quadrant: ``0`` = Solid, ``1`` = Metal, ``2`` = Emission.
        cell_x: Column index within the quadrant's palette grid.
        cell_y: Row index within the quadrant's palette grid.
        emission_idx: Strip index (only used when ``quadrant == 2``).

    Returns:
        ``(u, v)`` normalised UV coordinates, or ``None`` if ``dcp_albedo``
        is not found or has zero dimensions.
    """
    img = bpy.data.images.get(PREFIX + "albedo")
    if img is None:
        return None
    img_w, img_h = img.size
    if img_w <= 0 or img_h <= 0:
        return None

    layout = get_layout(props)
    cs     = layout.cell_size

    quad_origins = [
        (layout.margin, layout.panel_height + layout.text_height),   # Solid
        (layout.margin + layout.palette_width + layout.margin,
         layout.panel_height + layout.text_height),                   # Metal
        (layout.margin, layout.text_height),                          # Emission
    ]
    ox, oy = quad_origins[max(0, min(quadrant, 2))]

    px            = ox + cell_x * cs + cs * 0.5
    cell_bottom_y = oy + (props.color_rows - 1 - cell_y) * cs

    if quadrant == 2:
        el           = get_emission_layout(props)
        emission_idx = max(0, min(emission_idx, len(el.strip_heights) - 1))
        strip_bottom = sum(el.strip_heights[:emission_idx])
        py           = cell_bottom_y + strip_bottom + el.strip_heights[emission_idx] * 0.5
    else:
        py = cell_bottom_y + cs * 0.5

    return (px / img_w, py / img_h)


# ============================================================================
# UV HELPERS
# ============================================================================

def get_uv_islands_by_connectivity(bm, selected_faces: list) -> list:
    """Group selected BMesh faces into UV islands by mesh edge connectivity.

    Two faces belong to the same island if they share at least one edge.
    The grouping is purely topological — UV seams and UV coordinates are not
    considered.  This is intentional: all faces in an island are placed at the
    same UV target point, so UV seams are irrelevant for the lookup-texture
    workflow.

    Args:
        bm: The ``bmesh.types.BMesh`` that owns the faces.  Must be in a
            valid state (edit-mesh or freshly created from a mesh).
        selected_faces: List of ``bmesh.types.BMFace`` objects to group.

    Returns:
        A list of face-lists.  Each inner list is one connected island.
        The order of islands and faces within islands is not guaranteed.
    """
    selected_set = {f.index for f in selected_faces}
    visited      = set()
    islands      = []

    def flood_fill(start):
        island = []
        stack  = [start]
        while stack:
            face = stack.pop()
            if face.index in visited:
                continue
            visited.add(face.index)
            island.append(face)
            for edge in face.edges:
                for linked in edge.link_faces:
                    if linked.index not in visited and linked.index in selected_set:
                        stack.append(linked)
        return island

    for face in selected_faces:
        if face.index not in visited:
            island = flood_fill(face)
            if island:
                islands.append(island)
    return islands


def place_islands_at_uv(bm, uv_layer, islands: list, target_uv: tuple) -> None:
    """Set every loop UV in each island to *target_uv*.

    All loops of all faces in every island are assigned the same UV point.
    This collapses the island to a single point in UV space, which is exactly
    what the multicol lookup-texture workflow requires: one UV coordinate →
    one colour sample.

    Args:
        bm: The ``bmesh.types.BMesh`` that owns the faces (unused directly,
            kept for API symmetry).
        uv_layer: The active ``bmesh.types.BMLayerItem`` for UV coordinates.
        islands: List of face-lists as returned by
            :func:`get_uv_islands_by_connectivity`.
        target_uv: ``(u, v)`` tuple — the palette point to assign.
    """
    from mathutils import Vector
    target = Vector(target_uv)
    for island in islands:
        for face in island:
            for loop in face.loops:
                loop[uv_layer].uv = target.copy()
