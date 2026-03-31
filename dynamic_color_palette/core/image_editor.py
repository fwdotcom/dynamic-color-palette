# SPDX-License-Identifier: GPL-3.0-or-later
"""Image Editor integration helpers for the DCP colour picker.

This module provides the bridge between Blender's Image Editor area and the
DCP picker modal operator.  All functions are stateless utilities; no
module-level Blender state is modified here.

Functions
---------
find_image_editor_area
    Locate the first Image Editor area in the current screen.
find_area_and_region_under_mouse
    Map screen-space mouse coordinates to an (area, region) pair.
is_pick_mode_available
    Quick check whether an Image Editor is open.
show_picker_in_image_editor
    Display ``dcp_picker`` in the found Image Editor and fit it to view.
image_editor_mouse_to_image_px
    Convert mouse coordinates to image-space pixel coordinates.
picker_pixel_to_cell
    Map picker-image pixel coordinates back to a palette (cell_x, cell_y).
force_stop_pick_mode
    Unconditionally terminate pick mode and redraw relevant areas.
"""
from __future__ import annotations

from typing import Optional

import bpy

from .. import PICKER_IMAGE_NAME


def find_image_editor_area(context) -> Optional[bpy.types.Area]:
    """Find the first Image Editor area in the current screen.

    Iterates over ``context.screen.areas`` and returns the first area whose
    type is ``"IMAGE_EDITOR"``.

    Args:
        context: The current Blender context.  ``context.screen`` may be
            ``None`` in some headless or background-render contexts.

    Returns:
        The first ``bpy.types.Area`` of type ``IMAGE_EDITOR``, or ``None``
        if no such area exists on the current screen.
    """
    screen = getattr(context, "screen", None)
    if screen is None:
        return None
    for area in screen.areas:
        if area.type == "IMAGE_EDITOR":
            return area
    return None


def find_area_and_region_under_mouse(context, mx: int, my: int):
    """Find the area and its WINDOW region that contains the given mouse position.

    Iterates over all areas and their regions in the current window's screen
    and performs a simple pixel-bounding-box test.

    Args:
        context: The current Blender context.
        mx: Mouse X coordinate in screen pixels (from ``event.mouse_x``).
        my: Mouse Y coordinate in screen pixels (from ``event.mouse_y``).

    Returns:
        ``(area, region)`` — a 2-tuple where *area* is a ``bpy.types.Area``
        and *region* is the ``WINDOW`` region that contains ``(mx, my)``.
        Returns ``(None, None)`` if no match is found or if the context has
        no window.
    """
    window = context.window
    screen = window.screen if window else None
    if screen is None:
        return None, None
    for area in screen.areas:
        for region in area.regions:
            if region.type != "WINDOW":
                continue
            if (region.x <= mx < region.x + region.width and
                    region.y <= my < region.y + region.height):
                return area, region
    return None, None


def is_pick_mode_available(context) -> bool:
    """Return ``True`` if an Image Editor area is present in the current screen.

    Used as a precondition check before starting the picker modal operator
    and to disable the picker button in the N-Panel when no Image Editor is
    open.

    Args:
        context: The current Blender context.

    Returns:
        ``True`` if at least one Image Editor area is found, ``False``
        otherwise.
    """
    return find_image_editor_area(context) is not None


def show_picker_in_image_editor(context) -> bool:
    """Display ``dcp_picker`` in the first Image Editor and fit it to the view.

    Sets the active image of the Image Editor's space to ``dcp_picker``, pins
    the image (so it is not replaced when the user switches context), and
    calls ``bpy.ops.image.view_all(fit_view=True)`` to zoom the view to fit
    the image bounds.

    Args:
        context: The current Blender context.

    Returns:
        ``True`` if the image was successfully displayed, ``False`` if no
        Image Editor area was found or ``dcp_picker`` does not exist in
        ``bpy.data.images``.
    """
    area = find_image_editor_area(context)
    if area is None:
        return False
    img = bpy.data.images.get(PICKER_IMAGE_NAME)
    if img is None:
        return False
    space = area.spaces.active
    if not hasattr(space, "image"):
        return False
    space.image = img
    if hasattr(space, "use_image_pin"):
        try:
            space.use_image_pin = True
        except Exception:
            pass
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    if region:
        try:
            with context.temp_override(area=area, region=region,
                                       space_data=space):
                bpy.ops.image.view_all(fit_view=True)
        except Exception:
            pass
    area.tag_redraw()
    return True


