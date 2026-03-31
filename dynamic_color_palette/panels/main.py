# SPDX-License-Identifier: GPL-3.0-or-later
"""Main N-Panel for the Dynamic Color Palette addon.

Registers ``DCP_PT_Main`` as a side-panel (N-Panel) tab in the 3D Viewport
under the label *DCP*.  The panel is visible in both Object Mode and Edit Mode.

Panel layout overview
---------------------
When no palette has been generated yet::

    [ ⚙  Configure… ]
    ℹ  Configure palette, then click Generate.

After a palette exists::

    [ ⚙  Configure… ]
    [ 👁  Pick From Image Editor: OFF / ON (ESC to stop) ]
    ℹ  Open an Image Editor to enable picking.   ← only when no IE open

    ┌────────────────────────────────────┐
    │  [ Solid ] [ Metal ] [ Emission ]  │
    │  Cell X  (0 – N)                   │
    │  Cell Y  (0 – N)                   │
    │  Emission Strip  (0 – N)           │  ← only in Emission quadrant
    │                                    │
    │  Color  ████   Hex  #FF8040        │
    │  RGB    …      RME  R:… M:… E:…    │
    │                                    │
    │  N Faces in M Objects selected     │  ← Edit Mode
    │  N Objects selected                │  ← Object Mode
    │                                    │
    │  [ UV  Assign Multicolor Material ]│
    │  [ ■   Assign Singlecolor Material]│
    │  ⚠ No UV layer: ObjectName        │  ← one line per object, max 3
    │    … and N more                    │
    └────────────────────────────────────┘

    ─────────────────────────────────
    [ 🗑  Cleanup Unused Slots ]
"""
from __future__ import annotations

import bpy
from bpy.types import Panel

from ..core.palette import pbr_from_quadrant, rgb_to_hex
from ..core.image_editor import is_pick_mode_available


