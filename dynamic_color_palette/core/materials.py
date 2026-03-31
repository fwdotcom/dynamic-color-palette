# SPDX-License-Identifier: GPL-3.0-or-later
"""Material builders and cache accessors for Dynamic Color Palette.

This module provides two families of functions:

**Material builders**
    :func:`build_or_update_multicol_material` — create or rebuild the shared
    ``dcp_multicol`` Principled-BSDF node-tree that reads colour and PBR
    values from the two DCP textures via UV lookup.

    :func:`build_singlecol_material` — create a baked single-colour
    Principled-BSDF material for a specific palette cell.  These materials
    carry the colour directly as node default values and do not reference any
    DCP texture.

**Material cache accessors**
    :func:`get_multicol_mat`, :func:`get_singlecol_mat`,
    :func:`cache_singlecol_mat` — read and write the pointer-based singlecol
    cache stored in ``DCPProperties.singlecol_mats``.

**Material slot helpers**
    :func:`ensure_material_slot`, :func:`cleanup_unused_material_slots` —
    low-level mesh-material slot management used by the assign and cleanup
    operators.

Note on the multicol node tree layout (left → right):
    ``TexImage(albedo) ──▶ BSDF.Base Color``
    ``TexImage(albedo) ──▶ BSDF.Emission Color``
    ``TexImage(matmap) ──▶ SeparateColor ──▶ BSDF.Roughness  (R channel)``
                                          ``──▶ BSDF.Metallic   (G channel)``
                                          ``──▶ Math(Multiply) ──▶ BSDF.Emission Strength``
                                                (multiplied by emission_factor)
"""
from __future__ import annotations

import bpy

from .. import PREFIX
from .palette import cell_color_from_props, pbr_from_quadrant