def image_editor_mouse_to_image_px(context, event) -> Optional[tuple]:
    """Convert mouse screen coordinates to image-space pixel coordinates.

    Uses ``region.view2d.region_to_view()`` to map from region-local pixel
    coordinates to the Image Editor's view coordinates (normalised ``[0, 1]``
    UV space), then multiplies by the image dimensions to obtain pixel
    coordinates.

    The function validates that:
    * The mouse is over an Image Editor area.
    * The Image Editor has an active image.
    * The mouse is within the WINDOW region bounds.
    * The resulting view coordinate is within ``[0.0, 1.0]`` (with a small
      epsilon for floating-point boundary hits).

    Args:
        context: The current Blender context.
        event: The Blender event whose ``mouse_x``/``mouse_y`` are used.

    Returns:
        ``(px, py)`` — pixel coordinates within the active image, with
        ``(0, 0)`` at the bottom-left corner, or ``None`` if any validation
        step fails.
    """
    area, region = find_area_and_region_under_mouse(
        context, event.mouse_x, event.mouse_y)
    if area is None or area.type != "IMAGE_EDITOR" or region is None:
        return None
    space = area.spaces.active
    if not space or not getattr(space, "image", None):
        return None
    img = space.image
    img_w, img_h = img.size
    if img_w <= 0 or img_h <= 0:
        return None
    rx = event.mouse_x - region.x
    ry = event.mouse_y - region.y
    if rx < 0 or ry < 0 or rx >= region.width or ry >= region.height:
        return None
    try:
        view_x, view_y = region.view2d.region_to_view(rx, ry)
    except Exception:
        return None
    if 0.0 <= view_x <= 1.000001 and 0.0 <= view_y <= 1.000001:
        px, py = view_x * img_w, view_y * img_h
    else:
        px, py = view_x, view_y
    return px, py


def picker_pixel_to_cell(props, px: float, py: float) -> Optional[tuple]:
    """Map picker-image pixel coordinates to a palette ``(cell_x, cell_y)``.

    The picker image has a half-cell border on all sides, so the palette grid
    starts at ``(border, border)`` in pixel space.  Cell coordinates are
    derived by integer division of the local pixel offset by the picker cell
    size.  The Y axis is flipped because Blender's image coordinate origin is
    at the bottom-left while the palette is laid out top-to-bottom in the
    DCP convention.

    Args:
        props: ``DCPProperties`` instance; provides grid dimensions and cell
            size.
        px: X pixel coordinate within the picker image.
        py: Y pixel coordinate within the picker image.

    Returns:
        ``(cell_x, cell_y)`` with ``cell_y = 0`` at the top of the palette,
        or ``None`` if ``(px, py)`` falls outside the palette area.
    """
    from .palette import get_picker_cell_size
    pcs     = get_picker_cell_size(props)
    border  = pcs // 2
    local_x = px - border
    local_y = py - border
    cols    = props.color_columns
    rows    = props.color_rows
    pw      = cols * pcs
    ph      = rows * pcs
    if local_x < 0 or local_y < 0 or local_x >= pw or local_y >= ph:
        return None
    cell_x = int(local_x // pcs)
    cell_y = rows - 1 - int(local_y // pcs)
    if not (0 <= cell_x < cols and 0 <= cell_y < rows):
        return None
    return cell_x, cell_y


def force_stop_pick_mode(context) -> None:
    """Unconditionally terminate the Image Editor pick mode.

    Clears the ``pick_from_image_editor`` flag on ``dcp_props``, resets the
    ``_is_running`` class attribute on
    :class:`~operators.picker.DCP_OT_PickFromImageEditor`, and schedules
    redraws for all relevant areas across all windows.

    This function is safe to call even when pick mode is not active — it is
    idempotent.  It is also called during addon registration to clear any
    stale state left over from a previous session or a script reload.

    Args:
        context: The current Blender context.  May be a background context
            with no window; all attribute accesses are guarded.
    """
    scene = getattr(context, "scene", None)
    if scene and hasattr(scene, "dcp_props"):
        scene.dcp_props.pick_from_image_editor = False
    try:
        from ..operators.picker import DCP_OT_PickFromImageEditor
        DCP_OT_PickFromImageEditor._is_running = False
    except Exception:
        pass
    wm = getattr(context, "window_manager", None)
    if wm:
        for window in wm.windows:
            screen = window.screen
            if screen:
                for area in screen.areas:
                    if area.type in {"VIEW_3D", "IMAGE_EDITOR", "PROPERTIES"}:
                        area.tag_redraw()
