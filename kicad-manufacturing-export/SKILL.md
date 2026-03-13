# KiCad Manufacturing Export

## Overview
Generates all manufacturing files: Gerbers, drill, BOM, pick-and-place, assembly drawing,
IPC-356 netlist, STEP 3D model, schematic PDF, PCB PDF, and a ZIP fab package.
**Run only after routing is 100% complete and DRC is clean (0 violations, 0 unconnected).**

## Prerequisites
- Routing complete (`kicad-route-pcb` done)
- DRC clean: run `kicad-cli pcb drc` → 0 violations, 0 unconnected
  - **Use `drc_pre_export.json` as the authoritative DRC file**
  - **Ignore `drc_report.json` and `drc_final*.json` — these are intermediate files**
- `pcb_path`, `schematic_path`, `project_dir` known

## Routing Verification

> ⚠️ **Do NOT use `track_count` from `get_pcb_statistics` to verify routing.**
> KiCad 9 stores tracks in a format that some tools report as 0 even when routes exist.
> Always verify routing by running kicad-cli DRC and checking `unconnected_count == 0`.

```bash
# Run fresh DRC to verify routing
DISPLAY=:99 kicad-cli pcb drc \
  --output /path/to/project/drc_pre_export.json \
  --format json \
  /path/to/board.kicad_pcb

# Check result
python3 -c "
import json
d = json.load(open('/path/to/project/drc_pre_export.json'))
v = d.get('violations', [])
unconnected = [x for x in v if x.get('type') == 'unconnected_items']
blocking = [x for x in v if x.get('severity') == 'error']
print(f'Unconnected: {len(unconnected)}, Blocking errors: {len(blocking)}')
if len(unconnected) == 0 and len(blocking) == 0:
    print('ROUTING VERIFIED COMPLETE')
else:
    print('ROUTING INCOMPLETE - fix before export')
"
```

## Step 1 — Clean up intermediate DRC files

Before quality check, remove intermediate DRC files to prevent confusion:
```bash
cd /path/to/project_dir
# Archive intermediate DRC files
for f in drc_report.json drc_final.json drc_final2.json drc_final3.json \
         drc_final4.json drc_final5.json drc_final6.json; do
  [ -f "$f" ] && mv "$f" "${f%.json}.json.archived" && echo "archived $f"
done
# drc_pre_export.json is now the only authoritative DRC file
```

## Step 2 — Export Gerbers
```bash
DISPLAY=:99 kicad-cli pcb export gerbers \
  --output /path/to/project/gerbers/ \
  --layers F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,F.Paste,B.Paste,Edge.Cuts,F.Fab,B.Fab \
  --use-drill-file-origin \
  /path/to/board.kicad_pcb
```

## Step 3 — Export Drill Files
```bash
DISPLAY=:99 kicad-cli pcb export drill \
  --output /path/to/project/gerbers/ \
  --format excellon \
  /path/to/board.kicad_pcb
```

## Step 4 — Export Pick-and-Place
```bash
DISPLAY=:99 kicad-cli pcb export pos \
  --output /path/to/project/assembly/pick_and_place.csv \
  --format csv \
  --units mm \
  /path/to/board.kicad_pcb
```

## Step 5 — Generate BOM

> ⚠️ **Do NOT use `kicad-cli pcb export bom` — it produces empty output when the
> .net file has 0 components (a known issue with batch_schematic.py output).**
> Use `generate_bom.py` instead — it reads directly from `schematic_config.json`.

```bash
python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-manufacturing-export/scripts/generate_bom.py \
  /path/to/project/schematic_config.json \
  /path/to/project/bom/board_bom.csv
```

Expected output:
```
BOM written: /path/to/bom/board_bom.csv  (6 line items, 8 total components)
  C1, C2       100nF  x2  Capacitor_SMD:C_0603_1608Metric
  D1           LED    x1  LED_SMD:LED_0603_1608Metric
  J1           Conn   x1  Connector_PinHeader...
  R1, R2, R3   10k    x3  Resistor_SMD:R_0603_1608Metric
  U1           NE555  x1  Package_DIP:DIP-8_W7.62mm
```

