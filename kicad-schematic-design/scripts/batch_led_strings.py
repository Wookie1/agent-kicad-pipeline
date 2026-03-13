#!/usr/bin/env python3
"""
batch_led_strings.py  v1.4.0

Batch-builds LED string circuits (net_label -> R -> D1 ... Dn -> GND) into a
.kicad_sch file in a single pass.

USAGE (inject mode):
  /usr/bin/python3 batch_led_strings.py <schematic.kicad_sch> <strings.json>

USAGE (rebuild mode):
  /usr/bin/python3 batch_led_strings.py --rebuild <schematic.kicad_sch>

=== PIN GEOMETRY (verified from KiCad 9.0 /usr/share/kicad/symbols/Device.kicad_sym) ===

Device:R at angle=90 (horizontal):
  Pin 1 LEFT  endpoint: (cx - 3.81, cy)
  Pin 2 RIGHT endpoint: (cx + 3.81, cy)

Device:LED at angle=0 (horizontal, K-left A-right):
  Pin K LEFT  endpoint: (cx - 3.81, cy)
  Pin A RIGHT endpoint: (cx + 3.81, cy)

power:GND           -- pin AT symbol center
Connector_Generic:Conn_01x01 -- pin AT symbol center

HORIZONTAL SPACING (v1.4.0 - 25.40mm LED-to-LED, 8.89mm wire gaps between symbols):
  Label start:  x = 10.16
  R center:     x = 25.40   pin1=21.59  pin2=29.21
  D1 center:    x = 38.10   K=34.29     A=41.91   gap from R.pin2 = 5.08mm
  D2 center:    x = 63.50   K=59.69     A=67.31   gap from D1.A   = 17.78mm
  D3 center:    x = 88.90   K=85.09     A=92.71   gap from D2.A   = 17.78mm
  D4 center:    x = 114.30  K=110.49    A=118.11  gap from D3.A   = 17.78mm
  D5 center:    x = 139.70  K=135.89    A=143.51  gap from D4.A   = 17.78mm
  GND (5-LED):  x = 152.40  wire from D5.A=143.51, gap=8.89mm  (60 x 2.54)
  GND (3-LED):  x = 101.60  wire from D3.A=92.71,  gap=8.89mm  (40 x 2.54)
  Row spacing (vertical): 20.32mm

  All LED centers on 2.54mm grid: 38.10=15x, 63.50=25x, 88.90=35x, 114.30=45x, 139.70=55x

REFERENCE DESIGNATORS:
  v1.3.0: Added (instances) block inside each symbol.
  v1.4.0: Added (sheet_instances) at root schematic level.
  BOTH are required for KiCad to display 'R1' instead of 'R?'.
  The (sheet_instances) block tells KiCad that path '/' is a real sheet (page 1).
  Without it, KiCad cannot resolve instance paths and shows library defaults.
"""

import json, uuid, re, shutil, sys
from pathlib import Path
from datetime import date

# === GEOMETRY CONSTANTS (v1.4.0 - 25.40mm LED spacing, 8.89mm end gaps) ===
PIN   = 3.81      # pin endpoint offset from symbol center
LX    = 10.16     # net-label / string start X
R_CX  = 25.40     # resistor center X
D_CX  = [38.10, 63.50, 88.90, 114.30, 139.70]  # LED centers, 25.40mm apart
GND5  = 152.40    # GND X for 5-LED strings (D5.A=143.51 + 8.89)
GND3  = 101.60    # GND X for 3-LED strings (D3.A=92.71  + 8.89)
STEP  = 20.32     # vertical row spacing mm

PROJECT_NAME = "torino_taillight"


def set_project_name(name):
    global PROJECT_NAME
    PROJECT_NAME = name


def uid():
    return str(uuid.uuid4())


def _instances(ref):
    """(instances) block required for KiCad to display reference designators.
    Without this AND sheet_instances at root level, KiCad shows 'R?' etc.
    """
    return ('    (instances\n'
            '      (project "{}"\n'.format(PROJECT_NAME) +
            '        (path "/"\n'
            '          (reference "{}")\n'.format(ref) +
            '          (unit 1)\n'
            '        )\n'
            '      )\n'
            '    )')


def _sheet_instances():
    """Root-level (sheet_instances) block required by KiCad 9.0.
    Declares that path '/' = page 1 of the schematic.
    Without this, instance paths don't resolve and references show as 'R?'.
    """
    return ('  (sheet_instances\n'
            '    (path "/"\n'
            '      (page "1")\n'
            '    )\n'
            '  )')


