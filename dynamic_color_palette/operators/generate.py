# SPDX-License-Identifier: GPL-3.0-or-later
"""Palette generation and related operators.

This module contains three operators and two groups of private helpers:

Operators
---------
DCP_OT_GeneratePalette
    Entry point for both first-time generation and regeneration.  On
    regeneration with relevant changes it delegates to
    ``DCP_OT_ConfirmRegenerate`` for a safety dialog; otherwise it runs the
    generation directly.
DCP_OT_ResetDefaults
    Resets all ``DCPProperties`` configuration fields to the built-in
    ``DEFAULT_*`` constants defined in :mod:`__init__`.
DCP_OT_ConfirmRegenerate
    Modal confirmation dialog (``invoke_props_dialog``) shown before
    regenerating when existing UV assignments or singlecol materials would
    be affected.

Private helpers
---------------
Snapshot helpers (``_write_snapshot``, ``_needs_confirmation``)
    Compare current properties against the last-generation snapshot to
    determine whether a warning is needed.
Core generation logic (``_run_generate``)
    The actual texture/material build pipeline, shared by both
    ``DCP_OT_GeneratePalette`` and ``DCP_OT_ConfirmRegenerate`` so neither
    operator needs to instantiate the other.
"""
from __future__ import annotations

import json
import os

import bpy
from bpy.types import Operator

from .. import (
    PREFIX, VERSION,
    ALBEDO_IMAGE_NAME, MATERIAL_IMAGE_NAME,
    DEFAULT_COLOR_COLUMNS, DEFAULT_COLOR_ROWS,
    DEFAULT_PASTEL_SATURATION, DEFAULT_SHADOW_VALUE,
    DEFAULT_SOLID_ROUGHNESS, DEFAULT_SOLID_METALNESS,
    DEFAULT_METAL_ROUGHNESS, DEFAULT_METAL_METALNESS,
    DEFAULT_EMISSION_ROUGHNESS, DEFAULT_EMISSION_METALNESS,
    DEFAULT_EMISSION_FACTOR, DEFAULT_EMISSION_STRIPS,
    DEFAULT_FILE_SAVE_PATH,
    DEFAULT_INFO_LINE_1, DEFAULT_INFO_LINE_2, DEFAULT_INFO_LINE_3,
    DEFAULT_BG_HEX, DEFAULT_FG_HEX,
)
from ..core.palette import (
    get_palette_colors, get_layout,
    _invalidate_emission_cache,
)
from ..properties import _recompute_preview
from ..core.textures import (
    _render_sheet, _render_picker_image, _build_picker_preview,
    _draw_palette_tile, _draw_material_tile,
)
from ..core.materials import build_or_update_multicol_material
from ..core.image_editor import show_picker_in_image_editor, force_stop_pick_mode


# Pending generation params – set by DCP_OT_GeneratePalette.execute() when
# confirmation is required, consumed by DCP_OT_ConfirmRegenerate.execute().
_pending_generation: dict = {}
"""Module-level staging dict for the confirmation dialog.

``DCP_OT_GeneratePalette.execute()`` populates this dict with warning flags
when it detects relevant changes during a regeneration attempt.
``DCP_OT_ConfirmRegenerate.execute()`` reads and clears it after the user
confirms.  The dict is keyed with underscore-prefixed sentinel keys
(``"_has_uv_shift"``, ``"_n_sc"``) to distinguish them from property names.
"""


# ============================================================================
# SNAPSHOT HELPERS
# ============================================================================

def _write_snapshot(props) -> None:
    """Copy current palette configuration into the snapshot properties.

    The snapshot is a set of ``snap_*`` fields on ``DCPProperties`` that
    mirror the configuration at the time of the last successful generation.
    On the next regeneration attempt :func:`_needs_confirmation` compares the
    current values against this snapshot.

    Args:
        props: ``DCPProperties`` instance from the active scene.
    """
    props.snap_color_columns      = props.color_columns
    props.snap_color_rows         = props.color_rows
    props.snap_pastel_saturation  = props.pastel_saturation
    props.snap_shadow_value       = props.shadow_value
    props.snap_solid_roughness    = props.solid_roughness
    props.snap_solid_metalness    = props.solid_metalness
    props.snap_metal_roughness    = props.metal_roughness
    props.snap_metal_metalness    = props.metal_metalness
    props.snap_emission_roughness = props.emission_roughness
    props.snap_emission_metalness = props.emission_metalness
    props.snap_emission_strips    = ",".join(
        str(e.value) for e in props.emission_strengths)


