# SPDX-License-Identifier: GPL-3.0-or-later
"""Configuration dialog operator for Dynamic Color Palette.

This module implements the palette configuration UI as a modal
``invoke_props_dialog`` operator rather than a sub-panel.  The design choice
keeps the N-Panel compact: all configuration lives behind a single
*Configure…* button.

The dialog is divided into five collapsible sections (implemented as
``WindowManager`` bool properties that persist across dialog sessions):

* **Palette** — grid dimensions and colour distribution (columns, rows,
  pastel saturation, shadow value).
* **PBR** — roughness and metalness per quadrant (Solid / Metal / Emission).
* **Emission Strength** — emission factor and per-strip normalised strength
  values.
* **Export** — optional directory path for PNG export.
* **Info Quadrant** — project/studio/license text and background/foreground
  hex colours for the info quadrant rendered in the texture.

Private helpers
---------------
_register_wm_props
    Attach collapsible-section state booleans to ``bpy.types.WindowManager``
    when the dialog is first opened.
_unregister_wm_props
    Remove those booleans during addon unregistration.
_section
    Draw one collapsible box header and return ``(box, is_open)``.
"""
from __future__ import annotations

import bpy
from bpy.types import Operator
from bpy.props import BoolProperty

from .. import MAX_EMISSION_STRIPS, DEFAULT_EMISSION_STRIPS, PREFIX


def _register_wm_props() -> None:
    """Attach collapsible-section toggle booleans to ``bpy.types.WindowManager``.

    Each boolean corresponds to one section in the configuration dialog.
    They are stored on ``WindowManager`` (rather than on the scene) so the
    open/closed state is not saved to the ``.blend`` file and is shared across
    all open scenes.

    The function is idempotent — it skips attributes that already exist so it
    can be called safely on every dialog open.
    """
    wm = bpy.types.WindowManager
    for attr, default in (
        ("dcp_cfg_palette_open",   True),
        ("dcp_cfg_pbr_open",       False),
        ("dcp_cfg_emission_open",  False),
        ("dcp_cfg_export_open",    False),
        ("dcp_cfg_info_open",      False),
    ):
        if not hasattr(wm, attr):
            setattr(wm, attr, BoolProperty(default=default))


def _unregister_wm_props() -> None:
    """Remove the collapsible-section toggle booleans from ``bpy.types.WindowManager``.

    Called from :func:`~__init__.unregister` to clean up the dynamic attributes
    added by :func:`_register_wm_props`.  Missing attributes are silently
    ignored.
    """
    wm = bpy.types.WindowManager
    for attr in ("dcp_cfg_palette_open", "dcp_cfg_pbr_open",
                 "dcp_cfg_emission_open", "dcp_cfg_export_open",
                 "dcp_cfg_info_open"):
        if hasattr(wm, attr):
            delattr(wm, attr)


def _section(layout, wm, attr: str, label: str, icon: str):
    """Draw a collapsible section header inside a box.

    Renders a box containing a toggle arrow icon and a label.  The toggle
    state is stored in the ``WindowManager`` attribute *attr*.

    Args:
        layout: The parent ``UILayout`` to draw into.
        wm: ``context.window_manager``; used to read and write *attr*.
        attr: Name of the ``BoolProperty`` on *wm* that controls open/closed
            state.
        label: Human-readable section title displayed next to the arrow.
        icon: Blender icon identifier for the section (e.g. ``"COLOR"``).

    Returns:
        ``(box, is_open)`` — the ``UILayout`` box and a bool indicating
        whether the section is currently expanded.
    """
    open_ = getattr(wm, attr)
    box   = layout.box()
    row   = box.row()
    row.prop(wm, attr,
             icon="TRIA_DOWN" if open_ else "TRIA_RIGHT",
             icon_only=True, emboss=False)
    row.label(text=label, icon=icon)
    return box, open_


