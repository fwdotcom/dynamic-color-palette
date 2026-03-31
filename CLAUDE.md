# Dynamic Color Palette — Claude Context

**v2.0 · Frank Winter · GPLv3 · © 2026**

---

## Was ist DCP?

Blender-Addon zum schnellen Einfärben von 3D-Meshes für Game-Engine-Workflows (primär Godot 4).
Generiert zwei UV-Lookup-Texturen (`dcp_albedo`, `dcp_material`) und ein Principled-BSDF-Material
(`dcp_multicol`), das per UV-Koordinate Farbe + PBR-Werte aus der Textur liest.

**Multicol-Workflow:** Alle Faces am selben Material, Farbe über UV-Koordinate gesteuert →
minimale Drawcalls in der Game Engine.

---

## Aktueller Entwicklungsstand

- **v1.2** im Repo (main): Einzelnes `.py`-Script, Alt+P, Konstanten-Konfiguration
- **v2.0** im Repo (dev): Vollständige Addon-Struktur implementiert, `dynamic_color_palette.zip` paketiert

---

## Addon-Zielstruktur

```
dynamic_color_palette/
    __init__.py          ← bl_info, VERSION, PREFIX, Name-Konstanten, register(), unregister()
    properties.py        ← DCPProperties, DCPEmissionEntry, DCPMatEntry
    preferences.py       ← DCPAddonPreferences (leerer Stub, nur Hinweis-Label)
    operators/
        generate.py      ← DCP_OT_GeneratePalette, DCP_OT_ConfirmRegenerate, DCP_OT_ResetDefaults
        config.py        ← DCP_OT_OpenConfig (invoke_props_dialog, Palette-Konfiguration)
        assign.py        ← DCP_OT_AssignMulticol, DCP_OT_AssignSinglecol
        picker.py        ← DCP_OT_PickFromImageEditor, DCP_OT_StopPickFromImageEditor
        cleanup.py       ← DCP_OT_Cleanup
        emission.py      ← DCP_OT_AddEmissionStrip, DCP_OT_RemoveEmissionStrip
    panels/
        main.py          ← DCP_PT_Main (N-Panel, 3D View)
    core/
        palette.py       ← Farbberechnung, UV-Helpers
        textures.py      ← GPU-Rendering, Texture-Erzeugung
        materials.py     ← Multicol- und Singlecol-Material-Builder
        image_editor.py  ← Picker-Helpers, region_to_view etc.
```

---

## bl_info

```python
bl_info = {
    "name":        "Dynamic Color Palette",
    "author":      "Frank Winter",
    "version":     (2, 0, 0),
    "blender":     (4, 2, 0),
    "location":    "View3D → N-Panel → DCP",
    "description": "Generate palette textures and assign colors via UV lookup",
    "category":    "Material",
    "doc_url":     "https://fwdotcom.itch.io/dynamic-color-palette",
}
```

`blender_manifest.toml` (Blender 4.2+ Extension System): `blender_version_min = "4.2.0"`, `license = ["SPDX:GPL-3.0-or-later"]`

---

## Preferences-Architektur

| Wo | Was | Gespeichert in |
|---|---|---|
| **Addon Preferences** | Nur Hinweis-Label (kein eigener State) | — |
| **N-Panel 3D View / Modal** | Alles: Palette, PBR, Emission, Export, Info-Quadrant | `DCPProperties` auf Scene (pro .blend) |

### DCPAddonPreferences (global)

Leerer Stub — zeigt nur einen Hinweis auf das DCP-Panel. Keine eigenen Properties mehr.

```python
class DCPAddonPreferences(AddonPreferences):
    bl_idname = __package__
    def draw(self, context):
        self.layout.label(text="Configure in View3D → N-Panel → DCP → Configure…")
```

### DCPProperties auf Scene (pro .blend, N-Panel)

