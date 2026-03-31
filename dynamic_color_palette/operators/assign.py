# SPDX-License-Identifier: GPL-3.0-or-later
"""Material assignment operators for Dynamic Color Palette.

Provides two operators for applying palette colours to mesh objects:

DCP_OT_AssignMulticol
    Assigns the shared ``dcp_multicol`` material and sets UV coordinates so
    the palette lookup texture reads the correct colour.  Supports both Edit
    Mode (selected faces only) and Object Mode (all faces of selected objects).

DCP_OT_AssignSinglecol
    Creates (or reuses from cache) a baked single-colour material for the
    current panel colour and assigns it to the selection.  Supports both Edit
    Mode (selected faces) and Object Mode (slot 0 of selected objects).

Both operators accept a ``from_picker`` flag.  When ``True`` the automatic
pick-mode termination that would normally follow a successful assign is
suppressed, allowing the picker modal to keep running after an assignment.

Slot management strategy
------------------------
Both operators place the DCP material at **slot 0** of the mesh.  In Object
Mode all polygon ``material_index`` values are set to ``0`` after assignment.
Existing slots are shifted up by one if the new material is not already
present, preserving all other material assignments.
"""
from __future__ import annotations

import bpy
from bpy.types import Operator

from bpy.props import BoolProperty

from ..core.palette import cell_to_albedo_uv, get_uv_islands_by_connectivity, place_islands_at_uv
from ..core.materials import (
    get_multicol_mat, get_singlecol_mat, cache_singlecol_mat,
    build_singlecol_material, ensure_material_slot,
)
from ..core.image_editor import force_stop_pick_mode
from .. import PREFIX


