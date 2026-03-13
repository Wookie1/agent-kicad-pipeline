---
name: "kicad-schematic-design"
description: "Build a complete KiCad schematic: search libraries, place symbols, draw wires, add net labels, place power ports, assign footprints to all components. Use after project initialization to create the circuit schematic before PCB layout."
version: "1.2.0"
author: "kicad-pcb-skills"
tags: ["kicad", "schematic", "symbols", "wiring", "netlist", "components"]
trigger_patterns:
  - "create schematic"
  - "draw schematic"
  - "place components"
  - "add components to schematic"
  - "wire schematic"
  - "build circuit"
---

# KiCad Schematic Design

## Overview
Places all components, connects them with wires and net labels, adds power symbols, and assigns footprints. Work in this order: **calculate → find → place → assign footprints → wire → power → preflight**. Never skip steps.

## Prerequisites
- `kicad-project-init` complete; `schematic_path` known
- Custom symbols/footprints created if needed
- Full BOM: every component's reference, value, lib_id, and footprint

---

## Step 0 — Calculate values BEFORE placing (DO THIS FIRST)

### LED current-limiting resistors
```
R = (V_supply - n × V_forward) / I_forward
P = I² × R  →  choose package with rating ≥ 2× P
```
**Automotive designs:** Always calculate at **14.4V** (engine running), not 12V.

### Package power ratings
| Package | Max continuous |
|---------|---------------|
| 0402 | 63 mW |
| 0603 | 100 mW |
| 0805 | 125 mW |
| 1206 | 250 mW |
| 2512 | 1 W |

**Required margin:** rated power ≥ 2× calculated dissipation at worst-case voltage.


### Standard Resistor Values (E24 Series)
**Always use standard E24 values unless otherwise directed:**
10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91
(Multiplied by powers of 10: 1.0Ω to 10MΩ)

**Calculation rule:** After calculating R = V/I, round to the **nearest E24 value**.
Acceptable deviation: ±20% (E24 tolerance). For precision circuits, use E96 series.

### Standard Capacitor Values (E12 Series)
**Always use standard E12 values unless otherwise directed:**
10, 15, 22, 33, 47, 68
(Multiplied by powers of 10: 1pF to 10,000µF)

**Common values:** 100pF, 1nF, 10nF, 100nF, 1µF, 10µF, 100µF, 470µF

### Standard Voltage Ratings
**Capacitors:** 6.3V, 10V, 16V, 25V, 35V, 50V, 63V, 100V, 200V, 400V, 630V
**Required margin:** V_rated ≥ 1.5× V_supply (ceramic), ≥ 2× V_supply (electrolytic)

**Resistors:** 1/10W, 1/8W, 1/4W, 1/2W, 1W, 2W, 5W
**Required margin:** P_rated ≥ 2× P_calculated

**Do not proceed until all component values are validated against standard series.**

Do not proceed until all component values are validated.

---

---

## ⭐ Footprint ID Quick Reference

> **CRITICAL:** Always use the FULL footprint name with metric suffix. Abbreviated names
> (e.g. `R_0603`) will NOT load — they don't exist in the library. `Device:LED_0603`
> is a **symbol** lib path, not a footprint.

### Resistors
| Package | Footprint ID |
|---------|--------------|
| 0402 | `Resistor_SMD:R_0402_1005Metric` |
| 0603 | `Resistor_SMD:R_0603_1608Metric` |
| 0805 | `Resistor_SMD:R_0805_2012Metric` |
| 1206 | `Resistor_SMD:R_1206_3216Metric` |
| 2512 (1W) | `Resistor_SMD:R_2512_6332Metric` |

### Capacitors
| Package | Footprint ID |
|---------|--------------|
| 0402 | `Capacitor_SMD:C_0402_1005Metric` |
| 0603 | `Capacitor_SMD:C_0603_1608Metric` |
| 0805 | `Capacitor_SMD:C_0805_2012Metric` |
| 1206 | `Capacitor_SMD:C_1206_3216Metric` |

### LEDs — Standard SMD
| Package | Footprint ID |
|---------|--------------|
| 0402 | `LED_SMD:LED_0402_1005Metric` |
| 0603 | `LED_SMD:LED_0603_1608Metric` |
| 0805 | `LED_SMD:LED_0805_2012Metric` |
| 1206 | `LED_SMD:LED_1206_3216Metric` |

