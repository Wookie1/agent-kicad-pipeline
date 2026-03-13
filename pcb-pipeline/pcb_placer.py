#!/usr/bin/env python3
"""
pcb_placer.py  v1.0.0

Connectivity-aware PCB component placement.

Reads a KiCad .net (S-expression netlist) and an existing .kicad_pcb file
(which already has footprints imported via sch_to_pcb_sync.py or update_pcb),
then writes footprint At-positions and the board Edge.Cuts outline using
pure string manipulation — no pcbnew / display required.

Placement strategy
------------------
Zone 1  Connectors (J/P/CN/CON)   → left edge, stacked vertically
Zone 2  ICs (U/IC/Q)              → centre, largest cluster first
Zone 3  Decoupling caps (C near U)→ right of their IC (same signal cluster)
Zone 4  LEDs (D)                  → horizontal rows, top-right area
Zone 5  Resistors / inductors     → columns, fill remaining space
Zone 6  Other                     → trailing columns

Grid: 1.27 mm    Board outline: exact board_w × board_h mm

Usage:
  python3 pcb_placer.py <project.net> <project.kicad_pcb> \
          --width 80 --height 60

Also importable; call place(net_path, pcb_path, board_w, board_h, hints={}).
"""

import re
import sys
from pathlib import Path

# ── Grid & zone geometry ──────────────────────────────────────────────────────

GRID         = 1.27          # mm
MARGIN       = 5.08          # mm — keep-out from board edge
CONN_X       = 5.08          # mm from left edge (connector centre X)
IC_START_X   = 20.32         # mm from left edge
COL_W        = 15.24         # mm — column pitch for ICs
ROW_H        =  7.62         # mm — row pitch for ICs
CAP_OFFSET_X =  5.08         # mm right of IC for decoupling caps
CAP_OFFSET_Y =  0.00         # mm
LED_START_Y  =  7.62         # mm from top for LED rows
LED_PITCH_X  =  7.62         # mm
SMALL_COL_W  =  5.08         # mm — column pitch for passives

MAX_ROWS_IC   = 6
MAX_ROWS_PASS = 10

# ── Regex classifiers ─────────────────────────────────────────────────────────

IC_RE   = re.compile(r'^(?:U|IC|Q)\d+',         re.IGNORECASE)
CONN_RE = re.compile(r'^(?:J|P|CN|CON)\d+',     re.IGNORECASE)
CAP_RE  = re.compile(r'^C\d+$',                 re.IGNORECASE)
LED_RE  = re.compile(r'^D\d+',                  re.IGNORECASE)
RES_RE  = re.compile(r'^R\d+',                  re.IGNORECASE)
IND_RE  = re.compile(r'^L\d+',                  re.IGNORECASE)


# ── Union-Find (same as schematic_builder, kept self-contained) ───────────────

class _UF:
    def __init__(self):
        self._p = {}

    def find(self, x):
        self._p.setdefault(x, x)
        if self._p[x] != x:
            self._p[x] = self.find(self._p[x])
        return self._p[x]

    def union(self, a, b):
        self._p[self.find(a)] = self.find(b)

    def groups(self, items):
        d = {}
        for i in items:
            d.setdefault(self.find(i), []).append(i)
        return d


# ── Netlist parser ────────────────────────────────────────────────────────────

def _parse_net(net_text: str) -> tuple[list[str], dict[str, list[list[str]]]]:
    """
    Returns:
      refs   — ordered list of component refs
      nets   — {net_name: [[ref, pin], ...]}
    """
    refs = re.findall(r'\(comp\s+\(ref\s+"([^"]+)"', net_text)

    nets: dict[str, list[list[str]]] = {}
    for m in re.finditer(r'\(net\s+[^)]*\(name\s+"([^"]+)"\)(.*?)\)', net_text, re.DOTALL):
        name  = m.group(1)
        body  = m.group(2)
        pins  = re.findall(r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)', body)
        nets[name] = [list(p) for p in pins]
    return refs, nets


