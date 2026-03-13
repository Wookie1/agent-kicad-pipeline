#!/usr/bin/env python3
"""
kicad_place_footprints.py
--------------------------
Batch-set footprint positions and orientations in a .kicad_pcb file
using direct s-expression manipulation (no KiCad Python API required).

The MCP server's update_pcb_from_schematic syncs footprints from schematic
but does NOT set positions.  This script fills that gap.

Usage (CLI):
    python kicad_place_footprints.py board.kicad_pcb placements.json [--out board_placed.kicad_pcb]

placements.json format:
    [
      {"ref": "U1", "x": 25.0, "y": 15.0, "angle": 0,   "side": "front"},
      {"ref": "C1", "x": 30.5, "y": 18.2, "angle": 90,  "side": "front"},
      {"ref": "R1", "x": 22.0, "y": 22.0, "angle": 180, "side": "back"}
    ]
    side: "front" = F.Cu, "back" = B.Cu (mirrors the component)

Usage (import):
    from helpers.kicad.kicad_place_footprints import place_footprints, Placement
    placements = [Placement("U1", 25.0, 15.0, 0.0, "front"), ...]
    new_content = place_footprints(pcb_content_str, placements)
"""

import re
import json
import sys
import argparse
from dataclasses import dataclass
from typing import List, Optional
from pathlib import Path


@dataclass
class Placement:
    ref: str           # reference designator, e.g. "U1"
    x: float           # X position in mm
    y: float           # Y position in mm
    angle: float = 0.0 # rotation in degrees (CCW positive in KiCad)
    side: str = "front"  # "front" or "back"


# ---------------------------------------------------------------------------
# Parser: very small recursive-descent s-expr locator
# We need to find each (footprint ...) block and update its (at ...) line
# and layer if side changes.
# ---------------------------------------------------------------------------

def _find_footprint_blocks(content: str) -> List[tuple]:
    """
    Find all top-level (footprint ...) blocks.
    Returns list of (start_idx, end_idx, reference_string).
    """
    results = []
    i = 0
    n = len(content)

    while i < n:
        # Find '(footprint'
        fp_start = content.find('(footprint', i)
        if fp_start == -1:
            break

        # Walk forward counting parentheses to find the closing )
        depth = 0
        j = fp_start
        while j < n:
            if content[j] == '(':
                depth += 1
            elif content[j] == ')':
                depth -= 1
                if depth == 0:
                    fp_end = j
                    block = content[fp_start:fp_end + 1]
                    # Extract reference from (fp_text reference "REF" ...)
                    ref_match = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', block)
                    if not ref_match:
                        # KiCad 6 format: (property "Reference" "REF" ...)
                        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
                    ref = ref_match.group(1) if ref_match else None
                    results.append((fp_start, fp_end + 1, ref))
                    i = fp_end + 1
                    break
            j += 1
        else:
            break  # no matching paren found

    return results


def _update_at_line(block: str, x: float, y: float, angle: float) -> str:
    """
    Replace the first (at X Y [ANGLE]) in the footprint block.
    KiCad stores footprint position as the first (at ...) NOT inside a sub-element.
    We target only the top-level one.
    """
    # The top-level (at ...) in a footprint is directly inside the footprint block,
    # before any sub-elements.  We match the first occurrence at depth 1.
    angle_str = f" {angle:.4f}".rstrip("0").rstrip(".")
    if angle_str in (" 0", " 0."):
        angle_str = ""

    new_at = f'(at {x:.4f} {y:.4f}{angle_str})'

    # Find the first (at ...) that is a direct child (depth=1 relative to block)
    depth = 0
    i = 0
    n = len(block)
    while i < n:
        if block[i] == '(':
            depth += 1
            if depth == 2:  # direct child of footprint
                # Check if this is (at
                rest = block[i:]
                if rest.startswith('(at ') or rest.startswith('(at\t'):
                    # Find end of this (at ...) expression
                    end = i + 1
                    inner_depth = 1
                    while end < n and inner_depth > 0:
                        if block[end] == '(':
                            inner_depth += 1
                        elif block[end] == ')':
                            inner_depth -= 1
                        end += 1
                    return block[:i] + new_at + block[end:]
        elif block[i] == ')':
            depth -= 1
        i += 1
    return block  # fallback: no change


def _update_layer(block: str, side: str) -> str:
    """
    If side == "back", replace layer "F.Cu" → "B.Cu" in the footprint
    (just the footprint declaration line, not pad layers).
    """
    if side.lower() in ("back", "b", "bottom"):
        # Replace the footprint-level layer declaration
        # Pattern: (layer "F.Cu")  at top level of the block
        block = re.sub(r'\(layer "F\.Cu"\)', '(layer "B.Cu")', block, count=1)
    else:
        block = re.sub(r'\(layer "B\.Cu"\)', '(layer "F.Cu")', block, count=1)
    return block


