#!/usr/bin/env python3
"""
batch_schematic.py  v1.0.0

Writes a complete KiCad 9.0 schematic in ONE pass from a JSON config.
Replaces 30-50 individual MCP tool calls with a single script invocation.

JSON format:
{
  "symbols": [
    {"ref":"U1","lib_id":"Timer:NE555","value":"NE555",
     "footprint":"Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
     "x":50.8,"y":35.56,"angle":0}
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

Usage:
  python3 batch_schematic.py <config.json> <schematic.kicad_sch>
  python3 batch_schematic.py <config.json> <schematic.kicad_sch> --append

Flags:
  --append   Inject into existing schematic (keeps existing symbols)
  --preflight  Run schematic_preflight.py after writing

Always run with /usr/bin/python3 (no pcbnew needed — pure string generation).
"""
import sys, json, re, uuid
from pathlib import Path


# ── KiCad S-expression helpers ────────────────────────────────────────────────

def _uuid():
    return str(uuid.uuid4())


def _sym_property(name, value, x, y, hide=False, size=1.27):
    hidden = ' (effects (font (size 1.27 1.27)) (hide yes))' if hide else f' (effects (font (size {size} {size})))'
    return (f'    (property "{name}" "{value}" (at {x} {y} 0)'
            f'{hidden})')


def make_symbol(ref, lib_id, value, x, y, footprint='', angle=0, project_name=''):
    """Build a KiCad 9.0 (symbol ...) s-expression string."""
    a_str = f' {angle}' if angle else ' 0'
    fp_prop = _sym_property('Footprint', footprint, x, y + 2.54, hide=True) if footprint else ''
    inst_block = ''
    if project_name and not ref.startswith('#'):
        inst_block = (
            f'    (instances\n'
            f'      (project "{project_name}"\n'
            f'        (path "/"\n'
            f'          (reference "{ref}")\n'
            f'          (unit 1)\n'
            f'        )\n'
            f'      )\n'
            f'    )'
        )
    lines = [
        f'  (symbol (lib_id "{lib_id}") (at {x} {y}{a_str}) (unit 1)',
        f'    (in_bom yes) (on_board yes) (dnp no)',
        f'    (uuid "{_uuid()}")',
        _sym_property('Reference', ref,  x,      y - 2.54),
        _sym_property('Value',     value, x,      y + 2.54),
        _sym_property('Datasheet', '~',   x,      y + 5.08, hide=True),
    ]
    if fp_prop:
        lines.append(fp_prop)
    if inst_block:
        lines.append(inst_block)
    lines.append('  )')
    return '\n'.join(lines)


def make_power_port(name, x, y, project_name=''):
    """Build a power port (VCC / GND / +5V etc.) symbol."""
    return make_symbol(
        ref=f'#PWR_{_uuid()[:4]}',
        lib_id=f'power:{name}',
        value=name,
        x=x, y=y,
        project_name=project_name
    )


def make_net_label(name, x, y, angle=0):
    return (
        f'  (label "{name}" (at {x} {y} {angle})\n'
        f'    (effects (font (size 1.27 1.27)))\n'
        f'    (uuid "{_uuid()}")\n'
        f'  )'
    )


def make_wire_path(points):
    """Build wire segments from a list of [x,y] points."""
    segs = []
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        segs.append(
            f'  (wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n'
            f'    (stroke (width 0) (type default))\n'
            f'    (uuid "{_uuid()}")\n'
            f'  )'
        )
    return '\n'.join(segs)