class DCP_OT_OpenConfig(Operator):
    """Open the Palette Configuration dialog.

    Invoked from the N-Panel's *Configure…* button.  Uses
    ``context.window_manager.invoke_props_dialog()`` to open a blocking modal
    dialog.  Changes to ``DCPProperties`` fields take effect immediately as
    the user edits them; there is no Cancel / Undo for individual field
    changes (this is standard Blender dialog behaviour).

    Pressing *OK* (or Enter) closes the dialog and calls ``execute()``,
    which simply returns ``{"FINISHED"}`` — no additional action is taken.
    The *Generate / Regenerate Palette* button inside the dialog invokes
    :class:`~operators.generate.DCP_OT_GeneratePalette` independently.
    """

    bl_idname = "dcp.open_config"
    bl_label  = "Palette Configuration"
    bl_description = "Open the Palette Configuration dialog."

    def invoke(self, context, event) -> set:
        """Register WindowManager props and open the dialog.

        Also initialises ``emission_strengths`` with default strip values if
        the collection is empty and no palette has been generated yet.

        Args:
            context: The current Blender context.
            event: The triggering event (unused).

        Returns:
            The return value of ``invoke_props_dialog``.
        """
        _register_wm_props()
        props = context.scene.dcp_props
        if len(props.emission_strengths) == 0 and not props.palette_generated:
            for v in DEFAULT_EMISSION_STRIPS:
                props.emission_strengths.add().value = v
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context) -> None:
        """Draw all five collapsible configuration sections.

        Each section is wrapped in a box with a toggle header (see
        :func:`_section`).  Only the *Palette* section is expanded by default.

        Args:
            context: The current Blender context.
        """
        layout = self.layout
        props  = context.scene.dcp_props
        wm     = context.window_manager

        # ---- Palette ---------------------------------------------------
        box, open_ = _section(layout, wm, "dcp_cfg_palette_open",
                               "Palette", "COLOR")
        if open_:
            col = box.column(align=True)
            col.prop(props, "color_columns")
            col.prop(props, "color_rows")
            col.prop(props, "pastel_saturation", slider=True)
            col.prop(props, "shadow_value",      slider=True)

        # ---- PBR -------------------------------------------------------
        box, open_ = _section(layout, wm, "dcp_cfg_pbr_open",
                               "PBR", "MATERIAL")
        if open_:
            col = box.column(align=True)
            col.label(text="Solid")
            col.prop(props, "solid_roughness",    slider=True, text="Roughness")
            col.prop(props, "solid_metalness",    slider=True, text="Metal")
            col.separator()
            col.label(text="Metal")
            col.prop(props, "metal_roughness",    slider=True, text="Roughness")
            col.prop(props, "metal_metalness",    slider=True, text="Metal")
            col.separator()
            col.label(text="Emission")
            col.prop(props, "emission_roughness", slider=True, text="Roughness")
            col.prop(props, "emission_metalness", slider=True, text="Metal")

        # ---- Emission Strength -----------------------------------------
        box, open_ = _section(layout, wm, "dcp_cfg_emission_open",
                               "Emission Strength", "FORCE_CHARGE")
        if open_:
            col = box.column(align=True)
            col.prop(props, "emission_factor")
            col.separator()
            n = len(props.emission_strengths)
            col.label(text=f"Strips  (max {MAX_EMISSION_STRIPS}, values 0.0 \u2013 1.0):")
            for i, entry in enumerate(props.emission_strengths):
                row_s         = col.row(align=True)
                row_s.prop(entry, "value", text=f"Strip {i + 1}")
                op            = row_s.operator("dcp.remove_emission_strip",
                                               text="", icon="REMOVE")
                op.index      = i
                row_s.enabled = n > 1
            add_row         = col.row()
            add_row.enabled = n < MAX_EMISSION_STRIPS
            add_row.operator("dcp.add_emission_strip", text="Add Strip", icon="ADD")

        # ---- Export ----------------------------------------------------
        box, open_ = _section(layout, wm, "dcp_cfg_export_open",
                               "Export", "EXPORT")
        if open_:
            col = box.column(align=True)
            col.prop(props, "textures_export_dir",
                     text=f"Export {PREFIX}albedo.png / {PREFIX}material.png")
            col.prop(props, "json_export_dir",
                     text=f"Export {PREFIX}config.json")
            col.prop(props, "gdshader_export_dir",
                     text="Export dcp_multicol.gdshader")
            col.prop(props, "gdutilclass_export_dir",
                     text="Export dcp_util.gd")

        # ---- Info Quadrant ---------------------------------------------
        box, open_ = _section(layout, wm, "dcp_cfg_info_open",
                               "Info Quadrant", "TEXT")
        if open_:
            col = box.column(align=True)
            col.prop(props, "info_line_1")
            col.prop(props, "info_line_2")
            col.prop(props, "info_line_3")
            col.separator()
            row = col.row(align=True)
            row.prop(props, "bg_hex", text="BG Hex")
            row.prop(props, "fg_hex", text="FG Hex")

        layout.separator()

        # ---- Actions ---------------------------------------------------
        col = layout.column(align=True)
        col.scale_y = 1.2
        col.operator("dcp.generate_palette",
                     text="Generate Palette" if not props.palette_generated
                     else "Regenerate Palette",
                     icon="FILE_REFRESH")
        col.operator("dcp.reset_defaults",
                     text="Reset to Defaults", icon="LOOP_BACK")

    def execute(self, context) -> set:
        """Close the dialog.

        No additional action is performed; all property changes have already
        been applied live as the user edited them.

        Args:
            context: The current Blender context (unused).

        Returns:
            ``{"FINISHED"}``.
        """
        return {"FINISHED"}