def _resistor(ref, val, fp, x, y):
    """Device:R placed horizontally (angle=90): Pin1 left, Pin2 right."""
    lines = [
        '  (symbol',
        '    (lib_id "Device:R")',
        '    (at {:.4f} {:.4f} 90)'.format(x, y),
        '    (unit 1)',
        '    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
        '    (uuid "{}")'.format(uid()),
        '    (property "Reference" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27))))'.format(ref, x, y-2.54),
        '    (property "Value" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27))))'.format(val, x, y+2.54),
        '    (property "Footprint" "{}" (at {:.4f} {:.4f} 90) (effects (font (size 1.27 1.27)) (hide yes)))'.format(fp, x, y),
        '    (property "Datasheet" "~" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(x, y),
        '    (pin "1" (uuid "{}"))'.format(uid()),
        '    (pin "2" (uuid "{}"))'.format(uid()),
        _instances(ref),
        '  )'
    ]
    return '\n'.join(lines)


def _led(ref, val, fp, x, y):
    """Device:LED placed horizontally (angle=0): K left, A right."""
    lines = [
        '  (symbol',
        '    (lib_id "Device:LED")',
        '    (at {:.4f} {:.4f} 0)'.format(x, y),
        '    (unit 1)',
        '    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
        '    (uuid "{}")'.format(uid()),
        '    (property "Reference" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27))))'.format(ref, x, y-2.54),
        '    (property "Value" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27))))'.format(val, x, y+2.54),
        '    (property "Footprint" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(fp, x, y),
        '    (property "Datasheet" "~" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(x, y),
        '    (pin "K" (uuid "{}"))'.format(uid()),
        '    (pin "A" (uuid "{}"))'.format(uid()),
        _instances(ref),
        '  )'
    ]
    return '\n'.join(lines)


def _connector(ref, val, fp, x, y):
    """Connector_Generic:Conn_01x01 -- single pin AT symbol center."""
    lines = [
        '  (symbol',
        '    (lib_id "Connector_Generic:Conn_01x01")',
        '    (at {:.4f} {:.4f} 0)'.format(x, y),
        '    (unit 1)',
        '    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
        '    (uuid "{}")'.format(uid()),
        '    (property "Reference" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27))))'.format(ref, x-5.0, y),
        '    (property "Value" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27))))'.format(val, x+6.5, y),
        '    (property "Footprint" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(fp, x, y),
        '    (property "Datasheet" "~" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(x, y),
        '    (pin "1" (uuid "{}"))'.format(uid()),
        _instances(ref),
        '  )'
    ]
    return '\n'.join(lines)


def _gnd(n, x, y):
    """power:GND -- pin AT symbol center."""
    ref = '#PWR{:03d}'.format(n)
    lines = [
        '  (symbol',
        '    (lib_id "power:GND")',
        '    (at {:.4f} {:.4f} 0)'.format(x, y),
        '    (unit 1)',
        '    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
        '    (uuid "{}")'.format(uid()),
        '    (property "Reference" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(ref, x, y+2.0),
        '    (property "Value" "GND" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27))))'.format(x, y+4.0),
        '    (property "Footprint" "" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(x, y),
        '    (property "Datasheet" "" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(x, y),
        '    (pin "1" (uuid "{}"))'.format(uid()),
        _instances(ref),
        '  )'
    ]
    return '\n'.join(lines)


def _pwr_flag(n, x, y):
    ref = '#PWR{:03d}'.format(n)
    lines = [
        '  (symbol',
        '    (lib_id "power:PWR_FLAG")',
        '    (at {:.4f} {:.4f} 0)'.format(x, y),
        '    (unit 1)',
        '    (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)',
        '    (uuid "{}")'.format(uid()),
        '    (property "Reference" "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(ref, x, y-2.0),
        '    (property "Value" "PWR_FLAG" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27))))'.format(x, y-4.0),
        '    (property "Footprint" "" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(x, y),
        '    (property "Datasheet" "" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27)) (hide yes)))'.format(x, y),
        '    (pin "1" (uuid "{}"))'.format(uid()),
        _instances(ref),
        '  )'
    ]
    return '\n'.join(lines)


def _wire(x1, y1, x2, y2):
    return '  (wire (pts (xy {:.4f} {:.4f}) (xy {:.4f} {:.4f})) (uuid "{}"))'.format(
        x1, y1, x2, y2, uid())


def _netlabel(name, x, y):
    return '  (label "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.27 1.27))) (uuid "{}"))'.format(
        name, x, y, uid())


def _schtext(msg, x, y, bold=False):
    b = 'yes' if bold else 'no'
    return '  (text "{}" (at {:.4f} {:.4f} 0) (effects (font (size 1.5 1.5) (bold {}))) (uuid "{}"))'.format(
        msg, x, y, b, uid())