# ── Snap helper ───────────────────────────────────────────────────────────────

def _snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 4)


# ── Connectivity-aware placement ──────────────────────────────────────────────

_POWER_RE = re.compile(
    r'^(?:VCC|VDD|V\d+V\d*|VBUS|VBAT|VMOT|V_\w+|\+\d+V\d*|'
    r'GND|AGND|DGND|PGND|GND_\w+|VSS)$',
    re.IGNORECASE
)


def _cluster_by_signal(refs: list[str], nets: dict) -> list[list[str]]:
    uf = _UF()
    for r in refs:
        uf.find(r)
    for name, pins in nets.items():
        if _POWER_RE.match(name):
            continue
        members = [p[0] for p in pins]
        for i in range(1, len(members)):
            uf.union(members[0], members[i])
    groups = uf.groups(refs)
    return sorted(groups.values(), key=len, reverse=True)


def _compute_positions(refs: list[str], nets: dict,
                       board_w: float, board_h: float,
                       hints: dict) -> dict[str, tuple[float, float]]:
    """
    Returns {ref: (x_mm, y_mm)} placed inside the board.
    Respects hints dict: {"ref": {"x": float, "y": float}} for manual overrides.
    """
    positions: dict[str, tuple[float, float]] = {}
    placed: set[str] = set()

    # Apply manual hints first
    for ref, h in hints.items():
        if "x" in h and "y" in h:
            positions[ref] = (_snap(h["x"]), _snap(h["y"]))
            placed.add(ref)

    connectors  = sorted([r for r in refs if CONN_RE.match(r) and r not in placed])
    ics         = sorted([r for r in refs if IC_RE.match(r)   and r not in placed])
    caps        = sorted([r for r in refs if CAP_RE.match(r)  and r not in placed])
    leds        = sorted([r for r in refs if LED_RE.match(r)  and r not in placed])
    resistors   = sorted([r for r in refs if RES_RE.match(r)  and r not in placed])
    inductors   = sorted([r for r in refs if IND_RE.match(r)  and r not in placed])
    others      = sorted([r for r in refs
                          if r not in placed
                          and not CONN_RE.match(r) and not IC_RE.match(r)
                          and not CAP_RE.match(r)  and not LED_RE.match(r)
                          and not RES_RE.match(r)  and not IND_RE.match(r)])

    # ── Zone 1: Connectors → left column ─────────────────────────────────────
    for i, ref in enumerate(connectors):
        x = _snap(MARGIN + CONN_X)
        y = _snap(MARGIN + LED_START_Y + i * ROW_H)
        y = min(y, _snap(board_h - MARGIN))
        positions[ref] = (x, y)
        placed.add(ref)

    ic_col_start = IC_START_X if connectors else MARGIN + 2.54

    # ── Zone 2: ICs → centre, cluster-aware ──────────────────────────────────
    clusters = _cluster_by_signal(ics, nets)
    col, row = 0, 0
    for cluster in clusters:
        for ref in sorted(cluster):
            if ref in placed:
                continue
            x = _snap(ic_col_start + col * COL_W)
            y = _snap(MARGIN + row * ROW_H)
            x = min(x, _snap(board_w - MARGIN))
            y = min(y, _snap(board_h - MARGIN))
            positions[ref] = (x, y)
            placed.add(ref)
            row += 1
            if row >= MAX_ROWS_IC:
                row = 0
                col += 1

    ic_max_col = col + (1 if row > 0 else 0)
    ic_end_x   = _snap(ic_col_start + ic_max_col * COL_W)

    # ── Zone 3: Decoupling caps → near their IC ───────────────────────────────
    # Build IC→cap mapping through shared signal nets
    ic_cap_pairs: dict[str, str] = {}  # cap → ic
    for name, pins in nets.items():
        if _POWER_RE.match(name):
            continue
        net_refs = [p[0] for p in pins]
        ic_refs  = [r for r in net_refs if r in positions and IC_RE.match(r)]
        cap_refs = [r for r in net_refs if CAP_RE.match(r) and r not in placed]
        for cap in cap_refs:
            if ic_refs and cap not in ic_cap_pairs:
                ic_cap_pairs[cap] = ic_refs[0]

    cap_offsets: dict[str, int] = {}  # how many caps already near this IC
    for cap in caps:
        if cap in placed:
            continue
        if cap in ic_cap_pairs:
            ic_ref = ic_cap_pairs[cap]
            ix, iy = positions[ic_ref]
            n       = cap_offsets.get(ic_ref, 0)
            x       = _snap(ix + CAP_OFFSET_X)
            y       = _snap(iy + n * GRID * 2)
            x = min(x, _snap(board_w - MARGIN))
            y = min(y, _snap(board_h - MARGIN))
            positions[cap] = (x, y)
            cap_offsets[ic_ref] = n + 1
            placed.add(cap)

    # Remaining caps → passive columns
    remaining_caps = [c for c in caps if c not in placed]

    # ── Zone 4: LEDs → horizontal rows ───────────────────────────────────────
    led_x_start = _snap(ic_end_x + SMALL_COL_W)
    led_row, led_col = 0, 0
    for led in leds:
        if led in placed:
            continue
        x = _snap(led_x_start + led_col * LED_PITCH_X)
        y = _snap(MARGIN + LED_START_Y + led_row * ROW_H)
        if x > board_w - MARGIN:
            led_col = 0
            led_row += 1
            x = led_x_start
            y = _snap(MARGIN + LED_START_Y + led_row * ROW_H)
        y = min(y, _snap(board_h - MARGIN))
        positions[led] = (x, y)
        placed.add(led)
        led_col += 1

    led_end_x = _snap(led_x_start + max(led_col, 1) * LED_PITCH_X) if leds else led_x_start

    # ── Zone 5 & 6: Passives + others → trailing columns ─────────────────────
    pass_start_x = _snap(max(ic_end_x, led_end_x) + SMALL_COL_W)
    p_col, p_row = 0, 0

    def _place_passive(ref_list):
        nonlocal p_col, p_row
        for ref in ref_list:
            if ref in placed:
                continue
            x = _snap(pass_start_x + p_col * SMALL_COL_W)
            y = _snap(MARGIN + p_row * GRID * 3)
            x = min(x, _snap(board_w - MARGIN))
            y = min(y, _snap(board_h - MARGIN))
            positions[ref] = (x, y)
            placed.add(ref)
            p_row += 1
            if p_row >= MAX_ROWS_PASS:
                p_row = 0
                p_col += 1

    _place_passive(remaining_caps)
    _place_passive(resistors)
    _place_passive(inductors)
    _place_passive(others)

    # Fallback for anything still unplaced
    fallback_x = _snap(board_w / 2)
    fallback_y = _snap(board_h / 2)
    fb_off = 0
    for ref in refs:
        if ref not in positions:
            positions[ref] = (_snap(fallback_x + fb_off * GRID), fallback_y)
            fb_off += 1

    return positions


