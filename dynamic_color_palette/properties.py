# SPDX-License-Identifier: GPL-3.0-or-later
"""Property groups for the Dynamic Color Palette addon.

All user-configurable state and runtime state for one DCP session is stored
here as Blender ``PropertyGroup`` subclasses attached to ``bpy.types.Scene``.
Storing properties on the scene guarantees they are persisted inside the
``.blend`` file and are undo-aware.

Classes
-------
DCPEmissionEntry
    Collection item holding a single normalised emission strip strength.
DCPMatEntry
    Collection item that caches a pointer to a generated singlecol material
    together with the palette coordinates it was created for.
DCPProperties
    Main property group.  Registered as ``bpy.types.Scene.dcp_props``.

Private helpers
---------------
_recompute_preview
    Recalculates ``preview_color`` from the current palette parameters
    without requiring a Blender context.
_update_preview
    Blender ``update`` callback used by palette-configuration properties;
    re-clamps cell coordinates and triggers area redraws.
_get_sel_cell_x / _set_sel_cell_x
    Custom getter/setter for ``sel_cell_x`` that clamp the value to the
    valid column range and refresh the preview on every write.
_get_sel_cell_y / _set_sel_cell_y
    Same as above for the Y axis / row dimension.
"""
from __future__ import annotations

import bpy
from bpy.props import (
    IntProperty, FloatProperty, StringProperty, BoolProperty,
    EnumProperty, PointerProperty, FloatVectorProperty, CollectionProperty,
)
from bpy.types import PropertyGroup

from . import (
    MAX_EMISSION_STRIPS,
    DEFAULT_COLOR_COLUMNS, DEFAULT_COLOR_ROWS,
    DEFAULT_PASTEL_SATURATION, DEFAULT_SHADOW_VALUE,
    DEFAULT_SOLID_ROUGHNESS, DEFAULT_SOLID_METALNESS,
    DEFAULT_METAL_ROUGHNESS, DEFAULT_METAL_METALNESS,
    DEFAULT_EMISSION_ROUGHNESS, DEFAULT_EMISSION_METALNESS,
    DEFAULT_EMISSION_FACTOR,
    DEFAULT_TEXTURES_EXPORT_DIR, DEFAULT_JSON_EXPORT_DIR,
    DEFAULT_GDSHADER_EXPORT_DIR, DEFAULT_GDUTILCLASS_EXPORT_DIR,
    DEFAULT_INFO_LINE_1, DEFAULT_INFO_LINE_2, DEFAULT_INFO_LINE_3,
    DEFAULT_BG_HEX, DEFAULT_FG_HEX,
)


class DCPEmissionEntry(PropertyGroup):
    """One normalised emission strip value stored in a CollectionProperty.

    A palette's emission quadrant is subdivided vertically into one strip per
    entry in this collection.  Each strip encodes a different emission
    strength level, allowing artists to pick "dim / medium / bright" emission
    from the same palette cell.

    Properties:
        value (float): Normalised emission strength in the range [0.0, 1.0].
            The actual render-time emission strength is ``value *
            emission_factor`` (see :attr:`DCPProperties.emission_factor`).
    """

    value: FloatProperty(
        name="Strip Value",
        description="Normalised emission strength for this strip (0.0 \u2013 1.0)",
        default=1.0, min=0.0, max=1.0,
    )


class DCPMatEntry(PropertyGroup):
    """Pointer-based cache entry for a generated singlecol material.

    The cache maps a (quadrant, cell_x, cell_y, emission) tuple to a
    ``bpy.types.Material`` pointer.  Using a ``PointerProperty`` instead of
    a name string ensures the reference survives material renames.

    Properties:
        quadrant (int): Palette quadrant index (0 = Solid, 1 = Metal,
            2 = Emission).
        cell_x (int): Column index of the palette cell.
        cell_y (int): Row index of the palette cell.
        emission (int): Emission strip index (only meaningful when
            ``quadrant == 2``).
        mat (bpy.types.Material): Pointer to the cached material datablock.
            May be ``None`` if the material was deleted outside DCP.
    """

    quadrant : IntProperty()
    cell_x   : IntProperty()
    cell_y   : IntProperty()
    emission : IntProperty()
    mat      : PointerProperty(type=bpy.types.Material)


