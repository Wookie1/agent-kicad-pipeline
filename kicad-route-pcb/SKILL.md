---
name: "kicad-route-pcb"
description: "Route PCB traces using Freerouter auto-routing (primary) or manual add_trace calls (fallback). Freerouter requires Java and the freerouting JAR — both are set up by run_agent_zero.sh. Run after kicad-run-drc passes with 0 non-unconnected violations."
version: "2.1.0"
author: "kicad-pcb-skills"
tags: ["kicad", "pcb", "routing", "traces", "vias", "freerouter", "autoroute"]
trigger_patterns:
  - "route pcb"
  - "autoroute"
  - "route traces"
  - "route board"
  - "add traces"
---

# KiCad PCB Routing

## Overview
Use after the layout skill has placed all components and ensured a
valid board outline; this skill only handles routing, not placement
or outline repair.
**Primary method: Freerouter auto-routing** via `scripts/kicad_freerouter.py`.
**Fallback: manual routing** using `add_trace` / `add_via` MCP calls.

Use Freerouter for boards with >5 nets. Use manual routing for trivial boards or to fix the few nets Freerouter leaves unrouted.

## Prerequisites
- `kicad-run-drc` passed (0 violations except "unconnected items")
- All components placed at non-zero positions
- Java installed: `java -version` works in container
- `FREEROUTING_JAR=/a0/usr/freerouting/freerouting.jar` env var set
- Layout completed: all components placed (layout skill finished)
- Board outline valid on `Edge.Cuts` (if DRC reports malformed outline,
  run the layout skill’s `ensure_board_outline` step before routing)

## Prerequisites Check

Before running Freerouter, verify all required tools are available:

```bash
# 1. Check Java
java -version 2>&1 | head -1
# Expected: openjdk version "11..." or similar

# 2. Check freerouting JAR
echo "JAR path: $FREEROUTING_JAR"
ls -lh "$FREEROUTING_JAR"
# Expected: file size ~10MB

# 3. Check pcbnew Python module (use system python3)
python3 -c "import pcbnew; print('pcbnew OK, version:', pcbnew.Version())"
# Expected: pcbnew OK, version: 9.x.x

# 4. Check kicad-cli-xvfb (needed for DRC after routing)
which kicad-cli-xvfb
# Expected: /usr/local/bin/kicad-cli-xvfb or similar
```

If any check fails:
- **Java missing:** `apt-get install -y default-jre`
- **JAR missing:** Check `FREEROUTING_JAR` env var; download from https://github.com/freerouting/freerouting/releases
- **pcbnew missing:** KiCad not installed or system Python path issue
- **kicad-cli-xvfb missing:** Check `/usr/local/bin/`; it is a wrapper script installed by run_agent_zero.sh

> **Board sanity check:** If `kicad-run-drc` reports outline-related
> errors (malformed outline, no edges on Edge.Cuts) or overlapping
> board outlines, do **not** call this routing skill yet. Instead,
> call the layout skill to run `ensure_board_outline` and re-run DRC
> until the outline is clean, then route.

## Method A — Freerouter Auto-Routing (Primary)

> **DSN export:** `kicad_freerouter.py` uses `kicad-cli pcb export specctra`
> first (fully headless, no display needed), then falls back to pcbnew.
>
> **SES import:** Uses `pcbnew.ImportSpecctraSES()` with `pcbnew.InitSettings()`
> for KiCad 9.0 headless. Requires `DISPLAY=:99` + Xvfb (set up by run_agent_zero.sh).
>
> **FreeRouting v2.1.0 CLI flags:** `-de <input.dsn>` `-do <output.ses>` (not `-i`/`-o`).
>
> **Zone fill:** Script fills copper zones after SES import — required to avoid
> false-positive GND unconnected items in DRC.


