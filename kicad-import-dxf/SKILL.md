---
name: "kicad-import-dxf"
description: "Import a DXF file as the board outline (Edge.Cuts layer) in a KiCad PCB file. Use whenever the user provides a DXF for the board shape instead of a simple rectangle."
version: "1.1.0"
author: "kicad-pcb-skills"
tags: ["kicad", "pcb", "dxf", "board-outline", "edge-cuts", "import"]
trigger_patterns:
  - "import dxf"
  - "board outline from dxf"
  - "dxf board shape"
  - "custom board shape"
  - "non-rectangular board"
---

# Import DXF Board Outline

## Overview
Parses a DXF file and injects all geometry as `gr_line`, `gr_arc`, and `gr_circle` elements on the `Edge.Cuts` layer. Handles LINE, ARC, CIRCLE, LWPOLYLINE, SPLINE, and ELLIPSE entities. Requires `ezdxf` (included in skills-venv).

## Required Inputs
| Input | Example | Notes |
|-------|---------|-------|
| `pcb_path` | `/a0/usr/projects/pcb-design/a0/usr/projects/pcb-design/workspace/pcb/<project_name>/<project_name>.kicad_pcb` | From project init |
| `dxf_path` | `/a0/usr/projects/pcb-design/a0/usr/projects/pcb-design/workspace/pcb/<project_name>/outline.dxf` | User-provided board outline |
| `scale` | `1.0` | Use `25.4` if DXF is in inches |
| `dxf_layer` | `OUTLINE` | Optional: restrict import to one DXF layer |

## Step 1 — Dry-run (inspect before importing)
```bash
/a0/usr/skills-venv/bin/python3 scripts/dxf_to_edge_cuts.py /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/outline.dxf
```
Prints s-expressions to stdout without modifying the PCB. Check for reasonable coordinates.

## Step 2 — Import into the PCB
```bash
/a0/usr/skills-venv/bin/python3 scripts/dxf_to_edge_cuts.py /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/outline.dxf \
  --pcb /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/<project_name>.kicad_pcb \
  --scale 1.0 \
  --width 0.05
```
Options: `--dxf-layer OUTLINE` to restrict to one layer; `--no-flip-y` if DXF already uses KiCad's Y-down orientation.
A `.bak` backup is created before modifying the PCB.

## Step 3 — Record board bounds
The script prints the bounding box. Record `x_min`, `y_min`, `x_max`, `y_max`, `width_mm`, `height_mm` for use in component placement.
If not printed, get bounds from:
```
get_pcb_statistics(pcb_path="/a0/usr/projects/pcb-design/workspace/pcb/<project_name>/<project_name>.kicad_pcb")
```

## Step 4 — Visual check
```
generate_pcb_thumbnail(project_path="/a0/usr/projects/pcb-design/workspace/pcb/<project_name>/<project_name>.kicad_pro")
```
Confirm a closed board outline is visible. If missing or distorted, check `--scale` and `--dxf-layer`.

## Success Criteria
- Script exits with code 0
- `get_pcb_statistics` shows non-zero board dimensions
- Thumbnail shows a closed board outline

## Error Recovery
| Error | Fix |
|-------|-----|
| Outline coordinates are huge (>1000mm) | DXF is in inches — use `--scale 25.4` |
| Outline appears mirrored | Try `--no-flip-y` |
| Only some entities imported | Use `--dxf-layer` to select the correct layer |
| Open outline (not closed) | Check DXF for gaps; LWPOLYLINE must have `is_closed=True` |

## Next Skill
→ **kicad-create-custom-symbol** for any non-standard components
→ **kicad-schematic-design** if all parts exist in standard libraries