def place_footprints(content: str, placements: List[Placement]) -> str:
    """
    Apply `placements` to `content` (string content of a .kicad_pcb file).
    Returns the updated content string.
    """
    # Build lookup
    place_map = {p.ref: p for p in placements}

    blocks = _find_footprint_blocks(content)
    if not blocks:
        return content

    # Process in reverse order so indices stay valid
    blocks.sort(key=lambda t: t[0], reverse=True)
    for (start, end, ref) in blocks:
        if ref not in place_map:
            continue
        p = place_map[ref]
        block = content[start:end]
        block = _update_at_line(block, p.x, p.y, p.angle)
        block = _update_layer(block, p.side)
        content = content[:start] + block + content[end:]

    return content


def get_current_positions(content: str) -> List[dict]:
    """
    Return current footprint positions as a list of dicts.
    Useful for inspecting a board before placing.
    """
    blocks = _find_footprint_blocks(content)
    result = []
    for (start, end, ref) in blocks:
        block = content[start:end]
        at_match = re.search(r'\(at\s+([\-\d.]+)\s+([\-\d.]+)(?:\s+([\-\d.]+))?\)', block)
        layer_match = re.search(r'\(layer "([^"]+)"\)', block)
        if at_match:
            x = float(at_match.group(1))
            y = float(at_match.group(2))
            angle = float(at_match.group(3)) if at_match.group(3) else 0.0
            layer = layer_match.group(1) if layer_match else "F.Cu"
            result.append({"ref": ref, "x": x, "y": y, "angle": angle, "layer": layer})
    return result


# ---------------------------------------------------------------------------
# Auto-placement helpers
# ---------------------------------------------------------------------------

def auto_place_grid(
    refs: List[str],
    origin_x: float = 10.0,
    origin_y: float = 10.0,
    cols: int = 5,
    col_spacing: float = 10.0,
    row_spacing: float = 10.0,
    side: str = "front",
) -> List[Placement]:
    """
    Arrange components in a grid starting at (origin_x, origin_y).
    Useful for initial placement before manual fine-tuning.
    """
    placements = []
    for i, ref in enumerate(refs):
        col = i % cols
        row = i // cols
        placements.append(Placement(
            ref=ref,
            x=origin_x + col * col_spacing,
            y=origin_y + row * row_spacing,
            angle=0.0,
            side=side,
        ))
    return placements


def auto_place_from_groups(groups: List[dict]) -> List[Placement]:
    """
    Place components by functional group.

    groups format:
    [
      {
        "label": "Power supply",
        "origin": [5.0, 5.0],
        "cols": 3,
        "col_spacing": 8.0,
        "row_spacing": 8.0,
        "refs": ["U1", "C1", "C2", "L1", "D1"]
      },
      {
        "label": "MCU area",
        "origin": [40.0, 10.0],
        "refs": ["U2", "C3", "C4", "R1", "R2", "X1"]
      }
    ]
    """
    all_placements = []
    for group in groups:
        refs = group["refs"]
        ox, oy = group.get("origin", [10.0, 10.0])
        cols = group.get("cols", max(1, len(refs)))
        cs = group.get("col_spacing", 8.0)
        rs = group.get("row_spacing", 8.0)
        side = group.get("side", "front")
        all_placements.extend(auto_place_grid(refs, ox, oy, cols, cs, rs, side))
    return all_placements


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Place footprints in a .kicad_pcb file")
    parser.add_argument("pcb",    help="Input .kicad_pcb file")
    parser.add_argument("placements", nargs="?", help="JSON placements file (or use --list-current)")
    parser.add_argument("--out",  default=None, help="Output PCB file (default: overwrite input)")
    parser.add_argument("--list-current", action="store_true", help="Print current positions and exit")
    parser.add_argument("--auto-grid", action="store_true",
                        help="Auto-place all footprints in a grid (useful starting point)")
    args = parser.parse_args()

    content = Path(args.pcb).read_text(encoding="utf-8")

    if args.list_current:
        positions = get_current_positions(content)
        print(json.dumps(positions, indent=2))
        return

    if args.auto_grid:
        positions = get_current_positions(content)
        refs = [p["ref"] for p in positions if p["ref"]]
        placements = auto_place_grid(refs)
        new_content = place_footprints(content, placements)
    elif args.placements:
        raw = json.loads(Path(args.placements).read_text())
        placements = [Placement(**p) for p in raw]
        new_content = place_footprints(content, placements)
    else:
        parser.print_help()
        return

    out_path = args.out or args.pcb
    if out_path == args.pcb:
        Path(args.pcb + ".bak").write_text(content, encoding="utf-8")
    Path(out_path).write_text(new_content, encoding="utf-8")
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