class DCP_OT_AssignMulticol(Operator):
    """Assign ``dcp_multicol`` and set UV coordinates to the selected palette cell.

    **Edit Mode**: Iterates over all objects in edit mode, groups selected
    faces into UV islands by edge connectivity, and moves every loop UV in
    each island to the target UV point derived from the current palette
    selection.  Objects without an active UV layer are skipped and reported.

    **Object Mode**: For every selected mesh object, places the material at
    slot 0, moves all existing slots up by one, and sets all polygon UV
    coordinates to the target point.
    """

    bl_idname     = "dcp.assign_multicol"
    bl_label      = "Assign Multicolor Material"
    bl_description = "Place UV islands at the selected palette cell and assign dcp_multicol"
    bl_options    = {"REGISTER", "UNDO"}

    from_picker: BoolProperty(
        default=False,
        options={"SKIP_SAVE", "HIDDEN"},
        description="Set by the picker modal to suppress automatic pick-mode "
                    "termination after a successful assign.",
    )

    def execute(self, context) -> set:
        """Dispatch to Edit Mode or Object Mode assignment logic.

        Args:
            context: The current Blender context.

        Returns:
            ``{"FINISHED"}`` on success, ``{"CANCELLED"}`` if a precondition
            is not met.
        """
        import bmesh

        props    = context.scene.dcp_props
        quadrant = int(props.sel_quadrant)
        cell_x   = props.sel_cell_x
        cell_y   = props.sel_cell_y
        emission = props.sel_emission

        multicol_mat = get_multicol_mat(context)
        if multicol_mat is None:
            self.report({"ERROR"},
                        f"'{PREFIX}multicol' not found. Run Generate Palette first.")
            return {"CANCELLED"}

        target_uv = cell_to_albedo_uv(props, quadrant, cell_x, cell_y, emission)
        if target_uv is None:
            self.report({"ERROR"},
                        f"'{PREFIX}albedo' not found. Run Generate Palette first.")
            return {"CANCELLED"}

        mode = context.mode

        if mode == "EDIT_MESH":
            result = self._assign_edit(context, props, multicol_mat,
                                       target_uv, quadrant, cell_x, cell_y)
        elif mode == "OBJECT":
            result = self._assign_object(context, multicol_mat, target_uv)
        else:
            self.report({"WARNING"}, "Switch to Edit or Object Mode.")
            return {"CANCELLED"}

        if result == {"FINISHED"} and not self.from_picker and props.pick_from_image_editor:
            force_stop_pick_mode(context)
        return result

    def _assign_edit(self, context, props, mat, target_uv,
                     quadrant, cell_x, cell_y) -> set:
        """Assign in Edit Mode — selected faces of all objects in edit mode.

        For each object in edit mode:
        1. Ensures the material is present in the mesh's material list.
        2. Groups selected faces into UV islands by edge connectivity.
        3. Moves all loop UVs in each island to *target_uv*.
        4. Sets the ``material_index`` of each selected face to the material's slot.

        Args:
            context: The current Blender context.
            props: ``DCPProperties`` instance from the active scene.
            mat: The ``dcp_multicol`` material datablock.
            target_uv: ``(u, v)`` palette UV coordinates.
            quadrant: Active quadrant index (unused here; kept for symmetry).
            cell_x: Active column index (unused here; kept for symmetry).
            cell_y: Active row index (unused here; kept for symmetry).

        Returns:
            ``{"FINISHED"}`` if at least one face was assigned,
            ``{"CANCELLED"}`` if no faces were selected on any object.
        """
        import bmesh

        obj          = context.active_object
        edit_objects = getattr(context, "objects_in_mode", None) or [obj]
        total_faces  = 0
        total_isl    = 0
        no_uv        = []

        for edit_obj in edit_objects:
            if edit_obj.type != "MESH":
                continue

            # Create a UV layer if the mesh has none yet.
            uv_is_new  = not edit_obj.data.uv_layers.active
            if uv_is_new:
                edit_obj.data.uv_layers.new(name="UVMap")

            mat_is_new = mat.name not in [m.name for m in edit_obj.data.materials if m]
            mat_idx    = ensure_material_slot(edit_obj.data, mat)

            bm       = bmesh.from_edit_mesh(edit_obj.data)
            uv_layer = bm.loops.layers.uv.active
            if not uv_layer:
                no_uv.append(edit_obj.name)
                continue

            sel = [f for f in bm.faces if f.select]
            if not sel:
                continue

            # Initialise unset faces to white (solid, col 0, last row) so they
            # show a defined colour instead of sampling random palette cells.
            # Covers two cases:
            #   • UV layer just created → all non-selected faces start at (0,0)
            #   • Material newly added → unselected faces implicitly reference
            #     the new slot (material_index == mat_idx)
            if mat_is_new or uv_is_new:
                default_uv = cell_to_albedo_uv(
                    props, 0, 0, props.color_rows - 1, 0)
                if default_uv:
                    to_init = [
                        f for f in bm.faces if not f.select
                        and (uv_is_new or f.material_index == mat_idx)
                    ]
                    if to_init:
                        place_islands_at_uv(bm, uv_layer, [to_init], default_uv)

            islands = get_uv_islands_by_connectivity(bm, sel)
            place_islands_at_uv(bm, uv_layer, islands, target_uv)
            for face in sel:
                face.material_index = mat_idx
            bmesh.update_edit_mesh(edit_obj.data)

            total_faces += len(sel)
            total_isl   += len(islands)

        if no_uv:
            self.report({"WARNING"},
                        "No UV layer on: " + ", ".join(no_uv[:3]) +
                        (f" \u2026 and {len(no_uv)-3} more" if len(no_uv) > 3 else ""))
        if total_faces == 0:
            self.report({"WARNING"}, "No faces selected.")
            return {"CANCELLED"}

        self.report({"INFO"},
                    f"{total_isl} island(s) / {total_faces} face(s) "
                    f"\u2192 UV ({target_uv[0]:.3f}, {target_uv[1]:.3f})")
        return {"FINISHED"}

    def _assign_object(self, context, mat, target_uv) -> set:
        """Assign in Object Mode — all faces of every selected mesh object.

        For each selected object:
        1. Ensures ``mat`` is at slot 0 (inserting/moving as needed).
        2. Sets all polygon ``material_index`` values to ``0``.
        3. Sets all UV loop coordinates to *target_uv*.

        Args:
            context: The current Blender context.
            mat: The ``dcp_multicol`` material datablock.
            target_uv: ``(u, v)`` palette UV coordinates.

        Returns:
            ``{"FINISHED"}`` if at least one object was processed,
            ``{"CANCELLED"}`` if no mesh objects are selected.
        """
        import bmesh as _bm

        sel = [o for o in context.selected_objects if o.type == "MESH"]
        if not sel:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        no_uv = []
        for obj in sel:
            mesh = obj.data
            if len(mesh.materials) == 0:
                mesh.materials.append(mat)
            else:
                existing_names = [m.name for m in mesh.materials if m]
                if mat.name in existing_names:
                    old_idx = existing_names.index(mat.name)
                    if old_idx != 0:
                        prev = list(mesh.materials)
                        mesh.materials[0] = mat
                        j = 1
                        for m in prev:
                            if m and m.name != mat.name:
                                mesh.materials[j] = m
                                j += 1
                else:
                    mesh.materials.append(mat)
                    for poly in mesh.polygons:
                        poly.material_index += 1
                    prev = [mesh.materials[i] for i in range(len(mesh.materials) - 1)]
                    mesh.materials[0] = mat
                    for i, m in enumerate(prev):
                        mesh.materials[i + 1] = m
            # All faces use slot 0 (multicol drives color via UV, not per-slot).
            for poly in mesh.polygons:
                poly.material_index = 0

            if not mesh.uv_layers.active:
                mesh.uv_layers.new(name="UVMap")

            bm       = _bm.new()
            bm.from_mesh(mesh)
            uv_layer = bm.loops.layers.uv.active
            if uv_layer:
                all_faces = list(bm.faces)
                place_islands_at_uv(bm, uv_layer, [all_faces], target_uv)
                bm.to_mesh(mesh)
            else:
                no_uv.append(obj.name)
            bm.free()
            mesh.update()

        if no_uv:
            self.report({"WARNING"},
                        "No UV layer on: " + ", ".join(no_uv[:3]) +
                        (f" \u2026 and {len(no_uv)-3} more" if len(no_uv) > 3 else ""))
        n = len(sel)
        self.report({"INFO"}, f"Multicol assigned to {n} object(s).")
        return {"FINISHED"}


