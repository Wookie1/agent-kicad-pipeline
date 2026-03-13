import json
#!/usr/bin/env python3
"""
pcb_layout_full.py  v1.0.0

Runs the COMPLETE PCB layout pipeline in one script call:
  1. Sync schematic footprints to PCB (via sch_to_pcb_sync logic)
  2. Upgrade PCB format (pcbnew LoadBoard/Save)
  3. Set board outline rectangle (Edge.Cuts)
  4. Place all components from groups.json
  5. Add GND copper fills on F.Cu and B.Cu
  6. Run DRC and report violations

Usage:
  DISPLAY=:99 python3 pcb_layout_full.py \
    --schematic /path/to/board.kicad_sch \
    --pcb       /path/to/board.kicad_pcb \
    --groups    /path/to/groups.json \
    --width     30 \
    --height    20

groups.json format:
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

All coordinates in mm. Requires DISPLAY=:99 for pcbnew.
Use system python3 (has pcbnew), NOT skills-venv.
"""
import sys, re, json, subprocess, argparse
from pathlib import Path

sys.path.insert(0, '/usr/lib/python3/dist-packages')
# Suppress pcbnew/wxPython 'duplicate image handler' debug noise
import os as _os
_devnull = open(_os.devnull, 'w')
import sys as _sys
_old_stderr = _sys.stderr
_sys.stderr = _devnull
import pcbnew
_sys.stderr = _old_stderr
_devnull.close()

# ── Helpers ───────────────────────────────────────────────────────────────────

def mm(v):
    """Convert mm to KiCad internal units."""
    return pcbnew.FromMM(v)


def load_board(pcb_path):
    board = pcbnew.LoadBoard(pcb_path)
    if board is None:
        raise RuntimeError(f"pcbnew.LoadBoard returned None for {pcb_path}")
    return board


# ── Step 1: Sync schematic footprints to PCB ──────────────────────────────────

def sync_schematic(sch_path, pcb_path):
    """Parse schematic and place footprints onto PCB via pcbnew."""
    sch_text = Path(sch_path).read_text(encoding='utf-8')
    # F2: File-type validation — detect if schematic was accidentally overwritten
    if sch_text.strip().startswith('(kicad_pcb'):
        msg = ('CRITICAL: ' + str(sch_path) + ' contains PCB data, not schematic data! '
               'The .kicad_sch file was accidentally overwritten with PCB content. '
               'Restore from backup (.bak_before_fp_fix or similar) before continuing.')
        raise RuntimeError(msg)
    if not sch_text.strip().startswith('(kicad_sch'):
        print(f'WARNING: {sch_path} does not start with (kicad_sch — may be malformed')

    # Parse components
    components = []
    pattern = re.compile(r'\(symbol[\s(]*lib_id\s+"([^"]+)"')
    for m in pattern.finditer(sch_text):
        start = m.start()
        lib_id = m.group(1)
        if lib_id.startswith('power:'):
            continue
        depth, end = 0, start
        for i, ch in enumerate(sch_text[start:], start):
            if ch == '(': depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        block = sch_text[start:end]
        ref_m = re.search(r'"Reference"\s+"([^"]+)"', block)
        fp_m  = re.search(r'"Footprint"\s+"([^"]+)"', block)
        val_m = re.search(r'"Value"\s+"([^"]+)"', block)
        if not ref_m: continue
        ref = ref_m.group(1)
        if ref.startswith('#'): continue
        if not fp_m or not fp_m.group(1): continue
        footprint = fp_m.group(1)
        value = val_m.group(1) if val_m else ref
        components.append({'ref': ref, 'footprint': footprint, 'value': value})

    # Deduplicate
    seen, deduped = set(), []
    for c in components:
        if c['ref'] not in seen:
            seen.add(c['ref'])
            deduped.append(c)

    FP_LIB = '/kicad-support/footprints'
    # Load existing board to preserve library tables (critical for FootprintLoad)
    board = pcbnew.LoadBoard(pcb_path) if Path(pcb_path).exists() else pcbnew.BOARD()
    if board is None:
        board = pcbnew.BOARD()
    board.SetFileName(pcb_path)

    # Remove existing footprints to prevent duplicates on re-run
    for fp in list(board.GetFootprints()):
        board.Remove(fp)

    placed, failed = 0, []
    for comp in deduped:
        parts = comp['footprint'].split(':')
        if len(parts) != 2:
            failed.append(f"{comp['ref']}: bad footprint '{comp['footprint']}'")
            continue
        lib_name, fp_name = parts
        lib_path = f'{FP_LIB}/{lib_name}.pretty'
        try:
            fp = pcbnew.FootprintLoad(lib_path, fp_name)
            if fp is None:
                # Suggest correct name by listing library contents
                lib_dir = Path(lib_path)
                suggestions = []
                if lib_dir.exists():
                    mods = [f.stem for f in lib_dir.glob('*.kicad_mod')]
                    suggestions = [m for m in mods if fp_name.lower()[:4] in m.lower()][:3]
                hint = f" — did you mean: {', '.join(suggestions)}?" if suggestions else ""
                sym_hint = " (NOTE: this looks like a SYMBOL lib path, not a footprint!)" if lib_name in ('Device','power','Timer','Connector') else ""
                failed.append(f"{comp['ref']}: '{comp['footprint']}' not found{hint}{sym_hint}")
                continue
            fp.SetReference(comp['ref'])
            fp.SetValue(comp['value'])
            board.Add(fp)
            placed += 1
        except Exception as e:
            failed.append(f"{comp['ref']}: {e}")

    # Load net_assignments from schematic_config.json if available (reliable net assignment)
    config_path = Path(sch_path).parent / 'schematic_config.json'
    net_assigned = 0
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            net_assignments = cfg.get('net_assignments', {})
            if net_assignments:
                net_cache = {}
                for fp_obj in board.GetFootprints():
                    ref = fp_obj.GetReference()
                    if ref not in net_assignments:
                        continue
                    for pad in fp_obj.Pads():
                        pad_name = pad.GetName()
                        net_name = net_assignments[ref].get(pad_name,
                                   net_assignments[ref].get(str(pad_name), ''))
                        if net_name:
                            if net_name not in net_cache:
                                ni = pcbnew.NETINFO_ITEM(board, net_name)
                                board.Add(ni)
                                net_cache[net_name] = ni
                            pad.SetNet(net_cache[net_name])
                            net_assigned += 1
                print(f'[sync] Net assignments applied: {net_assigned} pads across {len(net_cache)} nets')
        except Exception as e:
            print(f'[sync] Warning: net_assignments error: {e}')

    board.Save(pcb_path)
    print(f'[sync] Placed {placed}/{len(deduped)} footprints')
    if net_assigned == 0:
        print('[sync] WARNING: 0 net assignments — check net_assignments in schematic_config.json')
    if failed:
        print(f'[sync] Failed: {failed}')
    return placed


