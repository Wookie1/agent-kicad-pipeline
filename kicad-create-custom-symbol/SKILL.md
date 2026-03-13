---
name: "kicad-create-custom-symbol"
description: "Create a custom KiCad schematic symbol (.kicad_sym) for components that do not exist in standard KiCad libraries. Generates the symbol file and registers it in the project's sym-lib-table. Use before kicad-schematic-design whenever a novel IC, connector, or module needs a custom symbol."
version: "1.1.0"
author: "kicad-pcb-skills"
tags: ["kicad", "schematic", "symbol", "custom", "library", "kicad_sym"]
trigger_patterns:
  - "custom symbol"
  - "create symbol"
  - "new schematic symbol"
  - "symbol not in library"
  - "custom ic symbol"
  - "add component symbol"
---

# Create Custom KiCad Schematic Symbol

## Overview
Builds a `.kicad_sym` library file from a JSON specification and registers it in `sym-lib-table`. Supports `auto_layout` (preferred) and explicit pin geometry.

## Pin Direction Reference
| Direction | Use for |
|-----------|---------|
| `power_in` | VCC, VDD, AVCC, VBUS supply pins |
| `power_out` | Regulated output pins |
| `input` | Control signals, CS, CLK, RESET |
| `output` | Data out, status, interrupt |
| `bidirectional` | SDA, GPIO, shared bus lines |
| `passive` | Resistor, cap, crystal pins |
| `no_connect` | Intentionally unused pins |

## Step 1 — Build the symbol spec JSON
Use `auto_layout` for ICs (preferred):
```json
[
  {
    "name": "MY_CUSTOM_IC",
    "reference_prefix": "U",
    "value": "MY_CUSTOM_IC",
    "description": "Custom 8-pin controller",
    "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "auto_layout": {
      "left_pins":  ["1:VDD:power_in", "2:GND:power_in", "3:~{RESET}:input"],
      "right_pins": ["4:MOSI:input", "5:MISO:output", "6:SCK:input",
                     "7:~{CS}:input", "8:INT:output"]
    }
  }
]
```
Pin string format: `"pin_number:pin_name:direction"`. Use `~{NAME}` for active-low signals.

For connectors (explicit geometry):
```json
{
  "name": "MY_CONNECTOR",
  "reference_prefix": "J",
  "body_style": "rectangle",
  "body_x": -2.54, "body_y": -7.62,
  "body_w": 5.08, "body_h": 15.24,
  "pins": [
    {"number":"1","name":"VCC","direction":"power_in","x":-5.08,"y":2.54,"angle":0,"length":2.54},
    {"number":"2","name":"GND","direction":"power_in","x":-5.08,"y":0,"angle":0,"length":2.54},
    {"number":"3","name":"TX","direction":"output","x":5.08,"y":2.54,"angle":180,"length":2.54},
    {"number":"4","name":"RX","direction":"input","x":5.08,"y":0,"angle":180,"length":2.54}
  ]
}
```

## Step 2 — Generate the .kicad_sym file
```bash
/a0/usr/skills-venv/bin/python3 scripts/kicad_symbol_builder.py /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/spec.json \
  --out /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/my_custom_lib.kicad_sym
```

## Step 3 — Register the library
```bash
/a0/usr/skills-venv/bin/python3 scripts/update_sym_lib_table.py \
  --project /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/<project_name>.kicad_pro \
  --lib-name "my_custom_lib" \
  --lib-path /a0/usr/projects/pcb-design/workspace/pcb/<project_name>/my_custom_lib.kicad_sym
```

## Step 4 — Verify
```
search_symbol_libraries(query="MY_CUSTOM_IC")
get_symbol_details(lib_id="my_custom_lib:MY_CUSTOM_IC")
```
Record the `lib_id` (`"my_custom_lib:MY_CUSTOM_IC"`) for use in `add_schematic_symbol`.

## Symbol Layout Rules
- Left side: inputs (signals flow left → right)
- Right side: outputs
- Top: VCC/VDD; Bottom: GND
- Pin spacing: always 2.54mm — never deviate

## Success Criteria
- Script exits with code 0, file exists at `--out` path
- `search_symbol_libraries` returns the symbol
- `get_symbol_details` shows correct pin count and names

## Error Recovery
| Error | Fix |
|-------|-----|
| `sym-lib-table not found` | `update_sym_lib_table.py` creates it if absent |
| Symbol not found in search | Check library name is case-matching |
| Wrong pin count | Verify `auto_layout` left + right sum equals total pins |

## Next Skill
→ **kicad-create-custom-footprint** if the package also needs a custom footprint
→ **kicad-schematic-design** to start placing symbols