# ── PCB file patcher ──────────────────────────────────────────────────────────

_FP_RE = re.compile(
    r'(\(footprint\s+"[^"]*"[^(]*\(layer\s+"[^"]*"\))\s*\(at\s+[^)]+\)',
    re.DOTALL
)
_FP_REF_RE = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')


def _patch_pcb(pcb_text: str, positions: dict[str, tuple]) -> str:
    """
    Replace (at X Y [angle]) in each footprint block with computed position.
    Also injects Edge.Cuts outline if missing.
    """

    def _replace_at(m):
        block = m.group(0)
        ref_m = _FP_REF_RE.search(block)
        if not ref_m:
            return block
        ref = ref_m.group(1)
        if ref.startswith('#'):
            return block
        if ref not in positions:
            return block
        x, y = positions[ref]
        # Rebuild the (at ...) clause, preserving existing angle if any
        at_m = re.search(r'\(at\s+([\d.\-]+)\s+([\d.\-]+)(?:\s+([\d.\-]+))?\)', block)
        angle = at_m.group(3) if (at_m and at_m.group(3)) else "0"
        new_at = f'(at {x} {y} {angle})'
        return re.sub(r'\(at\s+[^)]+\)', new_at, block, count=1)

    patched = _FP_RE.sub(_replace_at, pcb_text)
    return patched


