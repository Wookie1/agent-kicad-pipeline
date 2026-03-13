#!/usr/bin/env python3
"""
schematic_builder.py  v1.0.0

Converts a high-level component+net description into:
  1. schematic_config.json  (consumed by batch_schematic.py)
  2. <project>.kicad_sch    (KiCad 9.0 schematic, via batch_schematic.py)
  3. <project>.net          (KiCad netlist, generated directly)

Input (Python dicts, also accepted as JSON file):
  components: [
    {"ref":"U1", "lib_id":"Timer:NE555", "value":"NE555",
     "footprint":"Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"},
    {"ref":"R1", "lib_id":"Device:R", "value":"10k",
     "footprint":"Resistor_SMD:R_0402_1005Metric"},
    ...
  ]
  nets: [
    {"name":"VCC",  "pins":[["U1","8"],["C1","1"]]},
    {"name":"GND",  "pins":[["U1","1"],["C1","2"],["R1","2"]]},
    {"name":"OUT",  "pins":[["U1","3"],["R1","1"]]}
  ]

Auto-layout strategy
--------------------
* Power nets (VCC / GND / +5V / +3V3 / VBUS / VBAT / …) get power port symbols,
  not net labels.  All other nets get net labels.
* Components are clustered by shared signal nets using Union-Find.
* Clusters are placed in rows; decoupling caps are nudged near their IC.
* Coordinates are millimetres on a 2.54 mm grid.

Usage (standalone):
  python3 schematic_builder.py components_nets.json /workspace/pcb/myproject/

Also importable; call build(components, nets, project_dir) → dict with paths.
"""

import json
import math
import re
import subprocess
import sys
import uuid
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

GRID       = 2.54          # mm — KiCad snapping grid
COL_W      = 30.48         # mm — horizontal gap between component columns
ROW_H      = 12.70         # mm — vertical gap between rows
ORIGIN_X   = 38.10         # mm — top-left of component field
ORIGIN_Y   = 38.10
POWER_Y_ABOVE  = 20.32     # mm — Y for VCC / positive rails (above components)
POWER_Y_BELOW  = 120.00    # mm — Y for GND symbols (below components)
LABEL_OFFSET_X =  5.08     # mm — net label offset from component centre

POWER_RE = re.compile(
    r'^(?:VCC|VDD|V\d+V\d*|VBUS|VBAT|VMOT|V_\w+|\+\d+V\d*|'
    r'GND|AGND|DGND|PGND|GND_\w+|VSS)$',
    re.IGNORECASE
)

DECOUPLING_RE = re.compile(r'^C\d+$', re.IGNORECASE)
IC_RE         = re.compile(r'^(?:U|IC|Q)\d+', re.IGNORECASE)
CONN_RE       = re.compile(r'^(?:J|P|CN|CON)\d+', re.IGNORECASE)
LED_RE        = re.compile(r'^D\d+', re.IGNORECASE)


# ── Union-Find ─────────────────────────────────────────────────────────────────

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
        """Return {root: [members]} for items."""
        d = {}
        for i in items:
            r = self.find(i)
            d.setdefault(r, []).append(i)
        return d


# ── Helpers ───────────────────────────────────────────────────────────────────

def _snap(v):
    return round(round(v / GRID) * GRID, 6)


def _is_power_net(name: str) -> bool:
    return bool(POWER_RE.match(name))


def _comp_priority(ref: str) -> int:
    """Lower = placed first / more central."""
    if IC_RE.match(ref):   return 0
    if CONN_RE.match(ref): return 1
    if LED_RE.match(ref):  return 2
    if DECOUPLING_RE.match(ref): return 4
    return 3


def _cluster_components(refs: list[str], nets: list[dict]) -> list[list[str]]:
    """
    Group component refs into clusters by shared *signal* nets.
    Returns list of clusters, largest first.
    """
    uf = _UF()
    for ref in refs:
        uf.find(ref)          # ensure all nodes exist

    for net in nets:
        if _is_power_net(net["name"]):
            continue          # power rails don't define proximity
        pins = net.get("pins", [])
        refs_in_net = [p[0] for p in pins if len(p) >= 1]
        for i in range(1, len(refs_in_net)):
            uf.union(refs_in_net[0], refs_in_net[i])

    groups = uf.groups(refs)
    clusters = sorted(groups.values(), key=len, reverse=True)
    return clusters