### Step 1 — Run Freerouter
```bash
/a0/usr/skills-venv/bin/python3 scripts/kicad_freerouter.py \
  /path/to/board.kicad_pcb \
  --passes 100 \
  --threads 4 \
  --max-iter 3 \
  --output-dir /path/to/routing/
```
The script auto-detects Java, the JAR (`FREEROUTING_JAR` env var), and the system `python3` with pcbnew. It exports DSN → routes → imports SES → prints a quality report.

### Step 2 — Check the report
The report shows:
- Completion %: must reach **100%** (0 unrouted connections)
- Via count and trace length
- DRC result (unconnected, clearance errors)

If completion < 100%, retry with more passes:
```bash
/a0/usr/skills-venv/bin/python3 scripts/kicad_freerouter.py \
  /path/to/board.kicad_pcb --passes 200 --max-iter 3
```

If Freerouter still leaves nets unrouted after 3 iterations, use Method B below to route only the remaining nets manually.

### Step 3 — Analyse an existing routing (no re-route)
```bash
/a0/usr/skills-venv/bin/python3 scripts/kicad_freerouter.py \
  /path/to/board.kicad_pcb --analyse-only
```

---

## Method B — Manual Routing (Fallback)

⛔ **Manual routing means `add_trace` MCP calls ONLY.** Do NOT write pcbnew Python to add tracks.
KiCad 9 renamed many classes — `pcbnew.SEGT`, `pcbnew.TRACK`, `pcbnew.VIA` do NOT exist.
The correct names are `pcbnew.PCB_TRACK`, `pcbnew.PCB_VIA` — but you should not need them since `add_trace` handles this.

Use when: board has ≤5 nets, or to finish nets Freerouter left unrouted.

### Trace width guide
| Net type | Width | Notes |
|----------|-------|-------|
| Signal (default) | 0.25 mm | UART, GPIO, SPI, I2C |
| Power < 0.5 A | 0.5 mm | VCC to ICs |
| Power 0.5–1 A | 1.0 mm | LDO output, logic supply |
| Power 1–3 A | 2.0 mm | Motor power, LED strips |
| GND | copper zone | Preferred over traces |

### Get pad positions
```
analyze_schematic_connections(schematic_path="/path/to/board.kicad_sch")
list_pcb_footprints(pcb_path="/path/to/board.kicad_pcb")
```

### Add traces
```
add_trace(
  pcb_path="/path/to/board.kicad_pcb",
  x1=pad1_x, y1=pad1_y,
  x2=pad2_x, y2=pad2_y,
  layer="F.Cu",
  width=0.25
)
```
Multi-segment traces: one `add_trace` call per segment. Use 45-degree bends only.

### Add vias (layer switch)
```
add_via(
  pcb_path="/path/to/board.kicad_pcb",
  x=via_x, y=via_y,
  size=0.8, drill=0.4,
  layers=["F.Cu", "B.Cu"],
  net="NET_NAME"
)
```

### Check progress
```
run_drc_check(project_path="/path/to/board.kicad_pro")
```
Stop when `unconnected items = 0`.

---


### Expected post-routing DRC noise (non-blocking after FreeRouting)
| Violation type | Typical count | Action |
|---------------|---------------|--------|
| `lib_footprint_issues` | 1 per custom footprint | Ignore — library validation only, not manufacturing |
| `silk_over_copper` | Few | Minor; note in design checklist |
| `track_dangling` | 1–5 | Tiny trace stubs from FreeRouting; fixable in KiCad UI |

## Final DRC
After all nets are routed (by either method):
```
run_drc_check(project_path="/path/to/board.kicad_pro")
```
Fix any clearance or track-too-narrow errors before proceeding.

## Routing Priority (manual mode)
1. **GND / power** — widest traces, shortest path
2. **Crystal** — short, direct, away from power
3. **Decoupling caps** → IC power pin
4. **Signal nets** — group by bus (SPI, I2C, UART)
5. **Remaining**

## Success Criteria
- `run_drc_check` returns 0 unconnected items
- 0 clearance violations
- Power nets routed with correct widths

## Next Skill
→ **kicad-manufacturing-export** — generate all manufacturing deliverables
