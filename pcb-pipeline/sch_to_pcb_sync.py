#!/usr/bin/env python3
"""
sch_to_pcb_sync.py  v1.4.0

Syncs a KiCad schematic to PCB:
  1. Places footprints from schematic (handles MCP + batch symbol formats)
  2. Assigns nets to pads by parsing schematic wires, labels, and power ports

Bypasses kicad-cli netlist export (broken for mixed-format schematics in headless Docker).

Usage:
  DISPLAY=:99 python3 sch_to_pcb_sync.py <schematic.kicad_sch> <board.kicad_pcb>
  DISPLAY=:99 python3 sch_to_pcb_sync.py <sch> <pcb> --width 80 --height 60

Footprint library path: /kicad-support/footprints/<LibName>.pretty
"""
import sys, re, math, argparse
from pathlib import Path

FP_LIB_DIR = '/kicad-support/footprints'
GRID = 0.0254  # 1 mil in mm — positions snapped to this grid


def _round(v, grid=0.254):
    """Round coordinate to grid."""
    return round(round(v / grid) * grid, 4)


def parse_components(sch_text):
    """Extract all real components (handles both MCP and batch symbol formats)."""
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
        if not ref_m:
            continue
        ref = ref_m.group(1)
        if ref.startswith('#'):
            continue
        fp_m  = re.search(r'"Footprint"\s+"([^"]+)"', block)
        val_m = re.search(r'"Value"\s+"([^"]+)"', block)
        at_m  = re.search(r'\(at\s+([\d.\-]+)\s+([\d.\-]+)', block)
        footprint = fp_m.group(1)  if fp_m  else ''
        value     = val_m.group(1) if val_m else ''
        x = float(at_m.group(1)) if at_m else 0.0
        y = float(at_m.group(2)) if at_m else 0.0
        if footprint:
            components.append({'ref': ref, 'lib_id': lib_id,
                               'footprint': footprint, 'value': value,
                               'x': x, 'y': y})
    # Deduplicate by ref
    seen, deduped = set(), []
    for c in components:
        if c['ref'] not in seen:
            seen.add(c['ref'])
            deduped.append(c)
    return deduped


def parse_nets(sch_text, components):
    """
    Build a net map: {(ref, pin_name): net_name} by tracing
    schematic wires and net labels from wire endpoint coordinates.

    Algorithm:
      1. Parse all wire segments → build adjacency graph (position → positions)
      2. Parse all net labels (including power ports) → {position: net_name}
      3. For each component pin, find its schematic position and walk the wire
         graph to reach a net label. That label's name is the net.
    """
    # Step 1: Build wire graph {(x,y) -> set of (x,y)}
    wire_graph = {}
    wire_pat = re.compile(
        r'\(wire\s+\(pts\s+\(xy\s+([\d.\-]+)\s+([\d.\-]+)\)\s+\(xy\s+([\d.\-]+)\s+([\d.\-]+)\)'
    )
    for m in wire_pat.finditer(sch_text):
        x1,y1,x2,y2 = float(m.group(1)),float(m.group(2)),float(m.group(3)),float(m.group(4))
        p1 = (_round(x1), _round(y1))
        p2 = (_round(x2), _round(y2))
        wire_graph.setdefault(p1, set()).add(p2)
        wire_graph.setdefault(p2, set()).add(p1)

    # Step 2: Parse net labels → {(x,y): net_name}
    labels = {}
    # Regular net labels
    label_pat = re.compile(r'\(label\s+"([^"]+)"\s+\(at\s+([\d.\-]+)\s+([\d.\-]+)')
    for m in label_pat.finditer(sch_text):
        name,x,y = m.group(1), float(m.group(2)), float(m.group(3))
        labels[(_round(x), _round(y))] = name

    # Power ports (their position IS the net connection point)
    pwr_pat = re.compile(
        r'\(symbol\s+\(lib_id\s+"power:([^"]+)"[^)]*\)\s+\(at\s+([\d.\-]+)\s+([\d.\-]+)'
    )
    for m in pwr_pat.finditer(sch_text):
        name,x,y = m.group(1), float(m.group(2)), float(m.group(3))
        labels[(_round(x), _round(y))] = name

    # Step 3: BFS from each label through wire graph to collect all connected positions
    net_at_pos = {}
    for start_pos, net_name in labels.items():
        if start_pos in net_at_pos:
            continue
        visited = {start_pos}
        queue = [start_pos]
        while queue:
            pos = queue.pop()
            net_at_pos[pos] = net_name
            for nb in wire_graph.get(pos, []):
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
                    if nb in labels:
                        net_at_pos[nb] = labels[nb]

    return net_at_pos, labels, wire_graph


