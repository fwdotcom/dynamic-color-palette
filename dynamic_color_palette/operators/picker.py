# SPDX-License-Identifier: GPL-3.0-or-later
"""Image Editor colour-picker modal operator.

Implements an interactive colour picker that reads clicks from the
``dcp_picker`` image displayed in Blender's Image Editor.

Operators
---------
DCP_OT_PickFromImageEditor
    Modal operator.  While running, every left-click inside the Image Editor
    on the ``dcp_picker`` image is translated to a palette cell address via
    :func:`~core.image_editor.picker_pixel_to_cell`.  If a mesh selection
    exists the colour is applied immediately via
    ``bpy.ops.dcp.assign_multicol``; otherwise the selection in the N-Panel
    is updated without assigning.

DCP_OT_StopPickFromImageEditor
    Non-modal helper that calls
    :func:`~core.image_editor.force_stop_pick_mode` to terminate an active
    pick session from outside the modal handler (e.g. from the N-Panel
    toggle button).

Concurrency
-----------
Only one instance of ``DCP_OT_PickFromImageEditor`` may be running at a
time.  This is enforced via the class-level ``_is_running`` boolean, which
is also checked by :func:`~core.image_editor.force_stop_pick_mode` when
clearing stale state.
"""
from __future__ import annotations

import bpy
from bpy.types import Operator

from .. import PICKER_IMAGE_NAME
from ..core.image_editor import (
    is_pick_mode_available, show_picker_in_image_editor,
    force_stop_pick_mode, find_area_and_region_under_mouse,
    image_editor_mouse_to_image_px, picker_pixel_to_cell,
)