def _assign_positions(components: list[dict], nets: list[dict]) -> dict[str, tuple[float, float]]:
    """
    Returns {ref: (x_mm, y_mm)} for every component.

    Layout rules (in priority order):
    1. Connectors → leftmost column
    2. ICs → central columns
    3. LEDs → horizontal row (grouped)
    4. Decoupling caps → near their IC (same cluster, nudged right/below)
    5. Everything else → remaining columns
    """
    refs = [c["ref"] for c in components]
    clusters = _cluster_components(refs, nets)

    # Build ref→cluster-index for quick lookup
    ref_cluster = {}
    for ci, cluster in enumerate(clusters):
        for r in cluster:
            ref_cluster[r] = ci

    positions = {}
    col = 0
    row = 0
    max_rows_this_col = 8           # wrap after this many rows

    # Separate connectors (always leftmost)
    connectors  = [r for r in refs if CONN_RE.match(r)]
    non_conn    = [r for r in refs if not CONN_RE.match(r)]

    def _place(ref_list):
        nonlocal col, row
        for ref in ref_list:
            x = _snap(ORIGIN_X + col * COL_W)
            y = _snap(ORIGIN_Y + row * ROW_H)
            positions[ref] = (x, y)
            row += 1
            if row >= max_rows_this_col:
                row = 0
                col += 1

    # Pass 1 – connectors in first column
    _place(sorted(connectors))
    if connectors:
        col += 1
        row = 0

    # Pass 2 – sort non-connectors: ICs first, then others, then caps last
    ics       = sorted([r for r in non_conn if IC_RE.match(r)])
    leds      = sorted([r for r in non_conn if LED_RE.match(r) and not IC_RE.match(r)])
    caps      = sorted([r for r in non_conn if DECOUPLING_RE.match(r)])
    rest      = sorted([r for r in non_conn
                        if not IC_RE.match(r) and not LED_RE.match(r)
                        and not DECOUPLING_RE.match(r)])

    _place(ics)
    _place(rest)
    _place(leds)

    # Decoupling caps: try to place near their IC partner
    ic_positions = {r: positions[r] for r in ics if r in positions}
    cap_ic_map = {}  # cap_ref → ic_ref

    for net in nets:
        if _is_power_net(net["name"]):
            continue
        pins = net.get("pins", [])
        net_refs = [p[0] for p in pins]
        ic_refs_in_net  = [r for r in net_refs if IC_RE.match(r) and r in ic_positions]
        cap_refs_in_net = [r for r in net_refs if DECOUPLING_RE.match(r)]
        for cap in cap_refs_in_net:
            if ic_refs_in_net and cap not in cap_ic_map:
                cap_ic_map[cap] = ic_refs_in_net[0]

    placed_caps = set()
    for cap in caps:
        if cap in cap_ic_map:
            ic_ref  = cap_ic_map[cap]
            ic_x, ic_y = ic_positions[ic_ref]
            # nudge slightly right and below IC
            offset = (list(caps).index(cap) + 1) * GRID * 2
            positions[cap] = (_snap(ic_x + COL_W * 0.6), _snap(ic_y + offset))
            placed_caps.add(cap)

    remaining_caps = [c for c in caps if c not in placed_caps]
    _place(remaining_caps)

    return positions


# ── Net label / power port coordinate helpers ─────────────────────────────────

def _net_labels_for(components: list[dict], nets: list[dict],
                    positions: dict[str, tuple]) -> list[dict]:
    """
    For each signal (non-power) net, emit a net label near the first
    component that appears in that net.
    """
    labels = []
    seen = set()
    for net in nets:
        name = net["name"]
        if _is_power_net(name):
            continue
        if name in seen:
            continue
        # find first component pin that has a position
        for pin in net.get("pins", []):
            ref = pin[0]
            if ref in positions:
                x, y = positions[ref]
                labels.append({
                    "name": name,
                    "x": _snap(x + LABEL_OFFSET_X),
                    "y": y,
                    "angle": 0
                })
                seen.add(name)
                break
    return labels