def build_or_update_multicol_material(
    props,
    img_albedo: bpy.types.Image,
    img_matmap: bpy.types.Image,
) -> bpy.types.Material:
    """Create or fully rebuild the ``dcp_multicol`` node-tree material.

    If a material named ``dcp_multicol`` already exists in ``bpy.data.materials``
    its datablock is reused (so objects that reference it keep their assignment),
    but its entire node tree is cleared and rebuilt from scratch.  This
    guarantees a clean state after every regeneration without breaking object
    → material links.

    Node tree overview::

        TexImage(albedo, Closest) ──► BSDF.Base Color
                                  ──► BSDF.Emission Color
        TexImage(matmap, Non-Color, Closest)
            └─► SeparateColor ──► [R] BSDF.Roughness
                               ──► [G] BSDF.Metallic
                               ──► [B] Math(×emission_factor) ──► BSDF.Emission Strength
        BSDF ──► Output

    Args:
        props: ``DCPProperties`` instance; used only to read
            ``emission_factor`` for the Multiply node.
        img_albedo: The ``dcp_albedo`` image datablock produced by
            :func:`~textures._render_sheet`.
        img_matmap: The ``dcp_material`` image datablock produced by
            :func:`~textures._render_sheet`.

    Returns:
        The created or updated ``bpy.types.Material`` datablock.
    """
    name = PREFIX + "multicol"
    mat  = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name=name)

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out    = nodes.new("ShaderNodeOutputMaterial")
    bsdf   = nodes.new("ShaderNodeBsdfPrincipled")
    albedo = nodes.new("ShaderNodeTexImage")
    matmap = nodes.new("ShaderNodeTexImage")
    sep    = nodes.new("ShaderNodeSeparateColor")
    mul    = nodes.new("ShaderNodeMath")

    albedo.image                          = img_albedo
    albedo.image.colorspace_settings.name = "Non-Color"
    albedo.interpolation                  = "Closest"

    matmap.image                          = img_matmap
    matmap.image.colorspace_settings.name = "Non-Color"
    matmap.interpolation                  = "Closest"

    mul.operation               = "MULTIPLY"
    mul.inputs[1].default_value = props.emission_factor

    albedo.location = (-600,  200)
    matmap.location = (-600, -200)
    sep.location    = (-250, -200)
    mul.location    = (-250,  -50)
    bsdf.location   = (  50,    0)
    out.location    = ( 400,    0)

    links.new(albedo.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(albedo.outputs["Color"], bsdf.inputs["Emission Color"])
    links.new(matmap.outputs["Color"], sep.inputs["Color"])
    links.new(sep.outputs["Red"],      bsdf.inputs["Roughness"])
    links.new(sep.outputs["Green"],    bsdf.inputs["Metallic"])
    links.new(sep.outputs["Blue"],     mul.inputs[0])
    links.new(mul.outputs[0],          bsdf.inputs["Emission Strength"])
    links.new(bsdf.outputs["BSDF"],    out.inputs["Surface"])

    print(f"[DCP] '{name}' created/updated.")
    return mat


def _singlecol_name(quadrant: int, cell_x: int, cell_y: int, emission: int) -> str:
    """Construct the deterministic datablock name for a singlecol material.

    The name encodes the full palette address so that the material can be
    identified in a blend file even if the DCP cache is lost.

    Format:
        ``dcp_singlecol_<q>_<x>_<y>`` for Solid/Metal quadrants, or
        ``dcp_singlecol_em_<x>_<y>_<strip>`` for Emission.

    Args:
        quadrant: ``0`` = Solid (``"so"``), ``1`` = Metal (``"me"``),
            ``2`` = Emission (``"em"``).
        cell_x: Column index.
        cell_y: Row index.
        emission: Strip index (appended only for the emission quadrant).

    Returns:
        The material datablock name string.
    """
    qmap = {0: "so", 1: "me", 2: "em"}
    q    = qmap.get(quadrant, str(quadrant))
    if quadrant == 2:
        return f"{PREFIX}singlecol_{q}_{cell_x}_{cell_y}_{emission}"
    return f"{PREFIX}singlecol_{q}_{cell_x}_{cell_y}"


def build_singlecol_material(
    props,
    quadrant: int, cell_x: int, cell_y: int, emission: int,
) -> bpy.types.Material:
    """Create a baked single-colour Principled-BSDF material for one palette cell.

    All PBR values (base colour, roughness, metalness, emission strength) are
    baked directly into the BSDF node's default inputs — no texture lookup is
    required at render time.  The emission strength is the normalised strip
    value multiplied by ``props.emission_factor``.

    Unlike the multicol material, a new datablock is always created (never
    reused).  When the palette is regenerated the old datablocks remain in
    the blend file as orphans (zero users, no fake user) and can be purged
    manually or by Blender's "Purge All" operator.

    Args:
        props: ``DCPProperties`` instance; provides palette colours and PBR
            values.
        quadrant: ``0`` = Solid, ``1`` = Metal, ``2`` = Emission.
        cell_x: Column index.
        cell_y: Row index.
        emission: Strip index (only meaningful for quadrant 2).

    Returns:
        The newly created ``bpy.types.Material`` datablock.
    """
    name                     = _singlecol_name(quadrant, cell_x, cell_y, emission)
    color                    = cell_color_from_props(props, cell_x, cell_y)
    roughness, metalness, em = pbr_from_quadrant(props, quadrant, emission)

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out  = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    out.location  = (300, 0)
    bsdf.location = (  0, 0)

    bsdf.inputs["Base Color"].default_value        = color
    bsdf.inputs["Emission Color"].default_value    = color
    bsdf.inputs["Roughness"].default_value         = roughness
    bsdf.inputs["Metallic"].default_value          = metalness
    bsdf.inputs["Emission Strength"].default_value = em * props.emission_factor
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    print(f"[DCP] Singlecol '{name}' created.")
    return mat


# ============================================================================
# MATERIAL CACHE ACCESSORS
# ============================================================================

def get_multicol_mat(context) -> bpy.types.Material | None:
    """Return the cached multicol material if it still exists in the blend file.

    Validates the pointer by checking ``bpy.data.materials`` — a stale
    pointer (material deleted outside DCP) returns ``None``.

    Args:
        context: The current Blender context; used to access
            ``context.scene.dcp_props``.

    Returns:
        The ``dcp_multicol`` material, or ``None`` if it is not found.
    """
    mat = context.scene.dcp_props.multicol_mat
    return mat if (mat and mat.name in bpy.data.materials) else None


def get_singlecol_mat(context, quadrant: int, cell_x: int,
                      cell_y: int, emission: int) -> bpy.types.Material | None:
    """Look up a cached singlecol material by palette address.

    Iterates over ``DCPProperties.singlecol_mats`` and returns the first
    entry whose ``(quadrant, cell_x, cell_y, emission)`` matches.  Validates
    the pointer before returning.

    Args:
        context: The current Blender context.
        quadrant: ``0`` = Solid, ``1`` = Metal, ``2`` = Emission.
        cell_x: Column index.
        cell_y: Row index.
        emission: Strip index.

    Returns:
        The cached ``bpy.types.Material``, or ``None`` if no valid entry
        exists for the given address.
    """
    for entry in context.scene.dcp_props.singlecol_mats:
        if (entry.quadrant == quadrant and entry.cell_x == cell_x and
                entry.cell_y == cell_y and entry.emission == emission):
            mat = entry.mat
            return mat if (mat and mat.name in bpy.data.materials) else None
    return None


def cache_singlecol_mat(context, quadrant: int, cell_x: int,
                        cell_y: int, emission: int,
                        mat: bpy.types.Material) -> None:
    """Insert or update a singlecol material pointer in the scene cache.

    If an entry for the given palette address already exists its ``mat``
    pointer is updated in place.  Otherwise a new entry is appended to
    ``DCPProperties.singlecol_mats``.

    Args:
        context: The current Blender context.
        quadrant: ``0`` = Solid, ``1`` = Metal, ``2`` = Emission.
        cell_x: Column index.
        cell_y: Row index.
        emission: Strip index.
        mat: The material datablock to cache.
    """
    props = context.scene.dcp_props
    for entry in props.singlecol_mats:
        if (entry.quadrant == quadrant and entry.cell_x == cell_x and
                entry.cell_y == cell_y and entry.emission == emission):
            entry.mat = mat
            return
    entry          = props.singlecol_mats.add()
    entry.quadrant = quadrant
    entry.cell_x   = cell_x
    entry.cell_y   = cell_y
    entry.emission = emission
    entry.mat      = mat


# ============================================================================
# MATERIAL SLOT HELPERS
# ============================================================================

def ensure_material_slot(mesh: bpy.types.Mesh, mat: bpy.types.Material) -> int:
    """Return the slot index of *mat* in *mesh*, appending it if absent.

    Args:
        mesh: The mesh data-block whose material list is searched.
        mat: The material to locate or append.

    Returns:
        The zero-based slot index of *mat*.

    Raises:
        RuntimeError: If *mat* cannot be found after being appended, which
            should not happen under normal Blender operation.
    """
    names = [m.name for m in mesh.materials if m]
    if mat.name not in names:
        mesh.materials.append(mat)
    for i, m in enumerate(mesh.materials):
        if m and m.name == mat.name:
            return i
    raise RuntimeError(f"Failed to locate slot for '{mat.name}'")


def cleanup_unused_material_slots(obj: bpy.types.Object) -> tuple[int, int]:
    """Remove unused material slots and delete orphaned materials from *obj*.

    A slot is "unused" if no polygon in the mesh references its index.  A
    material is deleted only when it would become an orphan after slot removal
    (``users == 0`` after the slot is gone) **and** has no fake user.

    This function must be called with *obj* set as the active object (via
    ``context.view_layer.objects.active``) and with Blender in Object Mode,
    because ``bpy.ops.object.material_slot_remove()`` requires both conditions.

    Args:
        obj: The mesh object to clean.  Non-mesh objects are silently skipped.

    Returns:
        ``(slots_removed, materials_deleted)`` — counts of removed slots
        and deleted material datablocks respectively.
    """
    if not obj or obj.type != "MESH":
        return 0, 0
    mesh       = obj.data
    used       = {p.material_index for p in mesh.polygons}
    removable  = [i for i in range(len(mesh.materials)) if i not in used]
    slots_rem  = 0
    mats_del   = 0
    for slot_idx in reversed(removable):
        mat          = mesh.materials[slot_idx]
        cand         = mat.name if mat else None
        should_del   = bool(mat and mat.users == 1 and not mat.use_fake_user)
        obj.active_material_index = slot_idx
        bpy.ops.object.material_slot_remove()
        slots_rem += 1
        if should_del and cand:
            orphan = bpy.data.materials.get(cand)
            if orphan and orphan.users == 0:
                bpy.data.materials.remove(orphan)
                mats_del += 1
    return slots_rem, mats_del
