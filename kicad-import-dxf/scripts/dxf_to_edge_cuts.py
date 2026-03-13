#!/usr/bin/env python3
"""
dxf_to_edge_cuts.py
--------------------
Parse a DXF file and emit KiCad Edge.Cuts s-expression segments/arcs
that can be injected directly into a .kicad_pcb file.

Dependencies:
    pip install ezdxf

Usage (CLI):
    python dxf_to_edge_cuts.py board_outline.dxf [--layer "Edge.Cuts"] [--out outline.kicad_sexpr]

Usage (import):
    from helpers.kicad.dxf_to_edge_cuts import dxf_to_kicad_edge_cuts
    sexpr_text = dxf_to_kicad_edge_cuts("board.dxf")
    # inject sexpr_text before the closing ) of the .kicad_pcb file
"""

import sys
import argparse
import math
import uuid
from pathlib import Path
from typing import List, Tuple

try:
    import ezdxf
    from ezdxf.math import Vec2
except ImportError:
    sys.exit("ezdxf not installed. Run: pip install ezdxf")


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _fmt(v: float, decimals: int = 6) -> str:
    """Format a float with no trailing zeros."""
    return f"{v:.{decimals}f}".rstrip("0").rstrip(".")


def _pt(x: float, y: float) -> str:
    return f"(xy {_fmt(x)} {_fmt(y)})"


# ---------------------------------------------------------------------------
# DXF entity → KiCad s-expression converters
# (KiCad uses mm; DXF files are typically in mm too, but the script
#  accepts an optional --scale factor for imperial DXF files)
# ---------------------------------------------------------------------------

def _line_sexpr(x1, y1, x2, y2, layer: str, width: float) -> str:
    """gr_line segment."""
    return (
        f'  (gr_line\n'
        f'    (start {_fmt(x1)} {_fmt(y1)})\n'
        f'    (end   {_fmt(x2)} {_fmt(y2)})\n'
        f'    (layer "{layer}")\n'
        f'    (width {_fmt(width)})\n'
        f'    (tstamp {_uid()})\n'
        f'  )\n'
    )


def _arc_sexpr(cx, cy, sx, sy, ex, ey, layer: str, width: float) -> str:
    """
    gr_arc using KiCad 6+ (start/mid/end) format.
    cx,cy  = centre
    sx,sy  = start point
    ex,ey  = end point
    midpoint is computed from centre and the bisecting angle.
    """
    # Compute midpoint angle
    a_start = math.atan2(sy - cy, sx - cx)
    a_end   = math.atan2(ey - cy, ex - cx)
    a_mid   = (a_start + a_end) / 2.0
    # Ensure mid is on the correct arc (always take the shorter arc)
    r = math.hypot(sx - cx, sy - cy)
    mx = cx + r * math.cos(a_mid)
    my = cy + r * math.sin(a_mid)
    return (
        f'  (gr_arc\n'
        f'    (start {_fmt(sx)} {_fmt(sy)})\n'
        f'    (mid   {_fmt(mx)} {_fmt(my)})\n'
        f'    (end   {_fmt(ex)} {_fmt(ey)})\n'
        f'    (layer "{layer}")\n'
        f'    (width {_fmt(width)})\n'
        f'    (tstamp {_uid()})\n'
        f'  )\n'
    )


def _circle_sexpr(cx, cy, r, layer: str, width: float) -> str:
    """gr_circle."""
    return (
        f'  (gr_circle\n'
        f'    (center {_fmt(cx)} {_fmt(cy)})\n'
        f'    (end   {_fmt(cx + r)} {_fmt(cy)})\n'
        f'    (layer "{layer}")\n'
        f'    (width {_fmt(width)})\n'
        f'    (fill none)\n'
        f'    (tstamp {_uid()})\n'
        f'  )\n'
    )


def _spline_to_lines(entity, scale: float, layer: str, width: float) -> List[str]:
    """
    Approximate a SPLINE as polyline segments (ezdxf flattening).
    tolerance controls the chord-error in drawing units.
    """
    segments = []
    try:
        points = list(entity.flattening(distance=0.1))
        for i in range(len(points) - 1):
            x1, y1 = points[i].x * scale, points[i].y * scale
            x2, y2 = points[i + 1].x * scale, points[i + 1].y * scale
            segments.append(_line_sexpr(x1, y1, x2, y2, layer, width))
    except Exception:
        pass
    return segments


