# SPDX-License-Identifier: GPL-3.0-or-later
"""Addon preferences for Dynamic Color Palette.

DCP deliberately keeps its preferences panel minimal.  All user-configurable
state is stored on the scene (via :class:`~properties.DCPProperties`) so that
settings travel with the ``.blend`` file rather than being machine-global.

The preferences panel therefore only displays a single informational label
pointing the user to the correct location (the N-Panel in the 3D Viewport).
"""
from __future__ import annotations

from bpy.types import AddonPreferences


class DCPAddonPreferences(AddonPreferences):
    """Global addon preferences — informational stub only.

    No configurable properties are stored here.  All palette settings live in
    :class:`~properties.DCPProperties` on ``bpy.types.Scene`` so they are
    saved per blend file and participate in Blender's undo system.

    The panel content is intentionally kept minimal: a single label directs
    users to the actual configuration UI in the 3D Viewport N-Panel.
    """

    bl_idname = __package__

    def draw(self, context) -> None:
        """Draw the preferences panel content.

        Renders one informational label pointing to the DCP N-Panel.

        Args:
            context: The current Blender context (unused; required by the API).
        """
        self.layout.label(
            text="Configure in View3D \u2192 N-Panel \u2192 DCP \u2192 Configure\u2026",
            icon="INFO")