### LEDs — PLCC (commonly used by user)
| Package | Footprint ID | Notes |
|---------|--------------|-------|
| PLCC-2 (3.4×3.0mm) | `LED_SMD:LED_PLCC-2_3.4x3.0mm_AK` | Most common generic single LED, AK=Anode-Kathode orientation |
| PLCC-2 (3×2mm) | `LED_SMD:LED_PLCC-2_3x2mm_AK` | Smaller body variant |
| PLCC-4 Cree (3.2×2.8mm) | `LED_SMD:LED_Cree-PLCC4_3.2x2.8mm_CCW` | General PLCC-4 LED |
| PLCC-4 SK6812 / WS2812 (5×5mm) | `LED_SMD:LED_OPSCO_SK6812_PLCC4_5.0x5.0mm_P3.1mm` | Addressable RGB LEDs |
| PLCC-4 Cree (5×5mm) | `LED_SMD:LED_Cree-PLCC4_5x5mm_CW` | High-power single color |
| PLCC-6 RGB Cree (6×5mm) | `LED_SMD:LED_RGB_Cree-PLCC-6_6x5mm_P2.1mm` | RGB LED |
| PLCC-6 Inolux RGB (5×5.5mm) | `LED_SMD:LED_Inolux_IN-P55TATRGB_PLCC6_5.0x5.5mm_P1.8mm` | RGB LED |
| PLCC-6 Cree (4.7×1.5mm) | `LED_SMD:LED_Cree-PLCC6_4.7x1.5mm` | Narrow body RGB |
| miniPLCC 2835 | `LED_SMD:LED_PLCC_2835` | Common WS2812B-compatible |

### ICs
| Package | Footprint ID |
|---------|--------------|
| DIP-8 | `Package_DIP:DIP-8_W7.62mm` |
| SOIC-8 | `Package_SO:SOIC-8_3.9x4.9mm_P1.27mm` |
| SOIC-14 | `Package_SO:SOIC-14_3.9x8.7mm_P1.27mm` |
| SOIC-16 | `Package_SO:SOIC-16_3.9x9.9mm_P1.27mm` |
| SOT-23 | `Package_TO_SOT_SMD:SOT-23` |
| SOT-223 | `Package_TO_SOT_SMD:SOT-223-3_TabPin2` |
| TSSOP-20 | `Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm` |
| QFP-32 | `Package_QFP:LQFP-32_7x7mm_P0.8mm` |

### Connectors
| Package | Footprint ID |
|---------|--------------|
| 2-pin 2.54mm header | `Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical` |
| 3-pin 2.54mm header | `Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical` |
| 4-pin 2.54mm header | `Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical` |
| USB Micro-B | `Connector_USB:USB_Micro-B_Wuerth_629105150521` |
| USB-C 2.0 | `Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12` |
| JST PH 2-pin | `Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal` |

---

## Step 1 — Find lib_ids
For every component, find its correct library symbol:
```
search_symbol_libraries(query="STM32F103")
get_symbol_details(lib_id="MCU_ST_STM32F1:STM32F103C8Tx")
```
Record the full `lib_id` for each component.

---


### ALL designs: batch_schematic.py (PREFERRED — use this instead of individual MCP calls)

> **Why batch?** Placing symbols one-by-one with MCP calls (~40 calls for a small design)
> takes 3–5 minutes and creates intermediate partially-written files that can appear corrupt.
> `batch_schematic.py` writes the entire schematic in ONE pass — seconds, not minutes.

**Step 1:** Write a `schematic_config.json` describing all components, power ports, net labels, and wires:
```json
{
  "symbols": [   ← also accepted: "components" (both keys work)
    {"ref":"U1","lib_id":"Timer:NE555","value":"NE555",
     "footprint":"Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
     "x":50.8,"y":35.56,"angle":0},
    {"ref":"R1","lib_id":"Device:R","value":"10k",
     "footprint":"Resistor_SMD:R_0603_1608Metric",
     "x":30.48,"y":25.4,"angle":0}
  ],
  "power_ports": [
    {"name":"VCC","x":50.8,"y":20.32},
    {"name":"GND","x":50.8,"y":60.96}
  ],
  "net_labels": [
    {"name":"OUT","x":71.12,"y":35.56,"angle":0}
  ],
  "wires": [
    [[25.4,25.4],[40.64,25.4],[40.64,35.56]]
  ]
}
```

**Step 2:** Run the batch script:
```bash
python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-schematic-design/scripts/batch_schematic.py   /path/to/schematic_config.json   /path/to/board.kicad_sch   --preflight
```

The `--preflight` flag runs `schematic_preflight.py` automatically after writing.
The script produces: `batch_schematic: wrote N symbols, M power ports, K net labels, W wire segments`

> **Use MCP individual calls ONLY** if you need to append a single component to an existing schematic.

## Step 2 — Place symbols (fallback: individual MCP calls)