_preview_guard = False
"""Re-entrancy guard for :func:`_recompute_preview`.

Prevents infinite recursion when the preview update triggers further property
changes that would call the same function again.
"""


def _recompute_preview(props) -> None:
    """Recalculate ``preview_color`` from the current palette parameters.

    Reads the palette configuration stored in *props*, derives the RGBA colour
    at the currently selected cell (``sel_cell_x``, ``sel_cell_y``) and writes
    it to ``props.preview_color``.  The function does **not** require a Blender
    context, so it can safely be called from property getters/setters.

    A module-level boolean guard prevents re-entrant calls that could arise
    when writing ``preview_color`` itself triggers another update.

    Args:
        props: The ``DCPProperties`` instance attached to the active scene
            (``context.scene.dcp_props``).
    """
    global _preview_guard
    if _preview_guard:
        return
    _preview_guard = True
    try:
        from .core.palette import _compute_palette_params, _palette_cell_colors
        cols = max(1, props.color_columns)
        rows = max(2, props.color_rows)
        cx = max(0, min(props.sel_cell_x, cols - 1))
        cy = max(0, min(props.sel_cell_y, rows - 1))
        hues, sat_val = _compute_palette_params(cols, rows,
                                                props.pastel_saturation,
                                                props.shadow_value)
        colors = _palette_cell_colors(hues, sat_val, cols, rows)
        r, g, b, a = colors[cy][cx]
        props.preview_color = (r, g, b, a)
    except Exception as exc:
        print(f"[DCP] _recompute_preview: {exc}")
    finally:
        _preview_guard = False


def _update_preview(self, context) -> None:
    """Blender property ``update`` callback for palette-configuration properties.

    Invoked by Blender whenever a property that carries ``update=_update_preview``
    changes (e.g. ``color_columns``, ``pastel_saturation``, ``sel_quadrant``).

    Re-clamps the current cell coordinates by routing through their custom
    setters (which in turn call :func:`_recompute_preview`), then schedules
    redraws for all relevant areas.

    Args:
        self: The ``DCPProperties`` instance that owns the changed property.
        context: The Blender context provided by the property system.
    """
    # Re-clamp cell coords via setter (setter handles clamping + preview).
    _set_sel_cell_x(self, self.get("_cx", 0))
    _set_sel_cell_y(self, self.get("_cy", 0))
    if context and context.area:
        context.area.tag_redraw()
    if context and hasattr(context, "window") and context.window:
        for area in context.window.screen.areas:
            if area.type in {"VIEW_3D", "PROPERTIES", "IMAGE_EDITOR"}:
                area.tag_redraw()


# --- get/set for sel_cell_x, sel_cell_y, and sel_emission ---
# Using get/set instead of update so that the stored value is clamped
# immediately on every set call. This prevents the slider from "jumping back"
# — instead the drag simply stalls at the maximum valid value.

def _get_sel_cell_x(self) -> int:
    """Return the stored column index, defaulting to 0 if not yet written.

    Args:
        self: The ``DCPProperties`` instance.

    Returns:
        The current column index clamped to ``[0, color_columns - 1]``.
    """
    return self.get("_cx", 0)

def _set_sel_cell_x(self, value: int) -> None:
    """Clamp *value* to the valid column range and refresh the colour preview.

    The clamped result is stored in the internal key ``"_cx"`` rather than
    through the property itself to avoid re-entrant setter calls.

    Args:
        self: The ``DCPProperties`` instance.
        value: Desired column index (may be out of range).
    """
    cols = max(1, self.color_columns)
    self["_cx"] = max(0, min(value, cols - 1))
    _recompute_preview(self)

def _get_sel_cell_y(self) -> int:
    """Return the stored row index, defaulting to 0 if not yet written.

    Args:
        self: The ``DCPProperties`` instance.

    Returns:
        The current row index clamped to ``[0, color_rows - 1]``.
    """
    return self.get("_cy", 0)