def _lwpolyline_to_segments(entity, scale: float, layer: str, width: float) -> List[str]:
    """Convert LWPOLYLINE to gr_line / gr_arc segments."""
    segments = []
    pts = list(entity.get_points(format="xyseb"))  # x, y, start_width, end_width, bulge
    if not pts:
        return segments
    is_closed = entity.is_closed

    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        if j == 0 and not is_closed:
            break
        x1, y1 = pts[i][0] * scale, pts[i][1] * scale
        x2, y2 = pts[j][0] * scale, pts[j][1] * scale
        bulge = pts[i][4]

        if abs(bulge) < 1e-9:
            segments.append(_line_sexpr(x1, y1, x2, y2, layer, width))
        else:
            # Convert bulge → arc centre + points
            dx, dy = x2 - x1, y2 - y1
            chord = math.hypot(dx, dy)
            alpha = 4.0 * math.atan(bulge)
            r = chord / (2.0 * math.sin(alpha / 2.0))
            # Perpendicular bisector
            mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
            perp_angle = math.atan2(dy, dx) + math.pi / 2.0
            d = r * math.cos(alpha / 2.0)
            if bulge < 0:
                d = -d
            cx = mx - d * math.sin(math.atan2(dy, dx))
            cy = my + d * math.cos(math.atan2(dy, dx))
            segments.append(_arc_sexpr(cx, cy, x1, y1, x2, y2, layer, width))
    return segments


def _polyline_to_segments(entity, scale: float, layer: str, width: float) -> List[str]:
    """Convert 3D POLYLINE / legacy POLYLINE."""
    segments = []
    try:
        pts = [v.dxf.location for v in entity.vertices]
        is_closed = entity.is_closed
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            if j == 0 and not is_closed:
                break
            x1, y1 = pts[i].x * scale, pts[i].y * scale
            x2, y2 = pts[j].x * scale, pts[j].y * scale
            segments.append(_line_sexpr(x1, y1, x2, y2, layer, width))
    except Exception:
        pass
    return segments


# ---------------------------------------------------------------------------
# Main conversion function
# ---------------------------------------------------------------------------