def _needs_confirmation(props) -> dict:
    """Determine which breaking changes (if any) require a confirmation dialog.

    Compares ``props`` against its own ``snap_*`` snapshot fields and returns
    a dict of warning flags.  An empty dict means no confirmation is needed
    (no breaking changes detected).

    Breaking changes are:
    * **UV shift** — ``color_columns``, ``color_rows``, ``pastel_saturation``,
      ``shadow_value``, or emission strip values/count changed.  These cause
      all existing multicol UV assignments to point to wrong colours.
    * **Singlecol disconnect** — any PBR value or strip configuration changed
      while at least one singlecol material is cached.  The singlecols will
      be left with outdated baked PBR values.

    Args:
        props: ``DCPProperties`` instance from the active scene.

    Returns:
        A dict with zero or more of the following keys:

        * ``"_has_uv_shift"`` (``True``) — UV assignments will shift.
        * ``"_n_sc"`` (``int``) — number of singlecol materials that will be
          disconnected.

        An empty dict signals that regeneration can proceed without a dialog.
    """
    result = {}
    uv_shift = (
        props.color_columns     != props.snap_color_columns or
        props.color_rows        != props.snap_color_rows or
        props.pastel_saturation != props.snap_pastel_saturation or
        props.shadow_value      != props.snap_shadow_value
    )
    pbr_change = (
        props.solid_roughness    != props.snap_solid_roughness or
        props.solid_metalness    != props.snap_solid_metalness or
        props.metal_roughness    != props.snap_metal_roughness or
        props.metal_metalness    != props.snap_metal_metalness or
        props.emission_roughness != props.snap_emission_roughness or
        props.emission_metalness != props.snap_emission_metalness
    )
    curr_strips  = ",".join(str(e.value) for e in props.emission_strengths)
    strip_change = (curr_strips != props.snap_emission_strips)

    if uv_shift or strip_change:
        result["_has_uv_shift"] = True
    n_sc = len(props.singlecol_mats)
    if (pbr_change or strip_change) and n_sc > 0:
        result["_n_sc"] = n_sc
    return result


# ============================================================================
# CORE GENERATION LOGIC
# ============================================================================

def _run_generate(operator, context, props) -> None:
    """Execute the full DCP palette generation pipeline.

    This function is intentionally kept separate from any operator's
    ``execute()`` method so that both ``DCP_OT_GeneratePalette`` and
    ``DCP_OT_ConfirmRegenerate`` can call it without one operator needing to
    instantiate the other.

    Pipeline steps:

    1. Resolve and validate ``file_save_path``.
    2. Compute the full palette colour grid.
    3. Render and (optionally save) ``dcp_albedo`` via :func:`~textures._render_sheet`.
    4. Render and (optionally save) ``dcp_material`` via :func:`~textures._render_sheet`.
    5. Render ``dcp_picker`` and rebuild the PColl preview.
    6. Build or update ``dcp_multicol`` and store its pointer on *props*.
    7. Set ``palette_generated = True``, recompute preview colour, write snapshot.
    8. Display the picker in the Image Editor and schedule area redraws.

    Args:
        operator: The calling operator instance; used only for
            ``operator.report()``.
        context: The current Blender context.
        props: ``DCPProperties`` instance from the active scene.
    """
    save_path = props.file_save_path.strip() or None
    if save_path:
        save_path = bpy.path.abspath(save_path)
        if not os.path.isdir(save_path):
            operator.report({"WARNING"},
                            f"Export path not found: {save_path}")
            save_path = None

    colors = get_palette_colors(props)

    layout = get_layout(props)
    cs     = layout.cell_size

    def draw_albedo(shader, positions, colors_loc):
        for px, py in positions:
            _draw_palette_tile(shader, px, py + layout.text_height,
                               colors_loc, cs,
                               props.color_columns, props.color_rows)

    img_albedo = _render_sheet(props, ALBEDO_IMAGE_NAME, draw_albedo, colors, save_path)

    mat_cfg = [
        (props.solid_roughness,    props.solid_metalness,    False),
        (props.metal_roughness,    props.metal_metalness,    False),
        (props.emission_roughness, props.emission_metalness, True),
    ]

    def draw_material(shader, positions, _):
        for idx, (px, py) in enumerate(positions):
            r, m, is_em = mat_cfg[idx]
            _draw_material_tile(shader, px, py + layout.text_height,
                                r, m, is_em, props, cs)

    img_matmap = _render_sheet(props, MATERIAL_IMAGE_NAME, draw_material, colors, save_path)

    _render_picker_image(props, colors)
    _build_picker_preview()

    mat = build_or_update_multicol_material(props, img_albedo, img_matmap)
    props.multicol_mat      = mat
    props.palette_generated = True

    force_stop_pick_mode(context)
    props.sel_quadrant = "0"
    props.sel_cell_x   = 0
    props.sel_cell_y   = 0

    _recompute_preview(props)
    _write_snapshot(props)

    if save_path:
        config_data = {
            "albedo_image_name":  ALBEDO_IMAGE_NAME,
            "material_image_name": MATERIAL_IMAGE_NAME,
            "emission_strips":    [round(e.value, 2) for e in props.emission_strengths],
            "emission_factor":    props.emission_factor,
            "color_columns":      props.color_columns,
            "color_rows":         props.color_rows,
            "cell_size":          cs,
            "info_line1":         props.info_line_1,
            "info_line2":         props.info_line_2,
            "info_line3":         props.info_line_3,
        }
        config_path = os.path.join(save_path, PREFIX + "config.json")
        with open(config_path, "w", encoding="utf-8") as fh:
            json.dump(config_data, fh, indent=2)

        strips_gd = "[" + ", ".join(
            f"{e.value:.2f}" for e in props.emission_strengths
        ) + "]"
        gd_lines = [
            "class_name DCPConfig",
            "extends RefCounted",
            "",
            f"## Constants for DCP-Textures",
            "",
            f"## Generated by Dynamic Color Palette v{VERSION}",
            "",
            f'const ALBEDO_IMAGE_NAME: String = "{ALBEDO_IMAGE_NAME}"',
            f'const MATERIAL_IMAGE_NAME: String = "{MATERIAL_IMAGE_NAME}"',
            f"const COLOR_COLUMNS: int = {props.color_columns}",
            f"const COLOR_ROWS: int = {props.color_rows}",
            f"const CELL_SIZE: int = {cs}",
            f"const EMISSION_FACTOR: float = {props.emission_factor:.6g}",
            f"const EMISSION_STRIPS: Array[float] = {strips_gd}",
            f'const INFO_LINE1: String = "{props.info_line_1}"',
            f'const INFO_LINE2: String = "{props.info_line_2}"',
            f'const INFO_LINE3: String = "{props.info_line_3}"',
            "",
        ]
        gd_path = os.path.join(save_path, PREFIX + "config.gd")
        with open(gd_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(gd_lines))

    operator.report({"INFO"}, "Palette generated.")
    show_picker_in_image_editor(context)

    for area in context.screen.areas:
        if area.type in {"VIEW_3D", "IMAGE_EDITOR", "PROPERTIES"}:
            area.tag_redraw()