def make_schematic(config, project_name, append_to=None):
    """Build complete schematic text from config dict."""
    parts = []

    # Accept both 'symbols' and 'components' as the component list key
    _syms = config.get('symbols', config.get('components', []))
    if not _syms and 'symbols' not in config and 'components' not in config:
        print('WARNING: schematic_config.json has neither "symbols" nor "components" key — 0 components will be written')
        print('  Use "symbols": [...] or "components": [...] to list your components')
    for sym in _syms:
        # Accept both short and long field name aliases
        _ref = sym.get('ref', sym.get('reference', sym.get('designator', '')))
        _lib = sym.get('lib_id', sym.get('library_id', sym.get('symbol', '')))
        _val = sym.get('value', _ref)
        _fp  = sym.get('footprint', sym.get('footprint_id', ''))
        _x   = sym.get('x', sym.get('pos_x', 0))
        _y   = sym.get('y', sym.get('pos_y', 0))
        _ang = sym.get('angle', sym.get('rotation', 0))
        if not _ref:
            print(f'WARNING: skipping symbol with no ref/reference field: {sym}')
            continue
        if not _lib:
            print(f'WARNING: skipping {_ref} — no lib_id/library_id field')
            continue
        parts.append(make_symbol(
            ref=_ref,
            lib_id=_lib,
            value=_val,
            x=_x, y=_y,
            footprint=_fp,
            angle=_ang,
            project_name=project_name
        ))

    for pp in config.get('power_ports', []):
        parts.append(make_power_port(pp['name'], pp['x'], pp['y'], project_name))

    for lbl in config.get('net_labels', []):
        parts.append(make_net_label(lbl['name'], lbl['x'], lbl['y'], lbl.get('angle', 0)))

    for wire_pts in config.get('wires', []):
        if len(wire_pts) >= 2:
            parts.append(make_wire_path(wire_pts))

    new_content = '\n'.join(parts)

    if append_to and Path(append_to).exists():
        existing = Path(append_to).read_text('utf-8')
        # Insert before the final closing paren
        if existing.rstrip().endswith(')'):
            return existing.rstrip()[:-1] + '\n' + new_content + '\n)\n'
        return existing + '\n' + new_content + '\n'

    # Fresh schematic
    header = (
        f'(kicad_sch\n'
        f'  (version 20231120)\n'
        f'  (generator "batch_schematic")\n'
        f'  (generator_version "1.0")\n'
        f'  (paper "A4")\n'
        f'  (title_block (title "{project_name}") (rev "v1.0"))\n'
        f'  (lib_symbols)\n\n'
    )
    footer = (
        f'\n  (sheet_instances (path "/" (page "1")))\n'
        f')\n'
    )
    return header + new_content + footer


def run(config_path, sch_path, append=False, run_preflight=False):
    config_file = Path(config_path)
    if not config_file.exists():
        print(f'ERROR: schematic_config.json not found at {config_path}')
        return False
    raw = config_file.read_text('utf-8').strip()
    if not raw:
        print(f'ERROR: schematic_config.json is EMPTY at {config_path}')
        print('  The file write failed silently (code_execution_tool returned unknown).')
        print('  Re-write using heredoc: cat > file << JSONEOF ... JSONEOF')
        print('  Do NOT fall back to MCP individual calls — fix the config and retry.')
        return False
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f'ERROR: Invalid JSON in schematic_config.json: {e}')
        print(f'  First 200 chars: {raw[:200]}')
        print('  Fix the JSON and retry. Do NOT fall back to MCP individual calls.')
        return False
    project_name = Path(sch_path).stem

    sch_text = make_schematic(
        config, project_name,
        append_to=sch_path if append else None
    )
    Path(sch_path).write_text(sch_text, 'utf-8')

    sym_count  = len(config.get('symbols', config.get('components', [])))
    pp_count   = len(config.get('power_ports', []))
    lbl_count  = len(config.get('net_labels', []))
    wire_count = sum(max(0, len(w) - 1) for w in config.get('wires', []))
    print(f'batch_schematic: wrote {sym_count} symbols, {pp_count} power ports, '
          f'{lbl_count} net labels, {wire_count} wire segments to {sch_path}')

    if run_preflight:
        import subprocess, os
        preflight = str(Path(__file__).parent / 'schematic_preflight.py')
        result = subprocess.run(
            [sys.executable, preflight, sch_path, '--summary'],
            capture_output=True, text=True
        )
        print('Preflight:', result.stdout.strip() or result.stderr.strip())
        return result.returncode == 0
    return True


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Write KiCad schematic from JSON config in one pass')
    ap.add_argument('config',     help='Path to JSON config file')
    ap.add_argument('schematic',  help='Path to output .kicad_sch file')
    ap.add_argument('--append',   action='store_true', help='Append to existing schematic')
    ap.add_argument('--preflight',action='store_true', help='Run preflight check after writing')
    args = ap.parse_args()
    ok = run(args.config, args.schematic, append=args.append, run_preflight=args.preflight)
    sys.exit(0 if ok else 1)
