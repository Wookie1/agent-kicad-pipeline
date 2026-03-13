---
name: "kicad-run-drc"
description: "Run KiCad Design Rule Check (DRC) on a PCB layout, interpret each violation type, and fix all errors. Used twice: after component placement (pre-routing) and after routing (post-routing). Must return 0 blocking violations before manufacturing export."
version: "1.2.0"
author: "kicad-pcb-skills"
tags: ["kicad", "pcb", "drc", "design-rules", "validation", "clearance"]
trigger_patterns:
  - "run drc"
  - "design rule check"
  - "check pcb errors"
  - "fix drc violations"
  - "drc errors"
  - "pcb validation"
---

# KiCad Design Rule Check (DRC)

## Overview
DRC validates the physical layout against manufacturing and electrical rules. Run twice: after placement (fix courtyard/edge issues) and after routing (fix clearance/unconnected issues).

**Pre-routing:** Fix courtyard overlaps and edge clearances. Ignore "unconnected items" — normal before routing.
**Post-routing:** Fix all blocking violations. Zero blocking violations required before manufacturing.

## Step 1 — Run DRC (PRIMARY: kicad-cli-xvfb)

> **Always use `kicad-cli-xvfb`**, not plain `kicad-cli`. The xvfb wrapper sets
> `DISPLAY=:99` which is required for KiCad's GTK/wxWidgets initialisation.
> Plain `kicad-cli` silently fails or produces empty output in headless containers.

```bash
kicad-cli-xvfb pcb drc \
  --output /path/to/drc_report.json \
  --format json \
  --units mm \
  /path/to/board.kicad_pcb
```

Parse results:
```bash
python3 -c "
import json
d = json.load(open('/path/to/drc_report.json'))
violations = d.get('violations', [])
unconn = [v for v in violations if 'unconnected' in v.get('type','').lower()]
other  = [v for v in violations if 'unconnected' not in v.get('type','').lower()]
print(f'Total: {len(violations)}  Unconnected: {len(unconn)}  Other: {len(other)}')
from collections import Counter
for t,c in Counter(v.get('type','?') for v in violations).most_common():
    print(f'  {t}: {c}')
"
```

## Non-Blocking Violation Types

Not all DRC violations block manufacturing. Use this table to triage results:

| Violation type | Blocking? | Action |
|---|---|---|
| `lib_footprint_issues` | **No** | Ignore — library metadata check only, not a manufacturing issue |
| `silk_over_copper` | No (for fab) | Note it; fix if >20 instances or on critical pads |
| `track_dangling` | No (minor) | Note it; fix manually in KiCad GUI if needed |
| `unconnected_items` (pre-routing) | **No** | Expected — ignore until after routing |
| `unconnected_items` (post-routing) | **YES** | Must be 0 — re-route or add trace |
| `clearance_violation` | **YES** | Must fix — re-route offending trace |
| `track_too_narrow` | **YES** | Must fix — widen trace |
| `courtyard_overlap` | **YES** | Must fix — move component |
| `board_edge_clearance` | **YES** | Must fix — move component or trace inward |
| `hole_size_violation` | **YES** | Must fix — resize via drill |

## Step 2 — Fix each blocking violation type

### "Courtyard overlap"
Two components are too close. Move one using updated `placements.json` + placement script. Typical fix: increase separation by 1–2mm.

### "Board edge clearance"
Copper or component is <0.5mm from Edge.Cuts.
- Component: move inward in `placements.json`
- Trace: re-route at least 0.5mm from edge using `add_trace`

### "Clearance violation" (post-routing)
Two copper objects are closer than `min_clearance` (0.2mm).
```
add_trace(pcb_path, x1_new, y1_new, x2_new, y2_new, layer="F.Cu", width=0.25)
```
Re-route the offending trace farther away.

### "Track too narrow"
```
add_trace(pcb_path, x1, y1, x2, y2, layer="F.Cu", width=0.2)
```
Minimum width is 0.2mm.

### "Unconnected items" (post-routing only)
```
add_trace(pcb_path, x1=pad1_x, y1=pad1_y, x2=pad2_x, y2=pad2_y, layer="F.Cu", width=0.25)
```
Get pad positions from `list_pcb_footprints`. Or re-run `kicad-route-pcb`.

### "Hole size violation"
Fab minimum: JLCPCB 0.3mm drill; OSHPark 0.254mm.
```
add_via(pcb_path, x, y, size=0.8, drill=0.4)
```

### "Silkscreen clipped by solder mask"
Move the text 2–3mm away from the pad:
```
add_pcb_text(pcb_path, text="U1", x=adjusted_x, y=adjusted_y, layer="F.Silkscreen", size=1.0)
```

### "Footprint not in schematic"
Re-run `update_pcb_from_schematic` to remove orphaned footprints, or add the missing symbol to the schematic.

---

### Zone fill required after FreeRouting (before post-routing DRC)

After FreeRouting imports the SES file, copper zones (GND pour) are not filled.
Without zone fill, DRC reports all GND pads as "unconnected items" (false positives).

The `kicad_freerouter.py` script fills zones automatically after SES import.
If running DRC manually after routing, fill zones first:

```bash
python3 -c "
import pcbnew
b = pcbnew.LoadBoard('/path/to/board.kicad_pcb')
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save('/path/to/board.kicad_pcb')
print('Zones filled')
"
```

## Step 3 — Re-run DRC and check trend
```bash
kicad-cli-xvfb pcb drc \
  --output /path/to/drc_report.json \
  --format json --units mm \
  /path/to/board.kicad_pcb
```
Repeat until all **blocking** violation counts = 0. Maximum 5 iterations before escalating to user.

## Step 4 — Final validation
```
validate_project(project_path="/path/to/board.kicad_pro")
```

## Pre/Post-Routing Pass Gates
| Violation type | Pre-routing | Post-routing |
|---|---|---|
| Courtyard overlap | Fix | Fix |
| Edge clearance | Fix | Fix |
| Clearance violation | N/A | Fix |
| **Unconnected items** | **Ignore** | **Must be 0** |
| Track too narrow | N/A | Fix |
| lib_footprint_issues | Ignore | Ignore |
| silk_over_copper | Ignore | Ignore |
| track_dangling | Ignore | Ignore |

## Alternative: run_drc_check MCP tool

> Note: `run_drc_check` uses the same underlying kicad-cli and may have DISPLAY issues.
> Prefer the `kicad-cli-xvfb` command above for reliable results.

```
run_drc_check(project_path="/path/to/board.kicad_pro")
```

## Next Skill
**Pre-routing:** → **kicad-route-pcb**
**Post-routing:** → **kicad-manufacturing-export**