# ============================================================================
# OPERATORS
# ============================================================================

class DCP_OT_GeneratePalette(Operator):
    """Generate or regenerate the DCP palette textures and multicol material.

    On first use (``palette_generated == False``) the generation runs
    immediately without any confirmation.

    On subsequent uses the operator compares the current configuration against
    the snapshot written during the last generation (see
    :func:`_needs_confirmation`).  If breaking changes are detected it opens
    :class:`DCP_OT_ConfirmRegenerate` as a sub-dialog and returns early.
    If no breaking changes are detected it regenerates directly.

    This operator is intended to be invoked from both the N-Panel's Configure
    dialog (:class:`~operators.config.DCP_OT_OpenConfig`) and the main panel.
    """

    bl_idname      = "dcp.generate_palette"
    bl_label       = "Generate Palette"
    bl_description = "Generate palette textures and the multicol material"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        """Return ``True`` when a scene with ``dcp_props`` is available.

        Args:
            context: The current Blender context.

        Returns:
            ``True`` if ``context.scene`` is not ``None`` and has a
            ``dcp_props`` attribute.
        """
        return context.scene is not None and hasattr(context.scene, "dcp_props")

    def execute(self, context) -> set:
        """Run generation or open the confirmation dialog.

        Args:
            context: The current Blender context.

        Returns:
            ``{"FINISHED"}`` in all cases (the confirmation dialog is opened
            via ``bpy.ops.dcp.confirm_regenerate("INVOKE_DEFAULT")`` which
            does not block this operator's return value).
        """
        global _pending_generation
        props = context.scene.dcp_props

        if props.palette_generated:
            warn = _needs_confirmation(props)
            if warn:
                _pending_generation.update(warn)
                bpy.ops.dcp.confirm_regenerate("INVOKE_DEFAULT")
                return {"FINISHED"}
            # No relevant changes – regenerate directly without dialog.
            _invalidate_emission_cache()
            props.singlecol_mats.clear()
            _run_generate(self, context, props)
            return {"FINISHED"}

        # First generation – run directly.
        _invalidate_emission_cache()
        _run_generate(self, context, props)
        return {"FINISHED"}