class DCP_PT_Main(Panel):
    """Main N-Panel tab shown in the 3D Viewport sidebar under *DCP*.

    Visible in both ``OBJECT`` and ``EDIT_MESH`` modes.  All palette
    configuration is delegated to :class:`~operators.config.DCP_OT_OpenConfig`
    (a modal ``invoke_props_dialog``), keeping the panel itself compact.

    The panel is split into four logical sections:

    1. **Configure button** — always visible; opens the configuration dialog.
    2. **Picker row** — toggle for the Image Editor colour-picker modal.
       Disabled (greyed out) when no Image Editor area is open.
    3. **Colour info** — read-only display of the selected cell's colour,
       hex code, and PBR values.
    4. **Selection and assign** — shows how many faces/objects are selected,
       UV-layer warnings, and the two assign buttons.
    5. **Cleanup** — slot/material cleanup button, enabled only when the
       selection has materials.
    """

    bl_label       = "Dynamic Color Palette"
    bl_idname      = "DCP_PT_main"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "DCP"
    bl_order       = 10

    @classmethod
    def poll(cls, context) -> bool:
        """Return ``True`` when the panel should be visible.

        The panel requires:
        * An active scene with ``dcp_props`` attached.
        * The current mode to be either ``OBJECT`` or ``EDIT_MESH``.

        Args:
            context: The current Blender context.

        Returns:
            ``True`` if all preconditions are met, ``False`` otherwise.
        """
        return (context.scene is not None and
                hasattr(context.scene, "dcp_props") and
                context.mode in {"OBJECT", "EDIT_MESH"})

    def draw(self, context) -> None:
        """Draw the panel UI.

        Reads ``context.scene.dcp_props`` and ``context.mode`` on every
        redraw.  The panel returns early (showing only the Configure button
        and an info label) when ``palette_generated`` is ``False``.

        Args:
            context: The current Blender context.
        """
        layout = self.layout
        props  = context.scene.dcp_props
        mode   = context.mode

        # ---- Configure -------------------------------------------------
        layout.operator("dcp.open_config", text="Configure\u2026", icon="PREFERENCES")

        if not props.palette_generated:
            layout.label(text="Configure palette, then click Generate.", icon="INFO")
            return

        layout.separator()

        # ---- Picker ----------------------------------------------------
        ie_open = is_pick_mode_available(context)
        row     = layout.row()
        row.enabled = ie_open
        if props.pick_from_image_editor and ie_open:
            row.operator("dcp.stop_pick_from_image_editor",
                         text="Pick From Image Editor: ON (ESC to stop)",
                         icon="PAUSE")
        else:
            row.operator("dcp.pick_from_image_editor",
                         text="Pick From Image Editor: OFF",
                         icon="EYEDROPPER")
        if not ie_open:
            layout.label(text="Open an Image Editor to enable picking.",
                         icon="INFO")

        layout.separator()

        # ---- Box: selection, colour info, assign -----------------------
        box = layout.box()

        # Quadrant + cell selection
        row = box.row(align=True)
        row.prop(props, "sel_quadrant", expand=True)
        col = box.column(align=True)
        col.prop(props, "sel_cell_x",
                 text=f"Cell X  (0 \u2013 {props.color_columns - 1})")
        col.prop(props, "sel_cell_y",
                 text=f"Cell Y  (0 \u2013 {props.color_rows - 1})")
        if props.sel_quadrant == "2":
            n_strips = len(props.emission_strengths)
            col.prop(props, "sel_emission",
                     text=f"Emission Strip  (0 \u2013 {max(0, n_strips - 1)})")

        box.separator()

        # Colour info (read-only)
        try:
            r, g, b, _ = props.preview_color
            split      = box.split(factor=0.35)
            cl, cr     = split.column(), split.column()
            cl.label(text="Color")
            sw         = cr.row()
            sw.enabled = False
            sw.prop(props, "preview_color", text="")
            cl.label(text="Hex")
            cr.label(text=rgb_to_hex(r, g, b))
            cl.label(text="RGB")
            cr.label(text=f"{r:.2f}  {g:.2f}  {b:.2f}")
            roughness, metalness, em = pbr_from_quadrant(
                props, int(props.sel_quadrant), props.sel_emission)
            cl.label(text="RME")
            cr.label(text=f"R: {roughness:.2f}  M: {metalness:.2f}  "
                          f"E: {em:.2f}")
        except Exception as exc:
            box.label(text=f"Preview unavailable: {exc}")

        box.separator()

        # Selection info
        obj         = context.active_object
        has_sel     = False
        no_uv_names = []

        if mode == "EDIT_MESH" and obj:
            edit_objs = getattr(context, "objects_in_mode", None) or [obj]
            edit_objs = [o for o in edit_objs if o and o.type == "MESH"]
            nf        = sum(o.data.count_selected_items()[2] for o in edit_objs)
            no_objs   = len(edit_objs)
            has_sel   = nf > 0
            fw        = "Face" if nf == 1 else "Faces"
            ow        = "Object" if no_objs == 1 else "Objects"
            box.label(
                text=f"{nf} {fw} in {no_objs} {ow} selected" if has_sel
                     else "Nothing selected",
                icon="FACE_MAPS" if has_sel else "INFO")
            for edit_obj in edit_objs:
                try:
                    import bmesh
                    bm = bmesh.from_edit_mesh(edit_obj.data)
                    if not bm.loops.layers.uv.active:
                        no_uv_names.append(edit_obj.name)
                except Exception:
                    pass

        elif mode == "OBJECT":
            sel_meshes = [o for o in context.selected_objects if o.type == "MESH"]
            n          = len(sel_meshes)
            has_sel    = n > 0
            ow         = "Object" if n == 1 else "Objects"
            box.label(
                text=f"{n} {ow} selected" if has_sel else "Nothing selected",
                icon="OBJECT_DATA" if has_sel else "INFO")
            for o in sel_meshes:
                if not o.data.uv_layers.active:
                    no_uv_names.append(o.name)

        # Assign buttons
        col = box.column(align=True)
        col.enabled = has_sel
        col.operator("dcp.assign_multicol",
                     text="Assign Multicolor Material", icon="UV")
        col.operator("dcp.assign_singlecol",
                     text="Assign Singlecolor Material", icon="MATERIAL")

        if has_sel and no_uv_names:
            for name in no_uv_names[:3]:
                box.label(text=f"\u26a0 No UV layer: {name}", icon="ERROR")
            extra = len(no_uv_names) - 3
            if extra > 0:
                box.label(text=f"  \u2026 and {extra} more")

        layout.separator()

        # ---- Cleanup ---------------------------------------------------
        if mode == "EDIT_MESH":
            has_mats = bool(obj and obj.type == "MESH" and obj.data.materials)
        else:
            has_mats = any(
                bool(o.data.materials)
                for o in context.selected_objects if o.type == "MESH"
            )
        row         = layout.row()
        row.enabled = has_mats and (True if mode == "EDIT_MESH" else has_sel)
        row.operator("dcp.cleanup_unused_slots",
                     icon="TRASH", text="Cleanup Unused Slots")