## Step 6 — Export Schematic PDF
```bash
DISPLAY=:99 kicad-cli sch export pdf \
  --output /path/to/project/board_schematic.pdf \
  /path/to/board.kicad_sch
```

## Step 7 — Export PCB PDF
```bash
DISPLAY=:99 kicad-cli pcb export pdf \
  --output /path/to/project/board_pcb.pdf \
  --layers F.Cu,B.Cu,F.SilkS,Edge.Cuts \
  /path/to/board.kicad_pcb
```

## Step 8 — Export STEP 3D Model
```bash
DISPLAY=:99 kicad-cli pcb export step \
  --output /path/to/project/3d/board.step \
  /path/to/board.kicad_pcb
```

## Step 9 — Export IPC-356 Netlist
```bash
DISPLAY=:99 kicad-cli pcb export ipc356 \
  --output /path/to/project/board.ipc \
  /path/to/board.kicad_pcb
```

## Step 10 — Generate Assembly Drawing

> ⚠️ **Use `--out` flag, NOT a positional argument for the output path.**
> The script uses argparse and only accepts `--out OUTPUT_SVG`.

```bash
# CORRECT:
python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-manufacturing-export/scripts/kicad_assembly_drawing.py \
  /path/to/board.kicad_pcb \
  --out /path/to/project/assembly/assembly_front.svg \
  --side front

# WRONG (do NOT do this):
# python3 kicad_assembly_drawing.py board.kicad_pcb /path/to/assembly/
```

Expected output: `Assembly drawing written: /path/to/assembly/assembly_front.svg`

## Step 11 — Create Fab ZIP Package
```bash
python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-manufacturing-export/scripts/create_fab_zip.py \
  /path/to/project_dir/
```

The script auto-detects the project name from `.kicad_pro` and creates:
`<project_name>_fab_<YYYYMMDD>.zip` in the project directory.

Expected output:
```
  + gerbers/board-F_Cu.gtl  (25886 bytes)
  + gerbers/board.drl  (530 bytes)
  + bom/board_bom.csv  (412 bytes)
  + assembly/pick_and_place.csv  (581 bytes)
  + 3d/board.step  (23975 bytes)
  + board_schematic.pdf  (16450 bytes)
  + board_pcb.pdf  (27408 bytes)
  + board.ipc  (1675 bytes)

Fab ZIP: /path/to/project/board_fab_20260311.zip
Size: 45231 bytes  |  Files: 22
```

## File Size Validation

Verify ALL output files are non-empty before reporting success:

| File | Min expected size |
|------|-------------------|
| `gerbers/*-F_Cu.gtl` | > 1 KB |
| `gerbers/*.drl` | > 100 bytes |
| `bom/*.csv` | > 100 bytes (if only headers: 48 bytes = FAIL) |
| `assembly/pick_and_place.csv` | > 100 bytes |
| `3d/*.step` | > 10 KB |
| `*_schematic.pdf` | > 5 KB |
| `*_pcb.pdf` | > 10 KB |
| `*.ipc` | > 500 bytes |
| `assembly/assembly_front.svg` | > 5 KB |
| `*_fab_*.zip` | > 20 KB |

If any file fails the size check, **do not report success** — regenerate that file.

## Scripts Reference

| Script | Purpose | Usage |
|--------|---------|-------|
| `generate_bom.py` | BOM from schematic_config.json | `python3 generate_bom.py <config.json> <output.csv>` |
| `kicad_assembly_drawing.py` | Assembly SVG | `python3 kicad_assembly_drawing.py <pcb> --out <output.svg>` |
| `create_fab_zip.py` | ZIP all outputs | `python3 create_fab_zip.py <project_dir> [output.zip]` |
