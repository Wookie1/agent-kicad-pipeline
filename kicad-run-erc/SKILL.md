---
name: "kicad-run-erc"
description: "Run KiCad Electrical Rules Check (ERC) on a schematic using schematic_preflight.py (primary) or run_erc MCP tool (legacy, avoid). Interpret each violation type and fix all errors. Iterate until the schematic is ERC-clean (0 errors). Must complete before PCB layout begins."
version: "1.2.0"
author: "kicad-pcb-skills"
tags: ["kicad", "schematic", "erc", "validation", "electrical-rules", "errors"]
trigger_patterns:
  - "run erc"
  - "check schematic errors"
  - "electrical rules check"
  - "fix erc errors"
  - "erc violations"
  - "schematic validation"
---

# KiCad Electrical Rules Check (ERC)

## Overview
ERC validates the electrical correctness of a schematic. Target: 0 errors before exporting to PCB. Run → read violations → fix → repeat.

> **Primary method: `schematic_preflight.py`** — reliable, headless-safe, no SIGSEGV.
> **Do NOT use `run_erc` MCP tool** — it crashes with SIGSEGV (exit code -11) on KiCad 9.0
> headless. See Legacy section at the bottom if you must try it.

## Step 1 — Run preflight (PRIMARY)

```bash
python3 \
  /a0/usr/projects/pcb-design/.a0proj/skills/kicad-schematic-design/scripts/schematic_preflight.py \
  /path/to/board.kicad_sch \
  --summary
```

Expected passing output:
```
PASS | components=101 power_nets=1 labels=3 wires=122 errors=0 warnings=0
```

For full detail (useful when fixing errors):
```bash
python3 \
  /a0/usr/projects/pcb-design/.a0proj/skills/kicad-schematic-design/scripts/schematic_preflight.py \
  /path/to/board.kicad_sch
```

Preflight PASS = structurally sound; sufficient to proceed to PCB layout.

### Acceptable preflight warnings (do not block progression)
- `SINGLE-USE NET LABEL` for nets used only once (e.g. power input, control signal connectors)
- `PWR_FLAG` warnings when PWR_FLAG symbols are intentionally omitted

## Step 2 — Fix each violation type

### "Pin not connected"
**Fix A — connect it:**
```
add_net_label(schematic_path, "SIGNAL_NAME", pin_x, pin_y, angle=0)
```
**Fix B — intentionally unused:** Inject a no-connect flag at the exact pin coordinates:
```
(no_connect (at PIN_X PIN_Y) (uuid "NEW-UUID-HERE"))
```
Generate a UUID: `python3 -c "import uuid; print(uuid.uuid4())"`

### "Power pin not driven" / PWR_FLAG needed
```
add_schematic_symbol(schematic_path, lib_id="power:PWR_FLAG",
  reference="#PWR01", value="PWR_FLAG", x=12.7, y=10.16)
add_schematic_wire(schematic_path, 12.7, 10.16, 12.7, 12.7)
add_power_port(schematic_path, "+3V3", 12.7, 12.7)
```
Add one PWR_FLAG per power net that reports this error.

### "Duplicate reference designators"
```
update_symbol_property(
  schematic_path, reference="R1",
  property_name="Reference", new_value="R2"
)
```
Check `list_schematic_symbols` to find the next unused number.

### "Net label not connected"
Add a wire from the nearest pin to the label position:
```
add_schematic_wire(schematic_path, pin_x, pin_y, label_x, label_y)
```

### "Footprint not assigned"
```
assign_footprint(schematic_path, "U1", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm")
```

### "Pin type conflict" (output driving output)
Check net labels for typos connecting the wrong nets. If intentional (OR-wired open-drain): suppress with an ERC rule exception.

---

## Step 3 — Re-run preflight
```bash
python3 \
  /a0/usr/projects/pcb-design/.a0proj/skills/kicad-schematic-design/scripts/schematic_preflight.py \
  /path/to/board.kicad_sch --summary
```
Repeat Steps 1–3 until preflight returns **errors=0**. Maximum 5 iterations — if still failing, present remaining violations to user with exact coordinates.

## Step 4 — Export netlist (optional verification)
```
export_netlist(schematic_path, output_path="/path/to/project/board.xml", format="kicadxml")
analyze_schematic_connections(schematic_path="/path/to/board.kicad_sch")
```

## Success Criteria
- `schematic_preflight.py --summary` returns `errors=0`
- All components have footprints
- Netlist exports without errors

---

## Legacy: run_erc MCP tool

> ⚠️ **WARNING: `run_erc` crashes with SIGSEGV (exit code -11) on KiCad 9.0 headless.**
> Do NOT use this as your primary method. It is documented here only for reference.
> If you call it and get exit code -11 or a crash, switch immediately to `schematic_preflight.py`.

```
run_erc(
  schematic_path = "/path/to/board.kicad_sch",
  output_dir     = "/path/to/project/"
)
```

## Next Skill
→ **kicad-pcb-layout** to start the PCB layout phase
