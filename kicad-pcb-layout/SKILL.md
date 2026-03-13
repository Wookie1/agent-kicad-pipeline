---
name: "kicad-pcb-layout"
description: "Lay out a KiCad PCB: sync schematic to PCB, place all components at specified positions and orientations, add copper fills for power planes, set trace widths for power vs signal nets, and add required silkscreen text. Run after ERC is clean and before routing."
version: "1.3.0"
author: "kicad-pcb-skills"
tags: ["kicad", "pcb", "layout", "placement", "copper-fill", "silkscreen"]
trigger_patterns:
  - "pcb layout"
  - "place components on pcb"
  - "component placement"
  - "pcb design"
  - "layout board"
  - "arrange components"
---

# KiCad PCB Layout

## Overview
Syncs the schematic netlist into the PCB, places every component, adds copper fills, and prepares for routing.
Order: **sync → upgrade format → place → verify → copper fills → silkscreen**.

## Prerequisites
- `kicad-run-erc` passed with 0 errors
- `schematic_path` and `pcb_path` known
- Board outline on Edge.Cuts (from kicad-import-dxf or `set_board_outline_rect`)
- `board_bounds` known: {x_min, y_min, x_max, y_max} (from `get_pcb_statistics` or board dimensions)


## ⭐ PRIMARY METHOD — pcb_layout_full.py (use this first)

> **Why use this?** Running the full layout pipeline step-by-step requires
> 7 sequential decisions, each with failure modes. `pcb_layout_full.py` does
> ALL of them in one script call: sync → upgrade format → board outline →
> place components → GND fills → DRC. Agents that call individual steps
> in sequence frequently spiral into diagnosis loops when one step behaves
> unexpectedly.

### Step A — Write groups.json

Create `/path/to/project_dir/groups.json` describing component placement groups:
```json
[
  {
    "label": "ICs",
    "origin": [15.0, 8.0],
    "cols": 2,
    "col_spacing": 8.0,
    "row_spacing": 8.0,
    "refs": ["U1", "C2"]
  },
  {
    "label": "Passives",
    "origin": [5.0, 5.0],
    "cols": 3,
    "col_spacing": 6.0,
    "row_spacing": 6.0,
    "refs": ["R1", "R2", "R3", "C1"]
  },
  {
    "label": "Connectors",
    "origin": [3.0, 10.0],
    "cols": 1,
    "col_spacing": 0,
    "row_spacing": 8.0,
    "refs": ["J1"]
  }
]
```

### Step B — Run pcb_layout_full.py

```bash
DISPLAY=:99 python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-pcb-layout/scripts/pcb_layout_full.py \
  --schematic /path/to/board.kicad_sch \
  --pcb       /path/to/board.kicad_pcb \
  --groups    /path/to/groups.json \
  --width     30 \
  --height    20
```

Expected output:
```
=== pcb_layout_full.py: board_name (30×20mm) ===
--- Step 1: Sync schematic → PCB ---
[sync] Placed 9/9 footprints
--- Step 2: Upgrade PCB format ---
[upgrade] PCB format upgraded
--- Step 3: Board outline ---
[outline] Board outline set: 30×20mm at (0,0)
--- Step 4: Place components ---
[place] Placed 9 components
--- Step 5: GND copper fills ---
[fills] GND copper fills added on F.Cu and B.Cu
--- Step 6: DRC ---
[drc] 0 blocking, 1 non-blocking violations
[drc] ✅ PASS — 0 blocking violations
=== Layout complete: /path/to/board.kicad_pcb ===
```

### Step C — Generate thumbnail
```
generate_pcb_thumbnail(project_path="/path/to/board.kicad_pro")
```

> ⚠️ **Use the individual steps below ONLY if pcb_layout_full.py fails.**
> The individual steps are retained as reference and fallback ONLY.

---

## Python paths: system vs skills-venv

> **Rule:** Any step using `pcbnew` Python bindings must use **system `python3`**
> (`/usr/bin/python3` or just `python3`), NOT `/a0/usr/skills-venv/bin/python3`.
> pcbnew is only available in the system Python installed with KiCad.
> The skills-venv is used only for scripts that do NOT require pcbnew
> (e.g. `kicad_place_footprints.py` uses pure s-expression parsing).

## ⛔ KiCad 9 pcbnew API — Renamed Classes & Constants (BREAKING CHANGES)
Old names cause `ImportError` or silent failures. Use only these in KiCad 9:

**Classes (all renamed):**
| ❌ Old name (will ImportError) | ✅ KiCad 9 name |
|---|---|
| `pcbnew.SEGT` | `pcbnew.PCB_TRACK` |
| `pcbnew.TRACK` | `pcbnew.PCB_TRACK` |
| `pcbnew.VIA` | `pcbnew.PCB_VIA` |
| `pcbnew.DRAWSEGMENT` | `pcbnew.PCB_SHAPE` |
| `pcbnew.MODULE` | `pcbnew.FOOTPRINT` |
| `pcbnew.D_PAD` | `pcbnew.PAD` |
| `pcbnew.SEGCLOSED` | `pcbnew.PCB_SHAPE` (use `SetShape(pcbnew.SHAPE_T_RECT)`) |
| `pcbnew.SEGOPEN` | `pcbnew.PCB_SHAPE` (use `SetShape(pcbnew.SHAPE_T_SEGMENT)`) |

**Layer constants (changed):**
| ❌ Old name (doesn't exist) | ✅ KiCad 9 name |
|---|---|
| `pcbnew.BOARD_EDGE_CUT` | `pcbnew.Edge_Cuts` |
| `pcbnew.BOARD_EDGE_CUTS` | `pcbnew.Edge_Cuts` |
| Layer index for Edge.Cuts | `25` (but prefer `pcbnew.Edge_Cuts`) |

**Correct board outline snippet (KiCad 9):**
```python
# Add 4 line segments forming a rectangle on Edge.Cuts
corners = [(0,0),(w,0),(w,h),(0,h)]
for i in range(4):
    x1,y1 = corners[i]; x2,y2 = corners[(i+1)%4]
    seg = pcbnew.PCB_SHAPE(board)
    seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
    seg.SetLayer(pcbnew.Edge_Cuts)          # ← NOT BOARD_EDGE_CUT
    seg.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    seg.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
    seg.SetWidth(pcbnew.FromMM(0.05))
    board.Add(seg)
board.Save(pcb_path)
```

> ⚠️ **Do NOT write this manually** — `pcb_layout_full.py` already does this correctly. Only use the snippet above if `pcb_layout_full.py` fails and you must repair the outline manually.

⛔ **Do NOT write custom pcbnew routing Python.** Use Freerouter or `add_trace` MCP only.

## PCB Layer Reference (KiCad 9.0)
| Layer | Use |
|-------|-----|
| `F.Cu` | Front copper traces/pads |
| `B.Cu` | Back copper traces/pads |
| `F.Silkscreen` | Front labels and markings |
| `B.Silkscreen` | Back markings |
| `Edge.Cuts` | Board outline |
| `F.Courtyard` | Front component keep-out boundary |
| `F.Fab` | Front fabrication reference outlines |

## Step 1 — Sync schematic to PCB

> ⚠️ **`update_pcb_from_schematic` MCP tool fails (exit 1) in headless Docker — do NOT use it.**
> Use `sch_to_pcb_sync.py` instead. It reads the schematic s-expressions directly,
> handles both MCP-placed and batch-script symbols, and works reliably in headless Docker.

```bash
DISPLAY=:99 python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-pcb-layout/scripts/sch_to_pcb_sync.py \
  /path/to/board.kicad_sch \
  /path/to/board.kicad_pcb
```

Expected output: `Synced N/N footprints to PCB`
All footprints will be stacked at (0,0) after sync — that is expected.

## Step 2 — Upgrade PCB file format (REQUIRED — do this immediately after sync)

> **This step is mandatory before any `kicad-cli` command (DRC, Gerber export).**
> The MCP server writes PCB files in an older format (version 20231120) that
> kicad-cli cannot load. Load and re-save through pcbnew to upgrade to native format.
> Use system `python3` (has pcbnew), NOT skills-venv.

```bash
DISPLAY=:99 python3 -c "
import sys; sys.path.insert(0, '/usr/lib/python3/dist-packages')
import pcbnew
board = pcbnew.LoadBoard('/path/to/board.kicad_pcb')
board.Save('/path/to/board.kicad_pcb')
print('PCB format upgraded')
"
```

Verify: `kicad-cli-xvfb pcb drc /path/to/board.kicad_pcb` should now exit without format errors.

## Step 3 — Ensure board outline (repair or create)

> If DRC reports “board has malformed outline (self-intersecting)” or
> “no edges found on Edge.Cuts”, **do NOT delete the PCB file.**
> Instead, repair or (if needed) regenerate a clean rectangular outline
> based on the existing board extents.

Use system `python3` (has pcbnew), NOT the skills-venv:

```bash
DISPLAY=:99 python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-pcb-layout/scripts/ensure_board_outline.py \
  --pcb /path/to/board.kicad_pcb


## Step 4 — Verify footprint count
```
list_pcb_footprints(pcb_path="/path/to/board.kicad_pcb")
```
Check: component count matches schematic. All components will be at or near (0,0) — that is expected at this stage.

## Step 5 — Place all components

### Derive placement coordinates from board dimensions

Given board bounds `{x_min, y_min, x_max, y_max}` (in mm), compute group origins:
```
board_w = x_max - x_min          # total board width
board_h = y_max - y_min          # total board height
margin  = 3.0                    # mm clearance from Edge.Cuts

# Safe placement area:
place_x0 = x_min + margin        # leftmost safe X
place_y0 = y_min + margin        # topmost safe Y
place_x1 = x_max - margin        # rightmost safe X
place_y1 = y_max - margin        # bottommost safe Y

# Example group origins for a 100x80mm board (margin=3):
# Connectors at left edge:     origin=[3,  40]
# Power/control at top-left:   origin=[10, 6]
# LED array across middle:     origin=[20, 30]
# MCU/IC at centre-right:      origin=[60, 10]
```

### Primary method: group-based auto-placement

Create `groups.json` describing functional groups. The script computes grid positions within each group.

```json
[
  {
    "label": "Connectors",
    "origin": [3.0, 10.0],
    "cols": 1,
    "col_spacing": 0,
    "row_spacing": 12.0,
    "refs": ["J1", "J2", "J3"]
  },
  {
    "label": "Power and control",
    "origin": [15.0, 5.0],
    "cols": 4,
    "col_spacing": 8.0,
    "row_spacing": 8.0,
    "refs": ["U1", "C1", "C2", "R1", "R2", "D_protect"]
  },
  {
    "label": "LED array",
    "origin": [15.0, 30.0],
    "cols": 10,
    "col_spacing": 7.5,
    "row_spacing": 7.5,
    "refs": ["D1","D2","D3","D4","D5","D6","D7","D8","D9","D10",
             "R3","R4","R5","R6","R7","R8","R9","R10"]
  }
]
```

Run placement using the groups file:
```python
import json, sys
sys.path.insert(0, '/a0/usr/projects/pcb-design/.a0proj/skills/kicad-pcb-layout/scripts')
from kicad_place_footprints import auto_place_from_groups, place_footprints
from pathlib import Path

pcb_path = '/path/to/board.kicad_pcb'
groups = json.loads(Path('groups.json').read_text())
placements = auto_place_from_groups(groups)
content = Path(pcb_path).read_text()
content = place_footprints(content, placements)
Path(pcb_path).write_text(content)
print(f'Placed {len(placements)} components')
```

Or run via CLI with a flat placements.json (for fine-tuned individual positions):
```bash
/a0/usr/skills-venv/bin/python3 scripts/kicad_place_footprints.py \
  /path/to/board.kicad_pcb \
  /path/to/placements.json
```

See current positions before placing:
```bash
/a0/usr/skills-venv/bin/python3 scripts/kicad_place_footprints.py \
  /path/to/board.kicad_pcb --list-current
```

### Flat placements.json format (alternative / fine-tuning)
```json
[
  {"ref": "U1",  "x": 30.0, "y": 20.0, "angle": 0,   "side": "front"},
  {"ref": "C1",  "x": 27.0, "y": 20.0, "angle": 0,   "side": "front"},
  {"ref": "R1",  "x": 70.0, "y": 15.0, "angle": 90,  "side": "front"},
  {"ref": "J1",  "x": 10.0, "y": 30.0, "angle": 180, "side": "front"}
]
```

**Placement rules:**
| Component type | Rule |
|---------------|------|
| MCU / main IC | Board centre or near programming connector |
| Decoupling caps | ≤2mm from IC power pin, same side |
| Power supply | Near power input connector |
| Crystal | ≤10mm from MCU crystal pins, away from power traces |
| Connectors | Board edge; pin 1 marked clearly |
| `"side": "back"` | Mirrors component to B.Cu |

Maintain ≥0.5mm clearance from Edge.Cuts for all components.

## Step 6 — Verify placement
```
get_pcb_statistics(pcb_path="/path/to/board.kicad_pcb")
generate_pcb_thumbnail(project_path="/path/to/board.kicad_pro")
```
Check: component count matches schematic; none at (0,0).

## Step 7 — Add GND copper fills
```
add_copper_zone(
  pcb_path="...", net_name="GND", layer="F.Cu", clearance=0.2,
  polygon_points=[[x_min+1,y_min+1],[x_max-1,y_min+1],[x_max-1,y_max-1],[x_min+1,y_max-1]]
)
add_copper_zone(
  pcb_path="...", net_name="GND", layer="B.Cu", clearance=0.2,
  polygon_points=[[x_min+1,y_min+1],[x_max-1,y_min+1],[x_max-1,y_max-1],[x_min+1,y_max-1]]
)
```
GND fills on both sides reduce via count and improve EMI.

## Step 8 — Add silkscreen

### LED / Diode Polarity Marking (Required for Assembly)

PCB fabricators and assembly houses require polarity markers for all LEDs and diodes.
Always add a silkscreen **'A'** near the **anode pad** of every LED and diode.

> Use system `python3` (has pcbnew), NOT skills-venv.

```bash
DISPLAY=:99 python3 << 'PYEOF'
import pcbnew, math

board = pcbnew.LoadBoard("/path/to/board.kicad_pcb")
scale = 1e6

for fp in board.GetFootprints():
    ref = fp.GetReference()
    if not (ref.startswith('D') or ref.startswith('LED')):
        continue
    anode_pad = None
    for pad in fp.Pads():
        if pad.GetName() in ('A', 'A1', 'A2', 'A3'):
            anode_pad = pad
            break
    if anode_pad is None:
        continue
    fp_pos = fp.GetPosition()
    ap = anode_pad.GetPosition()
    dx, dy = ap.x - fp_pos.x, ap.y - fp_pos.y
    d = math.sqrt(dx*dx + dy*dy) or 1
    nx, ny = dx/d, dy/d
    offset = 1.5 * scale
    tx = ap.x + int(nx * offset)
    ty = ap.y + int(ny * offset)
    text = pcbnew.PCB_TEXT(board)
    text.SetText('A')
    text.SetLayer(pcbnew.F_SilkS)
    text.SetPosition(pcbnew.VECTOR2I(tx, ty))
    text.SetTextSize(pcbnew.VECTOR2I(int(0.5*scale), int(0.5*scale)))
    text.SetTextThickness(int(0.08*scale))
    text.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    board.Add(text)

board.Save("/path/to/board.kicad_pcb")
print("Anode markers added to all LEDs/diodes")
PYEOF
```

Board name and serial number:
```
add_pcb_text(pcb_path, text="BOARD_NAME v1.0", x=5.0, y=5.0, layer="F.Silkscreen", size=1.5)
add_pcb_text(pcb_path, text="SN: ________",    x=5.0, y=8.0, layer="F.Silkscreen", size=1.0)
```

## ⚠️ Routing Verification — "0 tracks" in get_pcb_statistics

`get_pcb_statistics` may show `track_count: 0` even after routing attempts. **Do NOT accept this and move on.**

`track_count: 0` means routing did NOT succeed. Debug by checking DRC unrouted count:
```bash
kicad-cli-xvfb pcb drc --output /tmp/drc_check.json --format json --units mm <pcb_path>
# Then check:  cat /tmp/drc_check.json | python3 -c "import json,sys; d=json.load(sys.stdin); print([v for v in d.get('violations',[]) if v.get('type')=='unconnected_items'])"
```

Zero unrouted DRC violations = board is routed (even if track_count shows 0 due to reload lag).
Non-zero unrouted DRC violations = routing failed; re-run Freerouter or use `add_trace` for remaining nets.

**Do NOT:**
- Proceed to silkscreen/manufacturing with unverified routing
- Assume traces were added but "just not showing in stats"

## Success Criteria
- PCB format upgraded (Step 2 completed)
- All components placed (none at 0,0)
- `get_pcb_statistics` shows correct component count and board dimensions
- GND copper fills on both sides
- DRC unconnected_items = 0 (routing verified)
- Silkscreen markings present

## Next Skill
→ **kicad-run-drc** to validate placement before routing