# === PUBLIC: build one LED string ===
def build_string(r_ref, r_val, r_fp, d_refs, d_val, d_fp, net, row_y, n_leds, pwr_counter):
    """
    Build one LED string at row_y. Returns list of S-expression strings.
    pwr_counter: [int] mutable single-element list for #PWR numbering.
    n_leds: 1 to 5
    """
    if not 1 <= n_leds <= 5:
        raise ValueError('n_leds must be 1-5, got {}'.format(n_leds))
    out = []
    out.append(_netlabel(net, LX, row_y))
    out.append(_resistor(r_ref, r_val, r_fp, R_CX, row_y))
    out.append(_wire(LX, row_y, R_CX - PIN, row_y))          # label -> R.pin1
    for i in range(n_leds):
        cx = D_CX[i]
        out.append(_led(d_refs[i], d_val, d_fp, cx, row_y))
        if i == 0:
            out.append(_wire(R_CX + PIN, row_y, cx - PIN, row_y))
        else:
            out.append(_wire(D_CX[i-1] + PIN, row_y, cx - PIN, row_y))
    gnd_x = GND5 if n_leds == 5 else GND3
    out.append(_wire(D_CX[n_leds-1] + PIN, row_y, gnd_x, row_y))
    pwr_counter[0] += 1
    out.append(_gnd(pwr_counter[0], gnd_x, row_y))
    return out


# === PUBLIC: inject strings into existing schematic ===
def inject_strings(sch_path, config, backup=True):
    global PROJECT_NAME
    p = Path(sch_path)
    PROJECT_NAME = p.stem
    text = p.read_text(encoding='utf-8')
    if backup:
        shutil.copy2(p, str(p) + '.bak')
    pwr_refs = re.findall(r'#PWR(\d+)', text)
    pwr_n = [max((int(x) for x in pwr_refs), default=0)]
    new_blocks = []
    for s in config['strings']:
        new_blocks += build_string(
            s['r_ref'], s['r_val'], s['r_fp'],
            s['led_refs'], s['led_val'], s['led_fp'],
            s['net'], float(s['row_y']), len(s['led_refs']), pwr_n)
    # Add (sheet_instances) if not already present — required for ref designators
    if '(sheet_instances' not in text:
        new_blocks.append(_sheet_instances())
    insertion = '\n' + '\n'.join(new_blocks)
    new_text = text.rstrip()
    if new_text.endswith(')'):
        new_text = new_text[:-1] + insertion + '\n)\n'
    else:
        new_text = new_text + insertion + '\n)\n'
    p.write_text(new_text, encoding='utf-8')
    print('Injected {} strings into {}'.format(len(config['strings']), p.name))


# === PUBLIC: full rebuild ===
def full_rebuild(sch_path, title='LED PCB Schematic', paper='A1',
                conn_defs=None, sections=None, backup=True, project_name=None):
    """
    Generate a complete schematic from scratch.
    Includes (sheet_instances) block required for KiCad to resolve reference designators.

    conn_defs: list of (ref, val, net_or_None, cy)
    sections: list of {'label', 'start_y', 'strings': [...]}
    """
    global PROJECT_NAME
    p = Path(sch_path)
    if project_name:
        PROJECT_NAME = project_name
    else:
        PROJECT_NAME = p.stem

    if backup and p.exists():
        bak = str(p) + '.bak_rebuild'
        shutil.copy2(p, bak)
        print('Backup: {}'.format(bak))

    pwr_n = [0]
    def np():
        pwr_n[0] += 1
        return pwr_n[0]

    blocks = []

    if conn_defs:
        blocks.append(_schtext('=== WIRE LANDING PADS (20 AWG) ===', 10.16, 14.0, bold=True))
        for ref, val, net, cy in conn_defs:
            blocks.append(_connector(
                ref, val,
                'Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical',
                20.32, cy))
            blocks.append(_wire(20.32, cy, 33.02, cy))
            if net:
                blocks.append(_netlabel(net, 33.02, cy))
            else:
                blocks.append(_gnd(np(), 33.02, cy))
        last_gnd_y = conn_defs[-1][3]
        blocks.append(_pwr_flag(np(), 43.18, last_gnd_y))
        blocks.append(_wire(33.02, last_gnd_y, 43.18, last_gnd_y))

    if sections:
        for sec in sections:
            blocks.append(_schtext(sec['label'], 10.16, sec['start_y'] - 10.0, bold=True))
            for i, s in enumerate(sec['strings']):
                ry = sec['start_y'] + i * STEP
                blocks += build_string(
                    s['r_ref'], s['r_val'], s['r_fp'],
                    s['led_refs'], s['led_val'], s['led_fp'],
                    s['net'], ry, len(s['led_refs']), pwr_n)

    today = date.today().strftime('%Y-%m-%d')
    hdr = ('(kicad_sch\n'
           '  (version 20231120)\n'
           '  (generator "eeschema")\n'
           '  (generator_version "9.0")\n'
           '  (paper "{}")\n'.format(paper) +
           '  (title_block\n'
           '    (title "{}")\n'.format(title) +
           '    (date "{}")\n'.format(today) +
           '    (rev "1.0")\n'
           '    (company "")\n'
           '  )\n'
           '  (lib_symbols)\n')

    # sheet_instances MUST appear at root level for references to resolve
    footer = ('\n' + _sheet_instances() + '\n'
               '  (embedded_fonts no)\n')

    full = hdr + '\n'.join(blocks) + footer + ')\n'
    p.write_text(full, encoding='utf-8')
    n_o = full.count('('); n_c = full.count(')')
    print('Written: {}  ({:,} bytes)'.format(p, len(full)))
    print('Blocks: {}, #PWR: {}'.format(len(blocks), pwr_n[0]))
    print('Paren balance: {}  (0=OK)'.format(n_o - n_c))