class DCP_OT_PickFromImageEditor(Operator):
    """Modal colour-picker operator for the DCP Image Editor workflow.

    Starts a modal handler that intercepts left-click events over the Image
    Editor.  On each click:

    1. The screen-space mouse coordinates are converted to picker-image pixel
       coordinates via :func:`~core.image_editor.image_editor_mouse_to_image_px`.
    2. The pixel coordinates are mapped to a palette ``(cell_x, cell_y)`` via
       :func:`~core.image_editor.picker_pixel_to_cell`.
    3. ``props.sel_cell_x`` and ``props.sel_cell_y`` are updated so the
       N-Panel reflects the picked colour.
    4. If a mesh selection exists (Edit Mode faces or selected Objects), the
       colour is applied immediately by invoking
       ``bpy.ops.dcp.assign_multicol`` inside a 3D Viewport context override.

    ESC or RMB terminates the modal; the panel button also calls
    :class:`DCP_OT_StopPickFromImageEditor` to stop it from the UI.

    All pass-through events (anything other than LMB, ESC, RMB) are forwarded
    so normal Blender navigation and shortcuts remain functional while the
    picker is active.
    """

    bl_idname      = "dcp.pick_from_image_editor"
    bl_label       = "Pick From Image Editor"
    bl_description = "Enable color picking from the palette in the Image Editor"
    bl_options: set = set()

    _is_running: bool = False
    """Class-level flag preventing multiple simultaneous pick sessions."""

    @classmethod
    def poll(cls, context) -> bool:
        """Return ``True`` when picking is possible.

        Requires a scene with ``dcp_props`` and a generated palette.

        Args:
            context: The current Blender context.

        Returns:
            ``True`` if the palette has been generated.
        """
        return (context.scene is not None and
                hasattr(context.scene, "dcp_props") and
                context.scene.dcp_props.palette_generated)

    def invoke(self, context, event) -> set:
        """Validate preconditions and start the modal handler.

        Checks that an Image Editor is available, that no other pick session
        is running, and that ``dcp_picker`` can be displayed.  On success the
        status bar is updated and a modal handler is registered.

        Args:
            context: The current Blender context.
            event: The triggering event (unused).

        Returns:
            ``{"RUNNING_MODAL"}`` on success, ``{"CANCELLED"}`` if any
            precondition fails.
        """
        props = context.scene.dcp_props
        if not is_pick_mode_available(context):
            force_stop_pick_mode(context)
            self.report({"WARNING"},
                        "Open an Image Editor in the current workspace first.")
            return {"CANCELLED"}
        if self.__class__._is_running and not props.pick_from_image_editor:
            self.__class__._is_running = False
        if self.__class__._is_running:
            self.report({"WARNING"}, "Pick mode already running.")
            return {"CANCELLED"}
        if not show_picker_in_image_editor(context):
            self.report({"WARNING"}, "Failed to display picker image.")
            return {"CANCELLED"}

        props.pick_from_image_editor = True
        self.__class__._is_running   = True
        context.window_manager.modal_handler_add(self)
        try:
            context.workspace.status_text_set(
                "DCP Pick  |  LMB: Pick  |  ESC / RMB: Stop")
        except Exception:
            pass
        for area in context.screen.areas:
            if area.type in {"VIEW_3D", "IMAGE_EDITOR", "PROPERTIES"}:
                area.tag_redraw()
        return {"RUNNING_MODAL"}

    def _finish(self, context, cancelled: bool = False) -> set:
        """Terminate the modal session and clean up state.

        Clears ``_is_running`` and ``pick_from_image_editor``, removes the
        status bar text, and schedules redraws for all relevant areas across
        all windows.

        Args:
            context: The current Blender context.
            cancelled: If ``True`` the operator returns ``{"CANCELLED"}``;
                otherwise ``{"FINISHED"}``.

        Returns:
            ``{"CANCELLED"}`` or ``{"FINISHED"}``.
        """
        self.__class__._is_running               = False
        context.scene.dcp_props.pick_from_image_editor = False
        try:
            context.workspace.status_text_set(None)
        except Exception:
            pass
        for window in context.window_manager.windows:
            screen = window.screen
            if screen:
                for area in screen.areas:
                    if area.type in {"VIEW_3D", "IMAGE_EDITOR", "PROPERTIES"}:
                        area.tag_redraw()
        return {"CANCELLED"} if cancelled else {"FINISHED"}

    def modal(self, context, event) -> set:
        """Process one event during the pick session.

        Terminates on ESC or RMB.  Passes all non-LMB events through so the
        user can navigate the viewport normally.  On LMB inside the Image
        Editor, picks the cell and optionally assigns the colour.

        Args:
            context: The current Blender context.
            event: The current Blender event.

        Returns:
            ``{"PASS_THROUGH"}`` for non-pick events,
            ``{"RUNNING_MODAL"}`` while picking continues,
            or the return value of :meth:`_finish` when the session ends.
        """
        props = context.scene.dcp_props

        if not props.pick_from_image_editor:
            return self._finish(context)
        if not is_pick_mode_available(context):
            return self._finish(context)
        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            return self._finish(context)
        if not (event.type == "LEFTMOUSE" and event.value == "PRESS"):
            return {"PASS_THROUGH"}

        area, region = find_area_and_region_under_mouse(
            context, event.mouse_x, event.mouse_y)
        if area is None or area.type != "IMAGE_EDITOR":
            return {"PASS_THROUGH"}
        if region is None:
            return {"PASS_THROUGH"}

        space = area.spaces.active
        if not space or not getattr(space, "image", None):
            return {"PASS_THROUGH"}
        if space.image.name != PICKER_IMAGE_NAME:
            return {"PASS_THROUGH"}

        coords = image_editor_mouse_to_image_px(context, event)
        if coords is None:
            return {"RUNNING_MODAL"}

        cell = picker_pixel_to_cell(props, coords[0], coords[1])
        if cell is None:
            return {"RUNNING_MODAL"}

        # Update panel colour.
        props.sel_cell_x, props.sel_cell_y = cell

        # Determine whether a selection exists.
        obj            = context.active_object
        has_edit_faces = False
        has_obj_sel    = False

        if obj and obj.type == "MESH" and obj.mode == "EDIT":
            edit_objs      = getattr(context, "objects_in_mode", None) or [obj]
            has_edit_faces = any(
                o.data.count_selected_items()[2] > 0
                for o in edit_objs if o.type == "MESH")
        elif context.mode == "OBJECT":
            has_obj_sel = any(
                o.type == "MESH" for o in context.selected_objects)

        if not (has_edit_faces or has_obj_sel):
            # No selection — colour transferred to panel only; force redraw.
            for area in context.screen.areas:
                if area.type in {"VIEW_3D", "PROPERTIES"}:
                    area.tag_redraw()
            return {"RUNNING_MODAL"}

        # Find 3D Viewport for context override.
        view3d_area = next(
            (a for a in context.screen.areas if a.type == "VIEW_3D"), None)
        view3d_region = next(
            (r for r in view3d_area.regions if r.type == "WINDOW"),
            None) if view3d_area else None

        if not view3d_area or not view3d_region:
            return {"RUNNING_MODAL"}

        try:
            with context.temp_override(area=view3d_area,
                                       region=view3d_region,
                                       active_object=obj):
                bpy.ops.dcp.assign_multicol(from_picker=True)
        except Exception as exc:
            self.report({"WARNING"}, f"Picker assign failed: {exc}")

        return {"RUNNING_MODAL"}


class DCP_OT_StopPickFromImageEditor(Operator):
    """Stop an active Image Editor pick session from the N-Panel.

    Calls :func:`~core.image_editor.force_stop_pick_mode`, which clears all
    pick-mode state flags and schedules redraws.  This operator exists as a
    separate non-modal operator so the N-Panel toggle button can terminate
    the pick session without relying on the modal event loop.
    """

    bl_idname = "dcp.stop_pick_from_image_editor"
    bl_label  = "Stop Pick"
    bl_description = "Stop the Image Editor pick mode."

    def execute(self, context) -> set:
        """Terminate pick mode.

        Args:
            context: The current Blender context.

        Returns:
            ``{"FINISHED"}``.
        """
        force_stop_pick_mode(context)
        return {"FINISHED"}