def dxf_to_kicad_edge_cuts(
    dxf_path: str,
    layer: str = "Edge.Cuts",
    line_width: float = 0.05,
    scale: float = 1.0,
    dxf_layer_filter: str = None,   # if set, only import entities on this DXF layer
    flip_y: bool = True,            # DXF Y increases upward; KiCad Y increases downward
) -> str:
    """
    Parse `dxf_path` and return a string of KiCad s-expressions for
    Edge.Cuts (or another layer).  Inject the returned string into a
    .kicad_pcb file before its closing ')'.

    Parameters
    ----------
    dxf_path        : path to the DXF file
    layer           : target KiCad layer name (default "Edge.Cuts")
    line_width      : line width in mm (default 0.05 mm)
    scale           : multiply all coordinates by this factor (1.0 for mm DXF)
                      use 25.4 to convert inches → mm
    dxf_layer_filter: if given, only process entities on this DXF layer name
    flip_y          : mirror Y axis (True = standard conversion)

    Returns
    -------
    Multi-line string of KiCad s-expressions ready for injection.
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()

    # Collect all entities (optionally filtered by DXF layer)
    entities = [
        e for e in msp
        if (dxf_layer_filter is None or e.dxf.layer == dxf_layer_filter)
    ]

    if not entities:
        # Fall back: try all entities if filter yields nothing
        entities = list(msp)

    sexprs: List[str] = []
    sexprs.append(f'  ; --- imported from {Path(dxf_path).name} ---\n')

    def fy(y: float) -> float:
        return -y if flip_y else y

    for entity in entities:
        etype = entity.dxftype()

        if etype == "LINE":
            x1 = entity.dxf.start.x * scale
            y1 = fy(entity.dxf.start.y * scale)
            x2 = entity.dxf.end.x * scale
            y2 = fy(entity.dxf.end.y * scale)
            sexprs.append(_line_sexpr(x1, y1, x2, y2, layer, line_width))

        elif etype == "ARC":
            cx = entity.dxf.center.x * scale
            cy = fy(entity.dxf.center.y * scale)
            r  = entity.dxf.radius * scale
            # DXF angles are CCW from +X; KiCad arc uses start/mid/end points
            a_start_deg = entity.dxf.start_angle
            a_end_deg   = entity.dxf.end_angle
            if flip_y:
                # Mirror: negate and swap angles
                a_start_deg, a_end_deg = -a_end_deg, -a_start_deg
            a_start = math.radians(a_start_deg)
            a_end   = math.radians(a_end_deg)
            sx = cx + r * math.cos(a_start)
            sy = cy + r * math.sin(a_start)
            ex = cx + r * math.cos(a_end)
            ey = cy + r * math.sin(a_end)
            sexprs.append(_arc_sexpr(cx, cy, sx, sy, ex, ey, layer, line_width))

        elif etype == "CIRCLE":
            cx = entity.dxf.center.x * scale
            cy = fy(entity.dxf.center.y * scale)
            r  = entity.dxf.radius * scale
            sexprs.append(_circle_sexpr(cx, cy, r, layer, line_width))

        elif etype == "ELLIPSE":
            # Approximate ellipse as 72 line segments
            cx = entity.dxf.center.x * scale
            cy_raw = entity.dxf.center.y * scale
            maj = entity.dxf.major_axis
            ratio = entity.dxf.ratio
            maj_len = math.hypot(maj.x, maj.y) * scale
            min_len = maj_len * ratio
            rot = math.atan2(maj.y, maj.x)
            pts = []
            for i in range(73):
                t = 2 * math.pi * i / 72
                px = cx + maj_len * math.cos(t) * math.cos(rot) - min_len * math.sin(t) * math.sin(rot)
                py = fy(cy_raw) + maj_len * math.cos(t) * math.sin(rot) + min_len * math.sin(t) * math.cos(rot)
                pts.append((px, py))
            for i in range(len(pts) - 1):
                sexprs.append(_line_sexpr(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1], layer, line_width))

        elif etype == "LWPOLYLINE":
            # Apply Y flip to all points
            raw_pts = list(entity.get_points(format="xyseb"))
            flipped = [(p[0] * scale, fy(p[1] * scale), p[2], p[3], p[4]) for p in raw_pts]
            # Temporarily patch entity points for the helper
            # Instead, inline the conversion here
            n = len(flipped)
            is_closed = entity.is_closed
            for i in range(n):
                j = (i + 1) % n
                if j == 0 and not is_closed:
                    break
                x1, y1 = flipped[i][0], flipped[i][1]
                x2, y2 = flipped[j][0], flipped[j][1]
                bulge = flipped[i][4]
                if abs(bulge) < 1e-9:
                    sexprs.append(_line_sexpr(x1, y1, x2, y2, layer, line_width))
                else:
                    dx, dy = x2 - x1, y2 - y1
                    chord = math.hypot(dx, dy)
                    if chord < 1e-12:
                        continue
                    alpha = 4.0 * math.atan(abs(bulge))
                    r = chord / (2.0 * math.sin(alpha / 2.0))
                    mx, my = (x1 + x2) / 2.0, (y1 + y2) / 2.0
                    perp = math.atan2(dy, dx) + math.pi / 2.0
                    d = r * math.cos(alpha / 2.0) * (1 if bulge > 0 else -1)
                    acx = mx - d * math.sin(math.atan2(dy, dx))
                    acy = my + d * math.cos(math.atan2(dy, dx))
                    sexprs.append(_arc_sexpr(acx, acy, x1, y1, x2, y2, layer, line_width))

        elif etype == "SPLINE":
            sexprs.extend(_spline_to_lines(entity, scale, layer, line_width))

        elif etype == "POLYLINE":
            sexprs.extend(_polyline_to_segments(entity, scale, layer, line_width))

        # HATCH, INSERT (blocks), TEXT, DIMENSION are silently skipped
        # Add handling here if needed for your DXF files

    return "".join(sexprs)


def inject_into_pcb(pcb_path: str, sexpr_text: str, backup: bool = True) -> None:
    """
    Insert `sexpr_text` into `pcb_path` just before the last closing ')'.
    Creates a .bak backup by default.
    """
    content = Path(pcb_path).read_text(encoding="utf-8")
    if backup:
        Path(pcb_path + ".bak").write_text(content, encoding="utf-8")
    # Find last ')' which closes the kicad_pcb block
    idx = content.rfind(")")
    if idx == -1:
        raise ValueError("Could not find closing ) in PCB file")
    new_content = content[:idx] + "\n" + sexpr_text + content[idx:]
    Path(pcb_path).write_text(new_content, encoding="utf-8")
    print(f"Injected {len(sexpr_text)} chars into {pcb_path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Convert DXF board outline to KiCad Edge.Cuts s-expressions")
    parser.add_argument("dxf",           help="Input DXF file")
    parser.add_argument("--pcb",         help="If given, inject directly into this .kicad_pcb file")
    parser.add_argument("--out",         help="Write s-expressions to this file instead of stdout")
    parser.add_argument("--layer",       default="Edge.Cuts", help="KiCad layer name (default: Edge.Cuts)")
    parser.add_argument("--width",       type=float, default=0.05, help="Line width in mm (default: 0.05)")
    parser.add_argument("--scale",       type=float, default=1.0,  help="Scale factor (25.4 for inch DXF)")
    parser.add_argument("--dxf-layer",   default=None, help="Only import entities from this DXF layer")
    parser.add_argument("--no-flip-y",   action="store_true",      help="Do not flip Y axis")
    args = parser.parse_args()

    sexpr = dxf_to_kicad_edge_cuts(
        args.dxf,
        layer=args.layer,
        line_width=args.width,
        scale=args.scale,
        dxf_layer_filter=args.dxf_layer,
        flip_y=not args.no_flip_y,
    )

    if args.pcb:
        inject_into_pcb(args.pcb, sexpr)
    elif args.out:
        Path(args.out).write_text(sexpr, encoding="utf-8")
        print(f"Written to {args.out}")
    else:
        print(sexpr)


if __name__ == "__main__":
    main()