# === CLI ===
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Batch-build LED strings into KiCad schematic')
    parser.add_argument('schematic', help='Path to .kicad_sch file')
    parser.add_argument('config', nargs='?', help='JSON config file (inject mode)')
    parser.add_argument('--rebuild', action='store_true',
                        help='Full rebuild using built-in torino_taillight defaults')
    args = parser.parse_args()

    if args.rebuild:
        tail_leds  = ['D{}'.format(n) for n in range(1,  31)]
        brake_leds = ['D{}'.format(n) for n in range(31, 51)]
        bkup_leds  = ['D{}'.format(n) for n in range(51, 81)]
        TAIL_FP  = 'LED_SMD:LED_PLCC-2_3.5x2.8mm'
        BRAKE_FP = 'LED_SMD:LED_PLCC-6_6x2.5mm'
        BKUP_FP  = 'LED_SMD:LED_PLCC-2_3.5x2.8mm'
        TAIL_Y0  = 116.84
        BRAKE_Y0 = TAIL_Y0 + 6*STEP + 20.0
        BKUP_Y0  = BRAKE_Y0 + 4*STEP + 20.0
        full_rebuild(
            args.schematic,
            title='1969 Ford Torino Sportsroof Taillight LED PCB',
            paper='A1',
            conn_defs=[
                ('J1', 'TAIL_PAD',   'TAIL',  25.40),
                ('J2', 'BRAKE_PAD',  'BRAKE', 45.72),
                ('J3', 'BACKUP_PAD', 'BACKUP',66.04),
                ('J4', 'GND_PAD',    None,    86.36),
            ],
            sections=[
                {'label': '=== TAIL LIGHTS (DIM RED)  6x5 LEDs  220ohm 0805 ===',
                 'start_y': TAIL_Y0,
                 'strings': [
                     {'r_ref': 'R{}'.format(s+1), 'r_val': '220',
                      'r_fp': 'Resistor_SMD:R_0805_2012Metric',
                      'led_refs': tail_leds[s*5:s*5+5],
                      'led_val': 'VLMS334AABB-GS08', 'led_fp': TAIL_FP, 'net': 'TAIL'}
                     for s in range(6)]},
                {'label': '=== BRAKE LIGHTS (BRIGHT RED)  4x5 LEDs  33ohm 2512 1W ===',
                 'start_y': BRAKE_Y0,
                 'strings': [
                     {'r_ref': 'R{}'.format(7+s), 'r_val': '33',
                      'r_fp': 'Resistor_SMD:R_6332_1632Metric',
                      'led_refs': brake_leds[s*5:s*5+5],
                      'led_val': 'LR G6SP.02-8D7E-46-G3R3-140-R18',
                      'led_fp': BRAKE_FP, 'net': 'BRAKE'}
                     for s in range(4)]},
                {'label': '=== BACKUP LIGHTS (WHITE)  10x3 LEDs  150ohm 1206 1/2W ===',
                 'start_y': BKUP_Y0,
                 'strings': [
                     {'r_ref': 'R{}'.format(11+s), 'r_val': '150',
                      'r_fp': 'Resistor_SMD:R_1206_3216Metric',
                      'led_refs': bkup_leds[s*3:s*3+3],
                      'led_val': 'CSMM-CWG3-NX7A2', 'led_fp': BKUP_FP, 'net': 'BACKUP'}
                     for s in range(10)]},
            ]
        )
    elif args.config:
        with open(args.config) as f:
            cfg = json.load(f)
        inject_strings(args.schematic, cfg)
    else:
        parser.print_help()
        sys.exit(1)