# ── Step 2: Upgrade PCB format ────────────────────────────────────────────────

def upgrade_format(pcb_path):
    board = load_board(pcb_path)
    board.Save(pcb_path)
    print('[upgrade] PCB format upgraded')


# ── Step 3: Set board outline ─────────────────────────────────────────────────

def set_outline(pcb_path, width, height, x0=0.0, y0=0.0):
    board = load_board(pcb_path)
    # Remove existing Edge.Cuts
    for item in list(board.GetDrawings()):
        if item.GetLayer() == pcbnew.Edge_Cuts:
            board.Remove(item)
    # Add rectangle
    corners = [
        (x0, y0), (x0 + width, y0),
        (x0 + width, y0 + height), (x0, y0 + height)
    ]
    for i in range(4):
        x1, y1 = corners[i]
        x2, y2 = corners[(i + 1) % 4]
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetLayer(pcbnew.Edge_Cuts)
        seg.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
        seg.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
        seg.SetWidth(mm(0.05))
        board.Add(seg)
    board.Save(pcb_path)
    print(f'[outline] Board outline set: {width}×{height}mm at ({x0},{y0})')


# ── Step 4: Place components from groups.json ─────────────────────────────────

def place_components(pcb_path, groups):
    board = load_board(pcb_path)
    fp_map = {fp.GetReference(): fp for fp in board.GetFootprints()}

    placed = 0
    for group in groups:
        origin = group['origin']           # [x, y] in mm
        cols = max(1, group.get('cols', 1))
        col_spacing = group.get('col_spacing', 6.0)
        row_spacing = group.get('row_spacing', 6.0)
        refs = group.get('refs', [])

        for idx, ref in enumerate(refs):
            if ref not in fp_map:
                print(f'[place] WARNING: {ref} not found on PCB')
                continue
            col = idx % cols
            row = idx // cols
            x = origin[0] + col * col_spacing
            y = origin[1] + row * row_spacing
            fp = fp_map[ref]
            fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            placed += 1

    board.Save(pcb_path)
    print(f'[place] Placed {placed} components')
    return placed


# ── Step 5: Add GND copper fills ──────────────────────────────────────────────