```python
class DCPProperties(PropertyGroup):

    # Palette-Konfiguration
    color_columns      : IntProperty(default=12, min=1, max=32)
    color_rows         : IntProperty(default=12, min=2, max=32)
    pastel_saturation  : FloatProperty(default=0.25, min=0.0, max=1.0)
    shadow_value       : FloatProperty(default=0.05, min=0.0, max=1.0)

    solid_roughness    : FloatProperty(default=0.5)
    solid_metalness    : FloatProperty(default=0.0)
    metal_roughness    : FloatProperty(default=0.2)
    metal_metalness    : FloatProperty(default=1.0)
    emission_roughness : FloatProperty(default=0.5)
    emission_metalness : FloatProperty(default=0.0)
    emission_factor    : FloatProperty(default=4.0, min=0.01)
    emission_strengths : CollectionProperty(type=DCPEmissionEntry)  # max 5

    file_save_path     : StringProperty(subtype='DIR_PATH')

    # Info Quadrant (pro .blend)
    info_line_1        : StringProperty(default="YOUR PROJECT NAME")
    info_line_2        : StringProperty(default="(C) YOUR STUDIO")
    info_line_3        : StringProperty(default="YOUR LICENSE")
    bg_hex             : StringProperty(default="1A1A1A")
    fg_hex             : StringProperty(default="CCCCCC")

    # Workflow-State
    palette_generated  : BoolProperty(default=False)
    multicol_mat       : PointerProperty(type=bpy.types.Material)
    singlecol_mats     : CollectionProperty(type=DCPMatEntry)
    sel_quadrant       : EnumProperty(items=[("0","Solid",""),("1","Metal",""),("2","Emission","")], default="0")
    sel_cell_x         : IntProperty(min=0, max=31, get=_get_sel_cell_x, set=_set_sel_cell_x)
    sel_cell_y         : IntProperty(min=0, max=31, get=_get_sel_cell_y, set=_set_sel_cell_y)
    sel_emission       : IntProperty(default=0)
    preview_color      : FloatVectorProperty(subtype='COLOR', size=4)
    pick_from_image_editor : BoolProperty(default=False)

    # Snapshot (Vergleich bei Regenerierung, nicht editierbar)
    snap_color_columns      : IntProperty()
    snap_color_rows         : IntProperty()
    snap_pastel_saturation  : FloatProperty()
    snap_shadow_value       : FloatProperty()
    snap_solid_roughness    : FloatProperty()
    snap_solid_metalness    : FloatProperty()
    snap_metal_roughness    : FloatProperty()
    snap_metal_metalness    : FloatProperty()
    snap_emission_roughness : FloatProperty()
    snap_emission_metalness : FloatProperty()
    snap_emission_strips    : StringProperty()  # CSV der Stärken
```

---

## Textur-Layout

```
top-left     Solid      (Palette + PBR: R=Roughness, G=Metalness, B=0)
top-right    Metal      (Palette + PBR: R=Roughness, G=Metalness, B=0)
bottom-left  Emission   (Palette + PBR: R=Roughness, G=Metalness, B=normEmission)
bottom-right Info/Copyright
```

Emission-Zellen vertikal in Strips unterteilt (je ein Stärke-Level).
`cell_to_albedo_uv()` berechnet exakte UV-Koordinate der Zellmitte (inkl. Strip-Präzision).

**Automatische Größen:**
- `CELL_SIZE = max(9, n_strips * 5)` — mind. 5 px pro Strip, kein separater Konfig-Wert
- `PICKER_CELL_SIZE = ceil(CELL_SIZE * 1.5)`

---

## N-Panel Layout

Ein Panel sichtbar in Edit Mode und Object Mode (3D View N-Panel, Tab "DCP").
Konfiguration erfolgt über einen modalen Dialog (`invoke_props_dialog`), der per Button geöffnet wird.

```
─── Dynamic Color Palette ───────────────────────────── (Workflow)

Keine Palette generiert:
  [ ⚙  Configure… ]
  ℹ Configure palette, then click Generate.

Nach Generierung:
  [ ⚙  Configure… ]
  [ 👁  Pick From Image Editor: OFF ]
  ℹ Open an Image Editor to enable picking.

  ┌────────────────────────────────────┐
  │  [ Solid ] [ Metal ] [ Emission ]  │
  │  Cell X ___   Cell Y ___           │
  │  Emission Strip ___                │  (nur Quadrant Emission)
  │                                    │
  │  Color  ████   Hex  #FF8040        │
  │  RGB    …      RME  …              │
  │                                    │
  │  12 Faces in 3 Objects selected    │
  │                                    │
  │  [ UV  Assign Multicolor Material ]│
  │  [ ■   Assign Singlecolor Material]│
  └────────────────────────────────────┘

  [ 🗑  Cleanup Unused Slots           ]
```

"Generate Palette" erscheint nur solange noch keine Palette existiert.
Regenerierung: Configure → Werte anpassen → OK → Generate klicken → Sicherheitsabfrage wenn relevant.

### Konfigurations-Dialog (DCP_OT_OpenConfig)

Öffnet via `context.window_manager.invoke_props_dialog(self, width=350)`.
Änderungen gelten sofort auf `DCPProperties`; OK schließt den Dialog (kein Cancel/Undo nötig).

```
┌─ Palette Configuration ──────────────────────┐
│                                               │
│  Columns ___   Rows ___                       │
│  Saturation ___   Shadow ___                  │
│                                               │
│  Solid     Roughness ___   Metalness ___      │
│  Metal     Roughness ___   Metalness ___      │
│  Emission  Roughness ___   Metalness ___      │
│  Emission Factor ___                          │
│  Strips: [val] [val] [val]  [+] [-]           │
│                                               │
│  Export Path ___________________________      │
│                                               │
│  [ ⚙  Generate / Regenerate Palette ]         │
│  [ ↺  Reset to Defaults      ]                │
│                              [ OK ]           │
└───────────────────────────────────────────────┘
```

---

## Operator-Übersicht

