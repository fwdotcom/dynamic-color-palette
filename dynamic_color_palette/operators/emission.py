# SPDX-License-Identifier: GPL-3.0-or-later
"""Emission strip management operators.

Provides two small operators for adding and removing emission strength strips
from ``DCPProperties.emission_strengths``.  Both operators invalidate the
emission layout cache after modifying the collection so the next generation
pass uses fresh geometry.

Constraints
-----------
* Minimum 1 strip — removing the last strip is refused.
* Maximum :data:`~__init__.MAX_EMISSION_STRIPS` strips (5) — adding beyond
  the limit is refused.
* When the collection is reduced to exactly one strip its value is normalised
  to ``1.0`` to avoid a degenerate single-strip-at-zero state.
"""
from __future__ import annotations

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from .. import MAX_EMISSION_STRIPS
from ..core.palette import _invalidate_emission_cache


class DCP_OT_AddEmissionStrip(Operator):
    """Add one emission strength strip to the collection.

    Appends a new :class:`~properties.DCPEmissionEntry` with ``value = 1.0``
    to ``DCPProperties.emission_strengths`` and invalidates the emission
    layout cache.  Refuses to add if the collection already contains
    :data:`~__init__.MAX_EMISSION_STRIPS` entries.
    """

    bl_idname = "dcp.add_emission_strip"
    bl_label  = "Add Strip"
    bl_description = "Add an emission strip (max 5)."

    def execute(self, context) -> set:
        """Append a new strip or report the limit.

        Args:
            context: The current Blender context.

        Returns:
            ``{"FINISHED"}`` if the strip was added, ``{"CANCELLED"}`` if
            the maximum number of strips has already been reached.
        """
        props = context.scene.dcp_props
        if len(props.emission_strengths) >= MAX_EMISSION_STRIPS:
            self.report({"WARNING"}, f"Maximum {MAX_EMISSION_STRIPS} strips.")
            return {"CANCELLED"}
        props.emission_strengths.add().value = 1.0
        _invalidate_emission_cache()
        return {"FINISHED"}


class DCP_OT_RemoveEmissionStrip(Operator):
    """Remove one emission strength strip from the collection.

    Removes the strip at ``index`` (or the last strip if *index* is out of
    range).  Refuses to remove if only one strip remains.  When the
    collection is reduced to a single strip that strip's value is reset to
    ``1.0``.  The emission layout cache is invalidated after the change.
    """

    bl_idname = "dcp.remove_emission_strip"
    bl_label  = "Remove Strip"
    bl_description = "Remove the last emission strip (min 1)."

    index: IntProperty(
        default=-1,
        description="Index of the strip to remove; -1 removes the last strip.",
    )

    def execute(self, context) -> set:
        """Remove the strip at *index* or report the minimum limit.

        Args:
            context: The current Blender context.

        Returns:
            ``{"FINISHED"}`` if the strip was removed, ``{"CANCELLED"}`` if
            only one strip remains.
        """
        props = context.scene.dcp_props
        n     = len(props.emission_strengths)
        if n <= 1:
            self.report({"WARNING"}, "At least one strip required.")
            return {"CANCELLED"}
        idx = self.index if 0 <= self.index < n else n - 1
        props.emission_strengths.remove(idx)
        if len(props.emission_strengths) == 1:
            props.emission_strengths[0].value = 1.0
        _invalidate_emission_cache()
        return {"FINISHED"}
