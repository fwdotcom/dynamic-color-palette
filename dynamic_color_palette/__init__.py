# SPDX-License-Identifier: GPL-3.0-or-later
# See bl_info for license and copyright information.

"""Dynamic Color Palette – Blender addon entry point.

This module serves as the addon package root and is responsible for:

* Declaring ``bl_info`` (required by Blender's legacy addon system).
* Defining all **addon-wide constants** (name tokens, defaults) so every
  sub-module can import them from a single location without circular imports.
* Implementing ``register()`` and ``unregister()`` which Blender calls when
  the addon is enabled or disabled.

Constants
---------
VERSION : str
    Human-readable version string derived from ``bl_info["version"]``,
    e.g. ``"2.0.0"``.
PREFIX : str
    Short prefix prepended to every Blender data-block created by DCP
    (``"dcp_"``).  Keeps DCP assets clearly distinguishable from
    user-created data.
ALBEDO_IMAGE_NAME, MATERIAL_IMAGE_NAME, PICKER_IMAGE_NAME : str
    Fixed names for the three GPU-rendered images stored in
    ``bpy.data.images``.
MULTICOL_MAT_NAME : str
    Name of the shared Principled-BSDF material whose colour is driven
    entirely by UV lookup into the albedo texture.
SINGLECOL_MAT_PREFIX : str
    Prefix for per-cell baked singlecolour materials.
MAX_EMISSION_STRIPS : int
    Hard upper limit on the number of emission strength strips (5).
DEFAULT_* constants
    Built-in fallback values for every user-configurable property.
    Used by ``DCP_OT_ResetDefaults`` and as ``default=`` in property
    declarations.
"""

from __future__ import annotations

import bpy

bl_info = {
    "name":        "Dynamic Color Palette",
    "author":      "Frank Winter",
    "version":     (2, 0, 7),
    "blender":     (4, 2, 0),
    "location":    "View3D → N-Panel → DCP",
    "description": "Generate palette textures and assign colors via UV lookup",
    "category":    "Material",
    "doc_url":     "https://fwdotcom.itch.io/dynamic-color-palette",
}

# Human-readable version string derived from bl_info (e.g. "2.0.0").
VERSION              = ".".join(str(v) for v in bl_info["version"])

# Shared prefix for all DCP-owned Blender datablocks (images, materials).
PREFIX               = "dcp_"

# Names of the three generated images stored in bpy.data.images.
ALBEDO_IMAGE_NAME    = PREFIX + "albedo"    # RGBA colour + alpha lookup texture
MATERIAL_IMAGE_NAME  = PREFIX + "material"  # PBR channels: R=Roughness, G=Metalness, B=Emission
PICKER_IMAGE_NAME    = PREFIX + "picker"    # UI colour-picker shown in the Image Editor

# Names of DCP materials stored in bpy.data.materials.
MULTICOL_MAT_NAME    = PREFIX + "multicol"    # Shared multi-colour material (UV-driven)
SINGLECOL_MAT_PREFIX = PREFIX + "singlecol_"  # Prefix for baked single-colour materials

# Package name used as bl_idname for AddonPreferences and translation registration.
ADDON_ID             = __name__   # "dynamic_color_palette"

# Maximum number of emission strength strips per palette.
MAX_EMISSION_STRIPS  = 5

# Default palette grid dimensions.
DEFAULT_COLOR_COLUMNS      = 12    # Number of colour columns per quadrant
DEFAULT_COLOR_ROWS         = 12    # Number of colour rows per quadrant

# Default colour distribution parameters.
DEFAULT_PASTEL_SATURATION  = 0.25  # HSV saturation shift towards pastel (0 = off, 1 = full)
DEFAULT_SHADOW_VALUE       = 0.05  # HSV value reduction for the shadow row

# Default PBR values per quadrant (Solid / Metal / Emission).
DEFAULT_SOLID_ROUGHNESS    = 0.5
DEFAULT_SOLID_METALNESS    = 0.0
DEFAULT_METAL_ROUGHNESS    = 0.2
DEFAULT_METAL_METALNESS    = 1.0
DEFAULT_EMISSION_ROUGHNESS = 0.5
DEFAULT_EMISSION_METALNESS = 0.0

# Default emission settings.
DEFAULT_EMISSION_FACTOR    = 4.0              # Global multiplier applied in the shader
DEFAULT_EMISSION_STRIPS    = (0.3, 0.7, 1.0)  # Normalised strength values (one entry per strip)

# Minimum pixel height of a single palette cell (grows with strip count).
DEFAULT_CELL_SIZE_MIN      = 9

# Font size used for info-quadrant text rendering (points).
DEFAULT_FONT_SIZE          = 10

# Default export directory (empty = no auto-export).
DEFAULT_FILE_SAVE_PATH     = ""

# Default info-quadrant text lines shown in the generated texture.
DEFAULT_INFO_LINE_1        = "YOUR PROJECT NAME"
DEFAULT_INFO_LINE_2        = "(C) YOUR STUDIO"
DEFAULT_INFO_LINE_3        = "YOUR LICENSE"

# Default info-quadrant background and foreground colours as hex strings (no #).
DEFAULT_BG_HEX             = "1A1A1A"
DEFAULT_FG_HEX             = "CCCCCC"