def _set_sel_cell_y(self, value: int) -> None:
    """Clamp *value* to the valid row range and refresh the colour preview.

    The clamped result is stored in the internal key ``"_cy"`` rather than
    through the property itself to avoid re-entrant setter calls.

    Args:
        self: The ``DCPProperties`` instance.
        value: Desired row index (may be out of range).
    """
    rows = max(2, self.color_rows)
    self["_cy"] = max(0, min(value, rows - 1))
    _recompute_preview(self)


def _get_sel_emission(self) -> int:
    n = max(1, len(self.emission_strengths))
    return max(0, min(self.get("_em", 0), n - 1))

def _set_sel_emission(self, value: int) -> None:
    n = max(1, len(self.emission_strengths))
    self["_em"] = max(0, min(value, n - 1))
    _recompute_preview(self)


class DCPProperties(PropertyGroup):
    """Scene-level property group — all configuration and runtime state for DCP.

    Registered as ``bpy.types.Scene.dcp_props``.  Because it lives on the
    scene, all values are saved in the ``.blend`` file and participate in
    Blender's undo/redo system.

    The properties are grouped into the following logical sections:

    **Palette configuration** (``color_columns``, ``color_rows``,
    ``pastel_saturation``, ``shadow_value``)
        Control the hue / saturation / value distribution of the generated
        colour grid.

    **PBR values** (``solid_*``, ``metal_*``, ``emission_*``)
        Roughness and metalness written into the ``dcp_material`` texture for
        each quadrant, as well as the global emission strength multiplier.

    **Emission strips** (``emission_strengths``)
        Collection of up to :data:`~__init__.MAX_EMISSION_STRIPS` strip
        entries.  Each strip subdivides the emission cell vertically and
        carries a normalised strength value.

    **Export** (``textures_export_dir``, ``json_export_dir``, ``gdshader_export_dir``, ``gdutilclass_export_dir``)
        Optional filesystem directory; when set, generated textures are saved
        as PNG files there.

    **Info quadrant** (``info_line_1/2/3``, ``bg_hex``, ``fg_hex``)
        Text and colour configuration for the copyright/info area rendered in
        the bottom-right quadrant of the palette texture.

    **Workflow state** (``palette_generated``, ``pick_from_image_editor``,
    ``multicol_mat``, ``singlecol_mats``)
        Runtime flags and material-cache pointers that drive the N-Panel UI
        and operator logic.

    **Colour selection** (``sel_quadrant``, ``sel_cell_x``, ``sel_cell_y``,
    ``sel_emission``, ``preview_color``)
        The currently active palette coordinate.  ``sel_cell_x/y`` use custom
        getters/setters to clamp values to the current grid dimensions and to
        keep ``preview_color`` in sync without requiring a context.

    **Snapshot** (``snap_*``)
        Read-only copies of the last-generated configuration.  Compared
        against current values by :func:`~operators.generate._needs_confirmation`
        to decide whether a safety dialog is needed before regeneration.
    """

    # ---- Palette configuration -------------------------------------------
    color_columns     : IntProperty(name="Hue Columns",
                                    default=DEFAULT_COLOR_COLUMNS, min=1, max=32,
                                    update=_update_preview)
    color_rows        : IntProperty(name="Rows",
                                    default=DEFAULT_COLOR_ROWS, min=2, max=32,
                                    update=_update_preview)
    pastel_saturation : FloatProperty(name="Pastel Saturation",
                                      default=DEFAULT_PASTEL_SATURATION,
                                      min=0.0, max=1.0,
                                      update=_update_preview)
    shadow_value      : FloatProperty(name="Shadow Value",
                                      default=DEFAULT_SHADOW_VALUE,
                                      min=0.0, max=1.0,
                                      update=_update_preview)

    # ---- PBR values -------------------------------------------------------
    solid_roughness    : FloatProperty(name="Solid Roughness",
                                       default=DEFAULT_SOLID_ROUGHNESS,
                                       min=0.0, max=1.0)
    solid_metalness    : FloatProperty(name="Solid Metalness",
                                       default=DEFAULT_SOLID_METALNESS,
                                       min=0.0, max=1.0)
    metal_roughness    : FloatProperty(name="Metal Roughness",
                                       default=DEFAULT_METAL_ROUGHNESS,
                                       min=0.0, max=1.0)
    metal_metalness    : FloatProperty(name="Metal Metalness",
                                       default=DEFAULT_METAL_METALNESS,
                                       min=0.0, max=1.0)
    emission_roughness : FloatProperty(name="Emission Roughness",
                                       default=DEFAULT_EMISSION_ROUGHNESS,
                                       min=0.0, max=1.0)
    emission_metalness : FloatProperty(name="Emission Metalness",
                                       default=DEFAULT_EMISSION_METALNESS,
                                       min=0.0, max=1.0)
    emission_factor    : FloatProperty(name="Strength Factor",
                                       description="Multiplied with strip value in shader",
                                       default=DEFAULT_EMISSION_FACTOR, min=0.01)

    # ---- Emission strips --------------------------------------------------
    emission_strengths : CollectionProperty(type=DCPEmissionEntry)

    # ---- Export -----------------------------------------------------------
    textures_export_dir    : StringProperty(name="Textures",
                                            default=DEFAULT_TEXTURES_EXPORT_DIR,
                                            subtype="DIR_PATH")
    json_export_dir        : StringProperty(name="JSON Config",
                                            default=DEFAULT_JSON_EXPORT_DIR,
                                            subtype="DIR_PATH")
    gdshader_export_dir    : StringProperty(name="GDShader",
                                            default=DEFAULT_GDSHADER_EXPORT_DIR,
                                            subtype="DIR_PATH")
    gdutilclass_export_dir : StringProperty(name="GDScript Util",
                                            default=DEFAULT_GDUTILCLASS_EXPORT_DIR,
                                            subtype="DIR_PATH")

    # ---- Info Quadrant ----------------------------------------------------
    info_line_1 : StringProperty(name="Project",  default=DEFAULT_INFO_LINE_1)
    info_line_2 : StringProperty(name="Studio",   default=DEFAULT_INFO_LINE_2)
    info_line_3 : StringProperty(name="License",  default=DEFAULT_INFO_LINE_3)
    bg_hex      : StringProperty(name="Background", default=DEFAULT_BG_HEX)
    fg_hex      : StringProperty(name="Foreground",  default=DEFAULT_FG_HEX)

    # ---- State ------------------------------------------------------------
    palette_generated      : BoolProperty(default=False)
    pick_from_image_editor : BoolProperty(default=False)

    # ---- Current colour selection ----------------------------------------
    sel_quadrant : EnumProperty(
        name="Quadrant",
        items=[
            ("0", "Solid",    "Matte non-metal surface"),
            ("1", "Metal",    "Fully metallic surface"),
            ("2", "Emission", "Glowing surface"),
        ],
        default="0",
        update=_update_preview,
    )
    sel_cell_x : IntProperty(name="Cell X", min=0, max=31,
                             get=_get_sel_cell_x, set=_set_sel_cell_x)
    sel_cell_y : IntProperty(name="Cell Y", min=0, max=31,
                             get=_get_sel_cell_y, set=_set_sel_cell_y)
    sel_emission : IntProperty(name="Emission Strip",
                               min=0, max=MAX_EMISSION_STRIPS - 1,
                               get=_get_sel_emission, set=_set_sel_emission)
    preview_color : FloatVectorProperty(
        name="Preview Color", subtype="COLOR", size=4,
        min=0.0, max=1.0, default=(0.3, 0.3, 0.3, 1.0),
    )

    # ---- Material cache ---------------------------------------------------
    multicol_mat   : PointerProperty(type=bpy.types.Material)
    singlecol_mats : CollectionProperty(type=DCPMatEntry)

    # ---- Snapshot (not user-editable; used for regeneration comparison) ---
    snap_color_columns      : IntProperty()
    snap_color_rows         : IntProperty()
    snap_pastel_saturation  : FloatProperty()
    snap_shadow_value       : FloatProperty()
    snap_solid_roughness    : FloatProperty()
    snap_solid_metalness    : FloatProperty()
    snap_metal_roughness    : FloatProperty()
    snap_metal_metalness    : FloatProperty()
    snap_emission_roughness : FloatProperty()
    snap_emission_metalness : FloatProperty()
    snap_emission_strips    : StringProperty()   # CSV of strip values
