---
name: "kicad-create-custom-footprint"
description: "Create a custom KiCad footprint (.kicad_mod) for non-standard or proprietary packages. Generates courtyard, fab layer, silkscreen, and pad definitions, then registers the library in fp-lib-table. Use before assigning footprints in kicad-schematic-design when the required package is absent from standard KiCad libraries."
version: "1.1.0"
author: "kicad-pcb-skills"
tags: ["kicad", "pcb", "footprint", "custom", "library", "kicad_mod", "package"]
trigger_patterns:
  - "custom footprint"
  - "create footprint"
  - "footprint not in library"
  - "custom package"
  - "new pad layout"
  - "proprietary package"
---

# Create Custom KiCad Footprint

## Overview
Generates `.kicad_mod` footprint files with pads, courtyard, fab layer, and silkscreen. Factory helpers produce correct SOIC, QFP, and DIP footprints from minimal inputs.

## Standard Pad Sizes (IPC-7351)
| Package | pad_w | pad_h | pitch | row_spacing |
|---------|-------|-------|-------|-------------|
| SOIC-8 | 1.60 | 0.60 | 1.270 | 5.40 |
| SOIC-16 | 1.60 | 0.60 | 1.270 | 7.50 |
| SOT-23-3 | 1.10 | 0.60 | 1.900 | 2.80 |
| 0402 SMD | 1.00 | 0.50 | — | — |
| 0603 SMD | 1.50 | 0.80 | — | — |
| 0805 SMD | 1.80 | 1.20 | — | — |
| DIP-8 | 1.60 dia | — | 2.540 | 7.62 |
| DIP drill | 0.80 | — | — | — |

## Step 1 — Build the footprint spec JSON

**Option A: Factory helper (always prefer this)**
```json
[
  { "factory": "soic", "pin_count": 8,  "pitch": 1.27, "pad_w": 1.6, "pad_h": 0.6 },
  { "factory": "soic", "pin_count": 16, "pitch": 1.27 },
  { "factory": "qfp",  "total_pins": 32, "pitch": 0.8, "body_w": 7.0, "body_h": 7.0 },
  { "factory": "dip",  "pin_count": 8,  "pitch": 2.54, "row_spacing": 7.62 }
]
```

**Option B: Custom pad specification**
```json
{
  "name": "MY_SOT23_VARIANT",
  "description": "Custom 3-pad SOT-23",
  "smd": true,
  "pads": [
    {"number":"1","pad_type":"smd","shape":"rect","x":-0.95,"y":0.0,"w":1.1,"h":0.6,
     "layers":["F.Cu","F.Paste","F.Mask"]},
    {"number":"2","pad_type":"smd","shape":"rect","x": 0.95,"y":0.0,"w":1.1,"h":0.6,
     "layers":["F.Cu","F.Paste","F.Mask"]},
    {"number":"3","pad_type":"smd","shape":"rect","x": 0.0,"y":1.30,"w":1.1,"h":0.6,
     "layers":["F.Cu","F.Paste","F.Mask"]}
  ],
  "courtyard_lines": [
    {"x1":-1.5,"y1":-0.5,"x2": 1.5,"y2":-0.5,"layer":"F.Courtyard","width":0.05},
    {"x1": 1.5,"y1":-0.5,"x2": 1.5,"y2": 1.8, "layer":"F.Courtyard","width":0.05},
    {"x1": 1.5,"y1": 1.8, "x2":-1.5,"y2": 1.8, "layer":"F.Courtyard","width":0.05},
    {"x1":-1.5,"y1": 1.8, "x2":-1.5,"y2":-0.5,"layer":"F.Courtyard","width":0.05}
  ]
}
```
Through-hole pads: `"pad_type":"thru_hole"` + `"drill"` dimension. Pin 1 uses `"shape":"rect"`, all others `"shape":"circle"`.

## Step 2 — Generate the .kicad_mod file
```bash
/a0/usr/skills-venv/bin/python3 scripts/kicad_footprint_builder.py /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/spec.json \
  --out /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/my_custom_footprints.pretty/
```

## Step 3 — Register the library
```bash
/a0/usr/skills-venv/bin/python3 scripts/update_fp_lib_table.py \
  --project /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/<project_name>.kicad_pro \
  --lib-name "my_custom_footprints" \
  --lib-path /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/my_custom_footprints.pretty
```

## Step 4 — Verify
```
search_footprint_libraries(query="MY_SOT23_VARIANT")
get_footprint_details(footprint_id="my_custom_footprints:MY_SOT23_VARIANT")
```
Confirm pad count, dimensions, and courtyard bounds. Record the full footprint ID: `"my_custom_footprints:MY_SOT23_VARIANT"`.

## Courtyard Rules
- Courtyard must enclose all pads with ≥0.25mm clearance
- Factory helpers auto-generate correct courtyards — prefer them

## Success Criteria
- Script exits with code 0
- `.kicad_mod` file exists in the `.pretty` directory
- `get_footprint_details` returns correct pad count and positions

## Error Recovery
| Error | Fix |
|-------|-----|
| `fp-lib-table not found` | `update_fp_lib_table.py` creates it if absent |
| Pads overlap in DRC | Increase pitch or reduce pad size |
| Factory generates wrong size | Check `pin_count` vs `total_pins` (QFP uses `total_pins`) |

## Next Skill
→ **kicad-schematic-design** — use the footprint IDs for `assign_footprint` calls