def add_gnd_fills(pcb_path, width, height, x0=0.0, y0=0.0, clearance=0.3):
    board = load_board(pcb_path)
    net_gnd = board.FindNet('GND')
    if net_gnd is None:
        ni = pcbnew.NETINFO_ITEM(board, 'GND')
        board.Add(ni)
        net_gnd = board.FindNet('GND')

    margin = 0.5
    corners = pcbnew.VECTOR_VECTOR2I([
        pcbnew.VECTOR2I(mm(x0 + margin), mm(y0 + margin)),
        pcbnew.VECTOR2I(mm(x0 + width - margin), mm(y0 + margin)),
        pcbnew.VECTOR2I(mm(x0 + width - margin), mm(y0 + height - margin)),
        pcbnew.VECTOR2I(mm(x0 + margin), mm(y0 + height - margin)),
    ])

    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        zone = pcbnew.ZONE(board)
        zone.SetLayer(layer)
        zone.SetNet(net_gnd)
        zone.SetLocalClearance(mm(clearance))
        zone.SetMinThickness(mm(0.25))
        # Use FULL (solid) pad connection to prevent thermal relief DRC violations
        try:
            zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        except Exception:
            pass  # Older API versions may not support this
        outline = zone.Outline()
        outline.NewOutline()
        for pt in corners:
            outline.Append(pt.x, pt.y)
        board.Add(zone)

    board.Save(pcb_path)
    print('[fills] GND copper fills added on F.Cu and B.Cu')


# ── Step 6: Run DRC ───────────────────────────────────────────────────────────

def refill_zones(pcb_path):
    """Refill copper zones after routing to ensure all zone fills are current."""
    board = load_board(pcb_path)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    board.Save(pcb_path)
    print('[refill] Copper zones refilled')


def run_drc(pcb_path, report_path):
    result = subprocess.run(
        ['kicad-cli-xvfb', 'pcb', 'drc',
         '--output', report_path,
         '--format', 'json',
         '--units', 'mm',
         pcb_path],
        capture_output=True, text=True
    )
    if not Path(report_path).exists():
        print(f'[drc] DRC report not generated. stderr: {result.stderr[:200]}')
        return -1, []

    NON_BLOCKING = {'lib_footprint_issues', 'silk_over_copper',
                    'track_dangling', 'solder_mask_bridge'}
    try:
        data = json.loads(Path(report_path).read_text())
        violations = data.get('violations', [])
        blocking = [v for v in violations
                    if v.get('type', '') not in NON_BLOCKING]
        non_block = len(violations) - len(blocking)
        print(f'[drc] {len(blocking)} blocking, {non_block} non-blocking violations')
        for v in blocking[:5]:
            print(f'  {v.get("type","?")} — {v.get("description","")[:80]}')
        return len(blocking), blocking
    except Exception as e:
        print(f'[drc] Error parsing report: {e}')
        return -1, []


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description='Full PCB layout pipeline: sync → upgrade → outline → place → fill → DRC')
    ap.add_argument('--schematic', required=True)
    ap.add_argument('--pcb',       required=True)
    ap.add_argument('--groups',    required=True, help='groups.json for component placement')
    ap.add_argument('--width',     type=float, required=True, help='Board width mm')
    ap.add_argument('--height',    type=float, required=True, help='Board height mm')
    ap.add_argument('--x0',        type=float, default=0.0, help='Board origin X (default 0)')
    ap.add_argument('--y0',        type=float, default=0.0, help='Board origin Y (default 0)')
    ap.add_argument('--skip-drc',  action='store_true', help='Skip DRC step')
    args = ap.parse_args()

    pcb_path = args.pcb
    sch_path = args.schematic
    groups_path = args.groups
    w, h = args.width, args.height
    x0, y0 = args.x0, args.y0

    groups = json.loads(Path(groups_path).read_text())
    report_path = str(Path(pcb_path).parent / 'drc_report.json')

    print(f'=== pcb_layout_full.py: {Path(pcb_path).stem} ({w}×{h}mm) ===')

    print('\n--- Step 1: Sync schematic → PCB ---')
    sync_schematic(sch_path, pcb_path)

    print('\n--- Step 2: Upgrade PCB format ---')
    upgrade_format(pcb_path)

    print('\n--- Step 3: Board outline ---')
    set_outline(pcb_path, w, h, x0, y0)

    print('\n--- Step 4: Place components ---')
    place_components(pcb_path, groups)

    print('\n--- Step 5: GND copper fills ---')
    add_gnd_fills(pcb_path, w, h, x0, y0)

    print('\n--- Step 5b: Refill zones ---')
    refill_zones(pcb_path)

    if not args.skip_drc:
        print('\n--- Step 6: DRC ---')
        blocking, _ = run_drc(pcb_path, report_path)
        if blocking == 0:
            print('[drc] ✅ PASS — 0 blocking violations')
        elif blocking > 0:
            print(f'[drc] ⚠️  {blocking} blocking violations — fix before routing')
        else:
            print('[drc] ⚠️  DRC did not run — check kicad-cli-xvfb')
    else:
        print('\n--- Step 6: DRC skipped ---')

    print(f'\n=== Layout complete: {pcb_path} ===')


if __name__ == '__main__':
    main()