class DCP_OT_AssignSinglecol(Operator):
    """Create (or reuse) a baked single-colour material and assign it.

    Looks up the material for the current panel colour in the scene's singlecol
    cache (``DCPProperties.singlecol_mats``).  If no cached material is found
    a new one is built via
    :func:`~core.materials.build_singlecol_material` and stored in the cache.

    **Edit Mode**: Assigns the material to selected faces only; slot index is
    determined by :func:`~core.materials.ensure_material_slot`.

    **Object Mode**: Places the material at slot 0 and sets all polygon
    ``material_index`` values to ``0``, overwriting any previous assignment.
    """

    bl_idname      = "dcp.assign_singlecol"
    bl_label       = "Assign Singlecolor Material"
    bl_description = "Create or reuse a baked flat-color material for the selected palette cell"
    bl_options     = {"REGISTER", "UNDO"}

    from_picker: BoolProperty(
        default=False,
        options={"SKIP_SAVE", "HIDDEN"},
        description="Set by the picker modal to suppress automatic pick-mode "
                    "termination after a successful assign.",
    )

    def execute(self, context) -> set:
        """Resolve the material and dispatch to mode-specific assignment.

        Args:
            context: The current Blender context.

        Returns:
            ``{"FINISHED"}`` on success, ``{"CANCELLED"}`` if no selection
            exists or the mode is unsupported.
        """
        props    = context.scene.dcp_props
        quadrant = int(props.sel_quadrant)
        cell_x   = props.sel_cell_x
        cell_y   = props.sel_cell_y
        emission = props.sel_emission

        mat = get_singlecol_mat(context, quadrant, cell_x, cell_y, emission)
        if mat is None:
            mat = build_singlecol_material(props, quadrant, cell_x,
                                           cell_y, emission)
            cache_singlecol_mat(context, quadrant, cell_x, cell_y,
                                emission, mat)

        mode = context.mode
        if mode == "EDIT_MESH":
            result = self._assign_edit(context, mat)
        elif mode == "OBJECT":
            result = self._assign_object(context, mat)
        else:
            self.report({"WARNING"}, "Switch to Edit or Object Mode.")
            return {"CANCELLED"}

        if result == {"FINISHED"} and not self.from_picker and props.pick_from_image_editor:
            force_stop_pick_mode(context)
        return result

    def _assign_edit(self, context, mat) -> set:
        """Assign the singlecol material to selected faces in Edit Mode.

        Iterates over all objects in edit mode, ensures the material slot
        exists, and sets ``material_index`` on every selected face.

        Args:
            context: The current Blender context.
            mat: The singlecol material datablock to assign.

        Returns:
            ``{"FINISHED"}`` if at least one face was assigned,
            ``{"CANCELLED"}`` if no faces were selected.
        """
        import bmesh

        obj          = context.active_object
        edit_objects = getattr(context, "objects_in_mode", None) or [obj]
        total        = 0

        for edit_obj in edit_objects:
            if edit_obj.type != "MESH":
                continue
            mat_idx = ensure_material_slot(edit_obj.data, mat)
            bm      = bmesh.from_edit_mesh(edit_obj.data)
            sel     = [f for f in bm.faces if f.select]
            if not sel:
                continue
            for face in sel:
                face.material_index = mat_idx
            bmesh.update_edit_mesh(edit_obj.data)
            total += len(sel)

        if total == 0:
            self.report({"WARNING"}, "No faces selected.")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Singlecol assigned to {total} face(s).")
        return {"FINISHED"}

    def _assign_object(self, context, mat) -> set:
        """Assign the singlecol material to all faces of selected objects.

        Places *mat* at slot 0 of each selected mesh object's material list
        and sets all polygon ``material_index`` values to ``0``.

        Args:
            context: The current Blender context.
            mat: The singlecol material datablock to assign.

        Returns:
            ``{"FINISHED"}`` if at least one object was processed,
            ``{"CANCELLED"}`` if no mesh objects are selected.
        """
        sel = [o for o in context.selected_objects if o.type == "MESH"]
        if not sel:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}
        for obj in sel:
            mesh = obj.data
            if len(mesh.materials) == 0:
                mesh.materials.append(mat)
            else:
                existing_names = [m.name for m in mesh.materials if m]
                if mat.name in existing_names:
                    # Already present — move it to slot 0 if needed.
                    old_idx = existing_names.index(mat.name)
                    if old_idx != 0:
                        # Reorder: put mat first, keep all others in order.
                        prev = list(mesh.materials)
                        mesh.materials[0] = mat
                        j = 1
                        for m in prev:
                            if m and m.name != mat.name:
                                mesh.materials[j] = m
                                j += 1
                        # Update poly indices: old_idx → 0, others shift up by 1.
                        for poly in mesh.polygons:
                            if poly.material_index == old_idx:
                                poly.material_index = 0
                            elif poly.material_index < old_idx:
                                poly.material_index += 1
                else:
                    # Insert at slot 0: append, shift poly indices, reorder slots.
                    mesh.materials.append(mat)
                    for poly in mesh.polygons:
                        poly.material_index += 1
                    prev = [mesh.materials[i] for i in range(len(mesh.materials) - 1)]
                    mesh.materials[0] = mat
                    for i, m in enumerate(prev):
                        mesh.materials[i + 1] = m
            # Assign ALL faces to slot 0.
            for poly in mesh.polygons:
                poly.material_index = 0
            mesh.update()
        self.report({"INFO"}, f"Singlecol assigned to {len(sel)} object(s).")
        return {"FINISHED"}