def _power_ports_for(components: list[dict], nets: list[dict],
                     positions: dict[str, tuple]) -> list[dict]:
    """
    Emit one power port per unique power net name.
    Place VCC/positive rails above the average X of their components;
    GND / negative rails below.
    """
    power_nets: dict[str, list[str]] = {}  # name → [refs]
    for net in nets:
        name = net["name"]
        if not _is_power_net(name):
            continue
        refs = [p[0] for p in net.get("pins", []) if len(p) >= 1]
        power_nets.setdefault(name, []).extend(refs)

    ports = []
    for name, refs in power_nets.items():
        xs = [positions[r][0] for r in refs if r in positions]
        avg_x = _snap(sum(xs) / len(xs)) if xs else ORIGIN_X

        # GND-family → below; everything else → above
        is_gnd = re.match(r'^(?:GND|AGND|DGND|PGND|VSS|GND_\w+)$', name, re.I)
        y = POWER_Y_BELOW if is_gnd else POWER_Y_ABOVE

        ports.append({"name": name, "x": avg_x, "y": _snap(y)})
    return ports


# ── .net file generation ──────────────────────────────────────────────────────

def _make_net_file(project_name: str, components: list[dict],
                   nets: list[dict]) -> str:
    """
    Generate a KiCad .net (S-expression netlist) directly from component+net
    data — no schematic parsing needed.
    """

    def _uid():
        return str(uuid.uuid4())

    lines = [
        f'(export (version "E")',
        f'  (design',
        f'    (source "{project_name}.kicad_sch")',
        f'    (date "2024-01-01 00:00:00")',
        f'    (tool "pcb-pipeline/schematic_builder.py")',
        f'  )',
        f'  (components',
    ]

    for comp in components:
        ref = comp["ref"]
        val = comp.get("value", ref)
        fp  = comp.get("footprint", "")
        lines += [
            f'    (comp (ref "{ref}")',
            f'      (value "{val}")',
            f'      (footprint "{fp}")',
            f'    )',
        ]

    lines.append('  )')
    lines.append('  (nets')

    for idx, net in enumerate(nets):
        name = net["name"]
        lines.append(f'    (net (code "{idx + 1}") (name "{name}")')
        for pin in net.get("pins", []):
            if len(pin) >= 2:
                lines.append(f'      (node (ref "{pin[0]}") (pin "{pin[1]}"))')
        lines.append('    )')

    lines.append('  )')
    lines.append(')')
    return '\n'.join(lines) + '\n'


# ── Config generation ─────────────────────────────────────────────────────────

def _make_schematic_config(components: list[dict], nets: list[dict]) -> dict:
    """
    Build the schematic_config.json dict consumed by batch_schematic.py.
    Includes net_assignments for sch_to_pcb_sync.py Priority-1 path.
    """
    positions = _assign_positions(components, nets)

    # Build net_assignments: {ref: {pin_num: net_name}}
    net_assignments: dict[str, dict[str, str]] = {}
    for net in nets:
        for pin in net.get("pins", []):
            if len(pin) < 2:
                continue
            ref, pin_num = str(pin[0]), str(pin[1])
            net_assignments.setdefault(ref, {})[pin_num] = net["name"]

    symbols = []
    for comp in components:
        ref = comp["ref"]
        x, y = positions.get(ref, (ORIGIN_X, ORIGIN_Y))
        symbols.append({
            "ref":       ref,
            "lib_id":    comp.get("lib_id", comp.get("symbol", "")),
            "value":     comp.get("value", ref),
            "footprint": comp.get("footprint", ""),
            "x":         x,
            "y":         y,
            "angle":     comp.get("angle", 0),
        })

    # Wires: connect each component's label-side to nearby net label
    # (minimal horizontal stubs so the schematic reads well)
    wires = []
    for comp in components:
        ref = comp["ref"]
        x, y = positions.get(ref, (ORIGIN_X, ORIGIN_Y))
        # stub wire to the right where signal net labels live
        if any(
            not _is_power_net(net["name"])
            for net in nets
            if any(p[0] == ref for p in net.get("pins", []))
        ):
            wires.append([[x, y], [_snap(x + LABEL_OFFSET_X), y]])

    config = {
        "symbols":       symbols,
        "power_ports":   _power_ports_for(components, nets, positions),
        "net_labels":    _net_labels_for(components, nets, positions),
        "wires":         wires,
        "net_assignments": net_assignments,
    }
    return config