### Small designs (≤15 components): MCP tool calls
```
add_schematic_symbol(
  schematic_path = "/path/to/board.kicad_sch",
  lib_id         = "Device:R",
  reference      = "R1",
  value          = "10k",
  x              = 25.4,
  y              = 25.4,
  angle          = 0,
  footprint      = "Resistor_SMD:R_0402_1005Metric"
)
```

**Coordinate system:** Origin top-left; X right, Y down; all mm. Use **2.54mm grid** — all coordinates must be multiples of 2.54.

**Small design grid** (4 per row, 15.24mm × 10.16mm spacing, start at 25.4, 25.4):
| Row | Col 0 | Col 1 | Col 2 | Col 3 |
|-----|-------|-------|-------|-------|
| 0 | (25.4, 25.4) | (40.64, 25.4) | (55.88, 25.4) | (71.12, 25.4) |
| 1 | (25.4, 35.56) | (40.64, 35.56) | … | … |

### LED/Diode array designs: LED string batch script
```bash
python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-schematic-design/scripts/batch_led_strings.py \
  /path/to/board.kicad_sch \
  /path/to/strings_config.json
```
The script writes all symbols, wires, net labels, and power ports in a single pass. Use this for LED string arrays only.

To regenerate strings after changing the config (rebuild mode):
```bash
python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-schematic-design/scripts/batch_led_strings.py \
  --rebuild /path/to/board.kicad_sch
```

> ⚠️ **This script handles ONLY LED strings** (net_label → R → D1…Dn → GND).
> Do NOT use it for MCU circuits, resistor banks, connectors, or mixed designs.
> For those, place components individually using `add_schematic_symbol` MCP calls.

> **Important — Create schematic file FIRST:** Before running `batch_led_strings.py`,
> the `.kicad_sch` file must already exist. Use `create_schematic()` MCP tool first:
> ```
> create_schematic(path="/path/to/board.kicad_sch", title="My PCB")
> ```
> If the file already exists, `create_schematic` will return an error — that is OK,
> proceed to batch injection. The batch script will inject into the existing file.


---

## Step 3 — Assign footprints
Every component must have a footprint before proceeding.
```
assign_footprint(
  schematic_path = "/path/to/board.kicad_sch",
  reference      = "U1",
  footprint_id   = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
)
```
Search: `search_footprint_libraries(query="SOIC-8 3.9mm")`
Verify: `list_schematic_symbols(schematic_path="/path/to/board.kicad_sch")`

---

## Step 4 — Add power ports
```
add_power_port(schematic_path="/path/to/board.kicad_sch", name="+3V3", x=25.4, y=12.7)
add_power_port(schematic_path="/path/to/board.kicad_sch", name="GND",  x=30.48, y=12.7)
```
Standard net names: `GND`, `+3V3`, `+5V`, `+12V`, `VCC`, `VDD`, `VIN`, `VBAT`, `VBUS`

---

## Step 5 — Connect with wires
```
add_schematic_wire(schematic_path, x1=25.4, y1=25.4, x2=40.64, y2=25.4)
# Multi-segment:
add_schematic_wire_path(schematic_path, points=[[25.4,25.4],[25.4,30.48],[40.64,30.48]])
```
Net labels (for distant connections — more reliable than long wires):
```
add_net_label(schematic_path, name="SPI_MOSI", x=50.8, y=25.4, angle=0)
```
**Net label names are case-sensitive.** Two labels with the same name are electrically connected.

---

## Step 6 — Preflight check
```bash
python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-schematic-design/scripts/schematic_preflight.py /path/to/board.kicad_sch
```
Checks: duplicate references, missing footprints, single-use power nets, dangling labels, paren balance, sheet_instances block. Fix all reported errors before running ERC.

---

## KiCad 9.0 Reference Designator Requirements
KiCad 9.0 requires two blocks for references to display correctly:
1. **`(instances)` block** inside each placed symbol — handled by `add_schematic_symbol`
2. **`(sheet_instances (path "/" (page "1")))`** at root level — must exist in the schematic file

If references show as `R?`, `D?` etc.: verify `(sheet_instances)` is present near the end of the `.kicad_sch` file. The preflight check catches this automatically.

---

## Critical Mistakes to Avoid
- Placing the same reference twice — causes ERC duplicate error
- Using `add_schematic_symbol` for GND/VCC — use `add_power_port` instead
- Leaving any component without a footprint — `update_pcb_from_schematic` will fail
- Net labels that don't match exactly — `GND` ≠ `Gnd`
- Coordinates not on 2.54mm grid — pins won't connect to wires

## Success Criteria
- Step 0 calculation table complete, no over-rated components
- `list_schematic_symbols` returns every expected component
- All references unique, all footprints assigned
- Preflight script reports 0 errors

## Next Skill
→ **kicad-run-erc** to validate the schematic electrically