| Operator | Beschreibung |
|---|---|
| `dcp.generate_palette` | Generiert Texturen + Multicol-Material, schreibt Snapshot |
| `dcp.confirm_regenerate` | Bestätigungs-Dialog bei Regenerierung |
| `dcp.open_config` | Öffnet modalen Konfigurations-Dialog (invoke_props_dialog) |
| `dcp.reset_defaults` | Setzt DCPProperties-Konfiguration auf DEFAULT_*-Konstanten zurück |
| `dcp.pick_from_image_editor` | Modal: Picker im Image Editor |
| `dcp.stop_pick_from_image_editor` | Beendet Pick-Mode |
| `dcp.assign_multicol` | UV-Islands → Palettenpunkt + dcp_multicol zuweisen |
| `dcp.assign_singlecol` | Singlecol-Material erstellen/cachen/zuweisen |
| `dcp.cleanup_unused_slots` | Ungenutzte Slots + verwaiste Materialien entfernen |
| `dcp.add_emission_strip` | Strip zur Collection hinzufügen (max 5) |
| `dcp.remove_emission_strip` | Strip entfernen (min 1) |

---

## Wichtige Design-Entscheidungen

- **Pointer-basierter Material-Cache** — kein Namens-Fallback für Singlecol
- **Snapshot-Mechanismus** — `snap_*`-Felder in DCPProperties, Vergleich beim Klick auf Generate wenn `palette_generated == True`
- **Singlecol bei Neugenerierung** — Cache geleert, Datablocks bleiben im .blend, DCP kennt sie nicht mehr
- **Multicol bei Neugenerierung** — Datablock bleibt, Node-Tree wird neu aufgebaut; zugewiesene Objekte behalten Material
- **Zwei Assign-Buttons** statt Mode-Switch — kein mentaler Overhead
- **Singlecol ↔ Multicol** überschreiben sich gegenseitig ohne Rückfrage
- **Picker ohne Selektion** → Farbwert ins Panel; mit Selektion → sofortiger Multicol-Assign
- **UV-Warn-Label** statt Operator-Report (max. 3 Objekte, dann "… and N more") — erscheint nur noch als Fallback, da fehlende UV-Layer automatisch angelegt werden
- **Name-Konstanten** in `__init__.py`: `PREFIX`, `VERSION` (aus `bl_info["version"]` abgeleitet), `ALBEDO_IMAGE_NAME`, `MATERIAL_IMAGE_NAME`, `PICKER_IMAGE_NAME`, `MULTICOL_MAT_NAME`, `SINGLECOL_MAT_PREFIX` — alle Datenblocknamen zentral, `bl_info` selbst ist im Extension-System nicht importierbar
- **STRENGTH_FACTOR** nur im Shader, kein Texturwert, löst keine Sicherheitsabfrage aus
- **Kein Image-Editor-Panel** — User erwartet dort keine DCP-Einstellungen
- **Konfigurations-Dialog statt Sub-Panel** — `DCP_OT_OpenConfig` via `invoke_props_dialog` statt `DCP_PT_Config`; saubere Trennung von Konfiguration und Workflow, kein Sub-Panel-Overhead im N-Panel

### Sicherheitsabfrage: relevante Parameter

| Parameter | Grund |
|---|---|
| color_columns, color_rows | UV-Punkte verschieben sich |
| pastel_saturation, shadow_value | Farbwerte aller Zellen |
| solid/metal/emission Roughness + Metalness | Singlecol PBR-Werte |
| emission_strengths (Werte oder Anzahl) | UV-Punkte + Emission-Werte |

Nicht relevant: emission_factor, CELL_SIZE, bg/fg_hex, info_lines, file_save_path.

---

## Assign-Verhalten

**Multicol:** Kein UV-Layer vorhanden → wird automatisch als `"UVMap"` angelegt (Edit Mode und Object Mode).
- Edit Mode → UV Islands selektierter Faces auf Palettenpunkt; wird multicol erstmalig hinzugefügt (`mat_is_new`) oder der Layer neu erstellt (`uv_is_new`), erhalten alle nicht-selektierten Faces, die auf den neuen Slot zeigen, Weiß als Initialwert (Solid, Spalte `0`, letzte Zeile)
- Object Mode → alle Face-UVs auf Palettenpunkt, Slot 0, alle polygon.material_index → 0

**Singlecol:** Cache oder neu erstellen; Edit Mode → selektierte Faces; Object Mode → Slot 0

**Cleanup:** Edit Mode immer enabled; Object Mode nur bei Selektion; respektiert Fake User

**Export:** `dcp_albedo.png`, `dcp_material.png` in `file_save_path` (nur diese beiden; `dcp_picker` wird **nicht** exportiert); Godot 4 Shader als Muster-Datei im Repo

---

## V3 Ausblick

- Multi-Palette-Support via Collection (mehrere Prefixes, je eigene Konfiguration)
- User-seitige Shader-Anpassung (Template-Textblock in Blender)