# ── Main entry point ──────────────────────────────────────────────────────────

def build(components: list[dict], nets: list[dict],
          project_dir: str | Path,
          batch_script: str | None = None,
          python_exe: str = "/a0/usr/skills-venv/bin/python3") -> dict:
    """
    Build schematic and netlist from component+net data.

    Returns:
      {
        "config_path":    str,
        "schematic_path": str,
        "net_path":       str,
        "preflight":      str,   # stdout from schematic_preflight.py
        "warnings":       [str],
        "ok":             bool,
      }
    """
    project_dir  = Path(project_dir)
    project_name = project_dir.name
    warnings     = []

    # ── Validate inputs ───────────────────────────────────────────────────────
    refs = {c["ref"] for c in components}
    for net in nets:
        for pin in net.get("pins", []):
            if pin[0] not in refs:
                warnings.append(f"Net '{net['name']}' references unknown ref '{pin[0]}'")

    for comp in components:
        if not comp.get("lib_id") and not comp.get("symbol"):
            warnings.append(f"Component '{comp['ref']}' has no lib_id/symbol field")
        if not comp.get("footprint"):
            warnings.append(f"Component '{comp['ref']}' has no footprint")

    # ── Write schematic_config.json ───────────────────────────────────────────
    config = _make_schematic_config(components, nets)
    config_path = project_dir / "schematic_config.json"
    config_path.write_text(json.dumps(config, indent=2), "utf-8")

    # ── Write .net file ───────────────────────────────────────────────────────
    net_path = project_dir / f"{project_name}.net"
    net_path.write_text(_make_net_file(project_name, components, nets), "utf-8")

    # ── Run batch_schematic.py ────────────────────────────────────────────────
    sch_path = project_dir / f"{project_name}.kicad_sch"

    # Locate batch_schematic.py relative to this file
    if batch_script is None:
        # Try sibling skills directory (deployed path)
        candidate = Path(__file__).parent.parent / (
            "kicad-schematic-design/scripts/batch_schematic.py"
        )
        if not candidate.exists():
            # Fallback: look in project's .a0proj/skills/
            candidate = Path("/a0/usr/skills/kicad-schematic-design/scripts/batch_schematic.py")
        batch_script = str(candidate)

    batch_ok = False
    preflight_output = ""

    if not Path(batch_script).exists():
        warnings.append(f"batch_schematic.py not found at {batch_script}; skipping schematic generation")
    else:
        cmd = [python_exe, batch_script,
               str(config_path), str(sch_path), "--preflight"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60,
                env={**__import__("os").environ, "DISPLAY": ":99"}
            )
            preflight_output = (result.stdout + result.stderr).strip()
            batch_ok = result.returncode == 0
            if not batch_ok:
                warnings.append(f"batch_schematic.py exited {result.returncode}: {preflight_output[:300]}")
        except subprocess.TimeoutExpired:
            warnings.append("batch_schematic.py timed out after 60 s")
        except Exception as exc:
            warnings.append(f"batch_schematic.py error: {exc}")

    return {
        "config_path":    str(config_path),
        "schematic_path": str(sch_path),
        "net_path":       str(net_path),
        "preflight":      preflight_output,
        "warnings":       warnings,
        "ok":             batch_ok or sch_path.exists(),
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="Build KiCad schematic + netlist from components+nets JSON"
    )
    ap.add_argument("input_json",   help="JSON file with {components:[], nets:[]}")
    ap.add_argument("project_dir",  help="KiCad project directory")
    ap.add_argument("--python",     default="/a0/usr/skills-venv/bin/python3",
                    help="Python interpreter to use for batch_schematic.py")
    ap.add_argument("--batch-script", default=None,
                    help="Path to batch_schematic.py (auto-detected if omitted)")
    args = ap.parse_args()

    data = json.loads(Path(args.input_json).read_text("utf-8"))
    result = build(
        components   = data["components"],
        nets         = data["nets"],
        project_dir  = args.project_dir,
        batch_script = args.batch_script,
        python_exe   = args.python,
    )
    for w in result["warnings"]:
        print(f"WARNING: {w}", file=sys.stderr)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["ok"] else 1)