def _inject_edge_cuts(pcb_text: str, board_w: float, board_h: float) -> str:
    """
    Add a rectangular Edge.Cuts outline if none is present.
    Uses gr_rect for KiCad 9.0.
    """
    if '"Edge.Cuts"' in pcb_text:
        return pcb_text  # already has outline

    outline = (
        f'\n  (gr_rect (start 0 0) (end {board_w} {board_h})\n'
        f'    (stroke (width 0.05) (type default))\n'
        f'    (layer "Edge.Cuts")\n'
        f'    (uuid "{_new_uuid()}"))\n'
    )
    # Insert before the final closing paren
    stripped = pcb_text.rstrip()
    if stripped.endswith(')'):
        return stripped[:-1] + outline + ')\n'
    return pcb_text + outline


def _new_uuid():
    import uuid
    return str(uuid.uuid4())


# ── Public API ────────────────────────────────────────────────────────────────

def place(net_path: str | Path, pcb_path: str | Path,
          board_w: float = 80.0, board_h: float = 60.0,
          hints: dict | None = None) -> dict:
    """
    Place footprints in an existing .kicad_pcb using connectivity from .net.

    Args:
      net_path   — path to KiCad .net file
      pcb_path   — path to .kicad_pcb (modified in-place)
      board_w    — board width mm
      board_h    — board height mm
      hints      — optional {ref: {x: float, y: float}} manual overrides

    Returns:
      {"placed": int, "warnings": [str], "ok": bool}
    """
    hints    = hints or {}
    warnings = []

    net_path = Path(net_path)
    pcb_path = Path(pcb_path)

    if not net_path.exists():
        return {"placed": 0, "warnings": [f".net file not found: {net_path}"], "ok": False}
    if not pcb_path.exists():
        return {"placed": 0, "warnings": [f".kicad_pcb not found: {pcb_path}"], "ok": False}

    net_text = net_path.read_text("utf-8")
    refs, nets = _parse_net(net_text)

    if not refs:
        warnings.append("No components found in .net file")
        return {"placed": 0, "warnings": warnings, "ok": False}

    positions = _compute_positions(refs, nets, board_w, board_h, hints)

    pcb_text  = pcb_path.read_text("utf-8")
    patched   = _patch_pcb(pcb_text, positions)
    patched   = _inject_edge_cuts(patched, board_w, board_h)
    pcb_path.write_text(patched, "utf-8")

    placed = sum(1 for r in refs if r in positions)
    return {"placed": placed, "warnings": warnings, "ok": True}


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser(
        description="Connectivity-aware PCB footprint placement from .net file"
    )
    ap.add_argument("net",        help="KiCad .net netlist file")
    ap.add_argument("pcb",        help=".kicad_pcb file (modified in-place)")
    ap.add_argument("--width",    type=float, default=80.0,  help="Board width mm")
    ap.add_argument("--height",   type=float, default=60.0,  help="Board height mm")
    ap.add_argument("--hints",    default=None,
                    help='JSON string {ref:{x,y}} for manual placement overrides')
    args = ap.parse_args()

    hints = json.loads(args.hints) if args.hints else {}
    result = place(args.net, args.pcb, args.width, args.height, hints)
    for w in result["warnings"]:
        print(f"WARNING: {w}", file=sys.stderr)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["ok"] else 1)