def assign_nets_to_board(board, components, net_at_pos, config_net_assignments=None):
    """Assign nets to PCB pads.

    Priority:
    1. config_net_assignments dict: {ref: {pad_name: net_name}} — from schematic_config.json
    2. pad-position lookup in net_at_pos — schematic-coordinate based
    3. component-center lookup — last resort fallback
    """
    import pcbnew
    assigned = 0
    net_cache = {}

    def get_or_create_net(net_name):
        if net_name not in net_cache:
            ni = pcbnew.NETINFO_ITEM(board, net_name)
            board.Add(ni)
            net_cache[net_name] = ni
        return net_cache[net_name]

    comp_pos = {c['ref']: (c['x'], c['y']) for c in components}

    for fp in board.GetFootprints():
        ref = fp.GetReference()

        for pad in fp.Pads():
            pad_name = pad.GetName()
            net_name = ''

            if config_net_assignments and ref in config_net_assignments:
                net_name = config_net_assignments[ref].get(pad_name, '')
                if not net_name:
                    net_name = config_net_assignments[ref].get(str(pad_name), '')

            if not net_name and ref in comp_pos:
                pad_pos = pad.GetPosition()
                pad_x_mm = pad_pos.x / 1e6
                pad_y_mm = pad_pos.y / 1e6
                pos_rounded = (_round(pad_x_mm), _round(pad_y_mm))
                net_name = net_at_pos.get(pos_rounded, '')

            if not net_name and ref in comp_pos:
                sx, sy = comp_pos[ref]
                pos_rounded = (_round(sx), _round(sy))
                net_name = net_at_pos.get(pos_rounded, '')

            if net_name:
                pad.SetNet(get_or_create_net(net_name))
                assigned += 1

    return assigned


def sync(sch_path, pcb_path, board_w=None, board_h=None):
    sys.path.insert(0, '/usr/lib/python3/dist-packages')
    import pcbnew

    sch_text = Path(sch_path).read_text(encoding='utf-8')
    components = parse_components(sch_text)
    net_at_pos, labels, wire_graph = parse_nets(sch_text, components)

    print(f'Found {len(components)} components with footprints')
    print(f'Found {len(labels)} net labels/power ports')
    print(f'Wire graph: {len(wire_graph)} nodes')

    # Load existing PCB (preserves board outline set by pcb_init)
    if Path(pcb_path).exists():
        board = pcbnew.LoadBoard(pcb_path)
        if board is None:
            board = pcbnew.BOARD()
    else:
        board = pcbnew.BOARD()
    board.SetFileName(pcb_path)

    placed, failed = 0, []
    for comp in components:
        parts = comp['footprint'].split(':')
        if len(parts) != 2:
            failed.append(f'{comp["ref"]}: bad footprint')
            continue
        lib_name, fp_name = parts
        lib_path = f'{FP_LIB_DIR}/{lib_name}.pretty'
        try:
            fp = pcbnew.FootprintLoad(lib_path, fp_name)
            if fp is None:
                failed.append(f'{comp["ref"]}: FootprintLoad None')
                continue
            fp.SetReference(comp['ref'])
            fp.SetValue(comp['value'])
            board.Add(fp)
            placed += 1
        except Exception as e:
            failed.append(f'{comp["ref"]}: {e}')

    # Load net_assignments from schematic_config.json if available
    import json as _json
    config_path = Path(sch_path).parent / 'schematic_config.json'
    config_net_assignments = None
    if config_path.exists():
        try:
            cfg = _json.loads(config_path.read_text())
            config_net_assignments = cfg.get('net_assignments', None)
            if config_net_assignments:
                print(f'[sync] Using net_assignments from schematic_config.json '
                      f'({len(config_net_assignments)} components)')
        except Exception as e:
            print(f'[sync] Warning: could not read schematic_config.json: {e}')

    net_assigned = assign_nets_to_board(board, components, net_at_pos, config_net_assignments)

    board.Save(pcb_path)
    print(f'Synced {placed}/{len(components)} footprints')
    print(f'Net assignments (approximate): {net_assigned} pads')
    if failed:
        print('Failed:', failed)

    if labels:
        unique_nets = sorted(set(labels.values()))
        print(f'Nets found in schematic: {unique_nets}')
    return placed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Sync KiCad schematic to PCB')
    parser.add_argument('schematic', help='Path to .kicad_sch')
    parser.add_argument('pcb',       help='Path to .kicad_pcb (created if missing)')
    parser.add_argument('--width',   type=float, default=None, help='Board width mm')
    parser.add_argument('--height',  type=float, default=None, help='Board height mm')
    args = parser.parse_args()

    result = sync(args.schematic, args.pcb,
                  board_w=args.width, board_h=args.height)
    sys.exit(0 if result > 0 else 1)
