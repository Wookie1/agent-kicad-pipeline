# PCB Design — Supplemental Reference

Workflow, agent team, and phase sequence are defined in the orchestrator system prompt.
This file provides: design calculation rules, gate format templates, and standing rules.

---

## Design Calculations (run before delegating to pcb-schematic)

**RESISTOR POWER RATINGS**
```
P = V²/R  or  P = I²×R
Required margin: rated power ≥ 2× P_calc
0402→63mW, 0603→100mW, 0805→125mW, 1206→250mW, 2512→1W
⚠ AUTOMOTIVE: always use 14.4V, not 12V
```

**LED CURRENT-LIMITING RESISTORS**
```
R = (V_supply − n×V_forward) / I_forward
P = I²×R → package rating ≥ 2× P
V_forward: red/yellow≈2.0V, green/blue≈3.2V  |  I_forward: 10mA default
FLAG: any LED with no series resistor
```

**CAPACITOR VOLTAGE RATINGS**
```
V_rated ≥ 1.5× V_supply (ceramic), ≥ 2× V_supply (electrolytic)
```

**DECOUPLING CAPS** — 100nF ceramic per IC VCC pin, ≥10µF bulk per rail

**PULL-UP/DOWN** — I²C: 4.7kΩ (3.3V) or 2.2kΩ (5V). RESET: 10kΩ to VCC.
FLAG: floating input pins.

**POWER PROTECTION** — Reverse-polarity, ESD/TVS, fuse/PTC on power input.

---

## Gate Format Templates

### APPROVAL GATE 1 — Schematic

```
PHASE 2 COMPLETE — SCHEMATIC REVIEW
══════════════════════════════════════════════
Project : <name>  |  Rev : <revision>  |  Date : <today>

SCHEMATIC STATISTICS
  Total components  : <count>
  Total nets        : <count>
  Power nets        : <list>
  Preflight result  : PASS — 0 errors

COMPONENT ANALYSIS
  Resistors
    <R1  10Ω  0805 : P_calc = 22mW, rated 125mW  ✓>
    <R4 100Ω  0402 : P_calc = 78mW, rated 63mW   ⚠ UNDER-RATED>
  Capacitors
    Decoupling 100nF : <count> at <ICs>
    Voltage ratings  : <OK / flags>
  LEDs
    <D1 red : R2 330Ω → I_f = 9mA  ✓>
  Pull-up/down
    <I²C: R5 R6 4.7kΩ ✓>  |  Floating inputs: <none ✓ / list>
  Power protection
    Reverse-polarity : <✓ / NONE — recommend>
    ESD/TVS          : <✓ / NONE>
    Fuse/PTC         : <✓ / NONE>

PARTS VERIFICATION
  <Paste the full Parts Verification Checklist from pcb-parts-research,
   or "All components sourced from standard KiCad library — no custom parts">

DESIGN WARNINGS
  <List or "None">

─────────────────────────────────────────────
Reply "approve schematic" to proceed to layout.
══════════════════════════════════════════════
```
**STOP. DO NOT PROCEED until user approves.**

---

### APPROVAL GATE 2 — Layout

```
PHASE 3 COMPLETE — BOARD LAYOUT REVIEW
══════════════════════════════════════════════
Project : <name>  |  Rev : <revision>

BOARD STATISTICS
  Dimensions       : <W>mm × <H>mm
  Copper layers    : 2
  Total components : <count>  (<front> front, <back> back)
  Unrouted nets    : <count>  (expected — routing not yet run)

PLACEMENT NOTES
  <Key placement decisions>

DRC (pre-routing)
  Violations (excl. unconnected) : <count — must be 0>

[Board image]

─────────────────────────────────────────────
Reply "approve layout" to proceed to routing.
══════════════════════════════════════════════
```
**STOP. DO NOT PROCEED until user approves.**

---

### APPROVAL GATE 3 — Routing

```
PHASE 4 COMPLETE — ROUTING REVIEW
══════════════════════════════════════════════
Project : <name>  |  Rev : <revision>

ROUTING STATISTICS
  Completion    : <X>%
  Unrouted nets : <count>  (<list or "None">)
  Via count     : <count>
  DRC result    : <PASS / FAIL — list violations>

─────────────────────────────────────────────
Reply "approve routing" to proceed to quality check.
══════════════════════════════════════════════
```
**STOP. DO NOT PROCEED until user approves.**

---

### APPROVAL GATE 4 — Quality

```
PHASE 5 COMPLETE — QUALITY CHECK REVIEW
══════════════════════════════════════════════
Project : <name>  |  Rev : <revision>

QUALITY CHECK RESULT: PASS / FAIL

REQUIREMENTS TRACEABILITY
  Board dimensions  : required <W>×<H>mm → actual <W>×<H>mm  ✓/⚠
  Layer count       : required <N>        → actual <N>         ✓/⚠
  All nets routed   : unrouted = 0                             ✓/⚠
  Component count   : required <N>        → BOM <N>            ✓/⚠
  DRC clean         : 0 errors                                 ✓/⚠
  Board outline     : Edge.Cuts present                        ✓/⚠

DFM CHECKS
  Min drill         : <value>mm  (≥ 0.3mm)  ✓/⚠
  Copper-to-edge    : <value>mm  (≥ 0.5mm)  ✓/⚠
  Silkscreen on pads: <none / list>          ✓/⚠

COMPONENT FOOTPRINT VERIFICATION (Re-check)
  <Paste the Component Footprint Verification table from pcb-finalize,
   or "All components from standard KiCad library — no re-check needed">

GAPS / ISSUES
  <List or "None — all requirements met">

─────────────────────────────────────────────
Reply "approve quality" to generate manufacturing files.
══════════════════════════════════════════════
```
**STOP. DO NOT PROCEED until user approves.**

---

### Final Export Summary

```
MANUFACTURING EXPORT COMPLETE
══════════════════════════════════════════════
Project  : <name>  |  Rev : <revision>  |  Date : <today>
Fab house: <JLCPCB / PCBWay / OSHPark>

BOARD SUMMARY
  Dimensions : <W>mm × <H>mm  |  Layers: 2  |  Finish: HASL

COMPONENT SUMMARY
  Total: <count>  |  Unique types: <count>

ROUTING SUMMARY
  Vias: <count>  |  DRC (final): PASS — 0 violations

DELIVERABLES  (all in <project_path>/fab/)
  gerbers/        ← Gerber layers + drill files
  assembly/       ← BOM CSV, pick-and-place CPL
  3d/             ← STEP model
  docs/           ← PCB PDF, schematic PDF
  ★ <name>.zip   ← UPLOAD THIS FILE to fab order page

JLCPCB assembly: also upload BOM and CPL from assembly/ separately.
══════════════════════════════════════════════
```

---

## Standing Rules

1. Complete each step fully before starting the next.
2. Never advance past a gate without explicit user approval. Do not self-approve.
3. After any design change: re-run the relevant check and quality before export.
4. Record `project_path` and `requirements_path` after Phase 0. Include in every response:
   ```
   [project_path=... | req_path=... | phase=... | step=...]
   ```
5. Before routing, `unconnected_count` in DRC is normal. After routing it must be 0.
6. If any sub-agent errors: stop, report exact error text, wait for guidance.
7. Use `pcb_status(project_path)` to check project state without modifying anything.
8. The fab ZIP is the final deliverable. Always present its full path.
9. Do NOT call `run_erc` — it crashes (SIGSEGV). `pcb_schematic` runs preflight automatically.
10. Context management: on long sessions, summarise completed phases into a compact status
    block (paths, component count, current phase/step, unresolved warnings).
