# SPDX-License-Identifier: GPL-3.0-or-later
"""Material slot cleanup operator for Dynamic Color Palette.

Provides a single operator that removes unused material slots from the target
objects and optionally deletes orphaned material datablocks.

A slot is considered *unused* when no polygon in the mesh references its
index.  A material is deleted when it would become an orphan (zero users)
after slot removal and has no fake user set.

The operator works in both Edit Mode and Object Mode:
* **Edit Mode** — targets all objects currently in edit mode.
* **Object Mode** — targets all selected mesh objects; only enabled when at
  least one selected object has materials.

Because ``bpy.ops.object.material_slot_remove()`` requires Object Mode, the
operator temporarily switches out of Edit Mode, performs the cleanup, and
then switches back.
"""
from __future__ import annotations

import bpy
from bpy.types import Operator

from ..core.materials import cleanup_unused_material_slots


class DCP_OT_Cleanup(Operator):
    """Remove unused material slots and orphaned materials from selected objects.

    Targets all mesh objects in the current mode:
    * **Edit Mode** — all objects returned by ``context.objects_in_mode``.
    * **Object Mode** — all selected mesh objects.

    For each target object :func:`~core.materials.cleanup_unused_material_slots`
    is called with the object set as the active object (required by
    ``bpy.ops.object.material_slot_remove``).  If the caller is in Edit Mode
    the mode is restored to Edit after the cleanup loop completes.

    A single INFO report summarises the total number of slots removed and
    materials deleted.
    """

    bl_idname  = "dcp.cleanup_unused_slots"
    bl_label   = "Cleanup Unused Slots"
    bl_description = "Remove unused material slots and orphaned materials."
    bl_options = {"UNDO"}

    def execute(self, context) -> set:
        """Run the cleanup loop on all target objects.

        Args:
            context: The current Blender context.

        Returns:
            ``{"FINISHED"}`` after cleanup (even if nothing was removed),
            ``{"CANCELLED"}`` if no target objects are found.
        """
        old_mode = context.mode

        if old_mode == "EDIT_MESH":
            targets = [
                o for o in (getattr(context, "objects_in_mode", None)
                             or [context.active_object])
                if o and o.type == "MESH"
            ]
        else:
            targets = [o for o in context.selected_objects if o.type == "MESH"]

        if not targets:
            self.report({"WARNING"}, "No mesh objects to clean up.")
            return {"CANCELLED"}

        if old_mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        orig_active  = context.view_layer.objects.active
        total_slots  = 0
        total_mats   = 0
        try:
            for obj in targets:
                context.view_layer.objects.active = obj
                s, m = cleanup_unused_material_slots(obj)
                total_slots += s
                total_mats  += m
        finally:
            context.view_layer.objects.active = orig_active
            if old_mode != "OBJECT":
                bpy.ops.object.mode_set(mode="EDIT")

        self.report({"INFO"},
                    f"Cleanup: {total_slots} slot(s) removed, "
                    f"{total_mats} material(s) deleted.")
        return {"FINISHED"}