def register() -> None:
    """Register all DCP classes and attach ``dcp_props`` to ``bpy.types.Scene``.

    Called automatically by Blender when the addon is enabled.  The function
    is idempotent: it unregisters any previously registered version of each
    class before re-registering, so reloading the addon with *F8* works
    without a Blender restart.

    Side effects:
        * All DCP operator, panel, property-group and preference classes are
          registered via ``bpy.utils.register_class()``.
        * ``bpy.types.Scene.dcp_props`` (a :class:`~properties.DCPProperties`
          PointerProperty) is attached to every scene in the blend file.
        * Any lingering pick-mode state from a previous session is cleared.
    """
    from bpy.props import PointerProperty

    from .properties  import DCPEmissionEntry, DCPMatEntry, DCPProperties
    from .preferences import DCPAddonPreferences
    from .operators.emission  import DCP_OT_AddEmissionStrip, DCP_OT_RemoveEmissionStrip
    from .operators.generate  import DCP_OT_GeneratePalette, DCP_OT_ResetDefaults, DCP_OT_ConfirmRegenerate
    from .operators.config    import DCP_OT_OpenConfig
    from .operators.picker    import DCP_OT_PickFromImageEditor, DCP_OT_StopPickFromImageEditor
    from .operators.assign    import DCP_OT_AssignMulticol, DCP_OT_AssignSinglecol
    from .operators.cleanup   import DCP_OT_Cleanup
    from .panels.main         import DCP_PT_Main

    _CLASSES = (
        DCPEmissionEntry,
        DCPMatEntry,
        DCPProperties,
        DCPAddonPreferences,
        DCP_OT_AddEmissionStrip,
        DCP_OT_RemoveEmissionStrip,
        DCP_OT_GeneratePalette,
        DCP_OT_ResetDefaults,
        DCP_OT_ConfirmRegenerate,
        DCP_OT_OpenConfig,
        DCP_OT_PickFromImageEditor,
        DCP_OT_StopPickFromImageEditor,
        DCP_OT_AssignMulticol,
        DCP_OT_AssignSinglecol,
        DCP_OT_Cleanup,
        DCP_PT_Main,
    )

    try:
        from .core.image_editor import force_stop_pick_mode
        force_stop_pick_mode(bpy.context)
    except Exception:
        pass

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

    for cls in _CLASSES:
        bpy.utils.register_class(cls)

    if hasattr(bpy.types.Scene, "dcp_props"):
        del bpy.types.Scene.dcp_props
    bpy.types.Scene.dcp_props = PointerProperty(type=DCPProperties)



    print("[DCP v2.0] Registered – open sidebar (N) → DCP tab.")




def unregister() -> None:
    """Unregister all DCP classes and clean up associated Blender state.

    Called automatically by Blender when the addon is disabled.

    Side effects:
        * ``bpy.types.Scene.dcp_props`` is removed so the property no longer
          appears on scenes.
        * The picker-preview ``PColl`` is freed to avoid a memory leak.
        * All DCP classes are unregistered via ``bpy.utils.unregister_class()``.
          Errors during unregistration are silently ignored so that a partial
          state cannot prevent the rest of the cleanup from running.
    """
    import bpy.utils.previews as _previews

    from .properties  import DCPEmissionEntry, DCPMatEntry, DCPProperties
    from .preferences import DCPAddonPreferences
    from .operators.emission  import DCP_OT_AddEmissionStrip, DCP_OT_RemoveEmissionStrip
    from .operators.generate  import DCP_OT_GeneratePalette, DCP_OT_ResetDefaults, DCP_OT_ConfirmRegenerate
    from .operators.config    import DCP_OT_OpenConfig, _unregister_wm_props
    from .operators.picker    import DCP_OT_PickFromImageEditor, DCP_OT_StopPickFromImageEditor
    from .operators.assign    import DCP_OT_AssignMulticol, DCP_OT_AssignSinglecol
    from .operators.cleanup   import DCP_OT_Cleanup
    from .panels.main         import DCP_PT_Main
    from .core.textures       import _get_picker_previews, _set_picker_previews

    _unregister_wm_props()

    _CLASSES = (
        DCPEmissionEntry,
        DCPMatEntry,
        DCPProperties,
        DCPAddonPreferences,
        DCP_OT_AddEmissionStrip,
        DCP_OT_RemoveEmissionStrip,
        DCP_OT_GeneratePalette,
        DCP_OT_ResetDefaults,
        DCP_OT_ConfirmRegenerate,
        DCP_OT_OpenConfig,
        DCP_OT_PickFromImageEditor,
        DCP_OT_StopPickFromImageEditor,
        DCP_OT_AssignMulticol,
        DCP_OT_AssignSinglecol,
        DCP_OT_Cleanup,
        DCP_PT_Main,
    )

    if hasattr(bpy.types.Scene, "dcp_props"):
        for scene in bpy.data.scenes:
            try:
                p = scene.dcp_props
                p.palette_generated      = False
                p.pick_from_image_editor = False
                p.multicol_mat           = None
                p.singlecol_mats.clear()
            except Exception:
                pass
        del bpy.types.Scene.dcp_props

    pp = _get_picker_previews()
    if pp is not None:
        _previews.remove(pp)
        _set_picker_previews(None)

    for cls in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