class DCP_OT_ResetDefaults(Operator):
    """Reset all palette configuration properties to built-in default values.

    Writes every configurable ``DCPProperties`` field back to the
    corresponding ``DEFAULT_*`` constant from :mod:`__init__`.  Also
    resets the ``emission_strengths`` collection to three default strip
    values.  Does **not** regenerate the palette or modify the snapshot.
    """

    bl_idname      = "dcp.reset_defaults"
    bl_label       = "Reset to Defaults"
    bl_description = "Reset all palette settings to built-in default values"

    def execute(self, context) -> set:
        """Apply all default values and invalidate the emission cache.

        Args:
            context: The current Blender context.

        Returns:
            ``{"FINISHED"}`` on success.
        """
        props = context.scene.dcp_props
        props.color_columns      = DEFAULT_COLOR_COLUMNS
        props.color_rows         = DEFAULT_COLOR_ROWS
        props.pastel_saturation  = DEFAULT_PASTEL_SATURATION
        props.shadow_value       = DEFAULT_SHADOW_VALUE
        props.solid_roughness    = DEFAULT_SOLID_ROUGHNESS
        props.solid_metalness    = DEFAULT_SOLID_METALNESS
        props.metal_roughness    = DEFAULT_METAL_ROUGHNESS
        props.metal_metalness    = DEFAULT_METAL_METALNESS
        props.emission_roughness = DEFAULT_EMISSION_ROUGHNESS
        props.emission_metalness = DEFAULT_EMISSION_METALNESS
        props.emission_factor    = DEFAULT_EMISSION_FACTOR
        props.file_save_path     = DEFAULT_FILE_SAVE_PATH

        props.emission_strengths.clear()
        for v in DEFAULT_EMISSION_STRIPS:
            props.emission_strengths.add().value = v

        props.info_line_1 = DEFAULT_INFO_LINE_1
        props.info_line_2 = DEFAULT_INFO_LINE_2
        props.info_line_3 = DEFAULT_INFO_LINE_3
        props.bg_hex      = DEFAULT_BG_HEX
        props.fg_hex      = DEFAULT_FG_HEX

        _invalidate_emission_cache()
        self.report({"INFO"}, "Settings reset to defaults.")
        return {"FINISHED"}


class DCP_OT_ConfirmRegenerate(Operator):
    """Safety confirmation dialog before regenerating a palette with breaking changes.

    Invoked by :class:`DCP_OT_GeneratePalette` via
    ``bpy.ops.dcp.confirm_regenerate("INVOKE_DEFAULT")`` when
    :func:`_needs_confirmation` returns a non-empty dict.  The operator reads
    its parameters from the module-level :data:`_pending_generation` dict,
    displays a summary of the consequences, and runs :func:`_run_generate` on
    confirmation.

    The operator's ``poll`` returns ``False`` when ``_pending_generation`` is
    empty, preventing accidental invocation when no generation is pending.
    """

    bl_idname      = "dcp.confirm_regenerate"
    bl_label       = "Regenerate Palette?"
    bl_description = "Confirm regeneration — existing UV assignments may be affected"
    bl_options     = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context) -> bool:
        """Return ``True`` only when a pending generation has been staged.

        Args:
            context: The current Blender context (unused).

        Returns:
            ``True`` if :data:`_pending_generation` is non-empty.
        """
        return bool(_pending_generation)

    def invoke(self, context, event) -> set:
        """Open the confirmation dialog.

        Args:
            context: The current Blender context.
            event: The triggering event (unused).

        Returns:
            The return value of ``invoke_props_dialog``, typically
            ``{"RUNNING_MODAL"}``.
        """
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context) -> None:
        """Draw the dialog body with consequence warnings.

        Shows one or two warning labels depending on which flags are set in
        :data:`_pending_generation`:

        * UV shift warning — when ``"_has_uv_shift"`` is ``True``.
        * Singlecol disconnect warning — when ``"_n_sc"`` is > 0.
        * A final "Continue?" prompt.

        Args:
            context: The current Blender context (unused in draw).
        """
        layout   = self.layout
        uv_shift = _pending_generation.get("_has_uv_shift", False)
        n_sc     = _pending_generation.get("_n_sc", 0)

        if uv_shift:
            layout.label(
                text="Multicolor UV assignments will shift.",
                icon="ERROR")
        if n_sc > 0:
            layout.label(
                text=f"{n_sc} Singlecolor material(s) will be "
                     "disconnected from DCP.",
                icon="ERROR")
        layout.separator()
        layout.label(text="Continue with regeneration?")

    def execute(self, context) -> set:
        """Commit the regeneration after user confirmation.

        Invalidates the emission layout cache, clears the singlecol cache,
        clears :data:`_pending_generation`, and delegates to
        :func:`_run_generate`.

        Args:
            context: The current Blender context.

        Returns:
            ``{"FINISHED"}`` on success.
        """
        global _pending_generation
        props = context.scene.dcp_props

        _invalidate_emission_cache()
        props.singlecol_mats.clear()
        _pending_generation = {}

        _run_generate(self, context, props)
        self.report({"INFO"}, "Palette regenerated.")
        return {"FINISHED"}
