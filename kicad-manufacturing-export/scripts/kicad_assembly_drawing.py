#!/usr/bin/env python3
"""
kicad_assembly_drawing.py
--------------------------
Generate an assembly drawing from a KiCad PCB file.

Produces:
  - SVG assembly drawing with component outlines, reference designators,
    pin-1 markers, board outline, and a component table
  - Optional PDF via reportlab (if installed)

The assembly drawing is a manufacturing deliverable showing the assembler
where to place each component.

Dependencies:
    pip install svgwrite reportlab   (reportlab optional)

Usage (CLI):
    python kicad_assembly_drawing.py board.kicad_pcb [--out assembly.svg] [--pdf]

Usage (import):
    from helpers.kicad.kicad_assembly_drawing import generate_assembly_drawing
    svg_text = generate_assembly_drawing("board.kicad_pcb", side="front")
"""

import re
import json
import sys
import math
import argparse
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from pathlib import Path

try:
    import svgwrite
    HAS_SVG = True
except ImportError:
    HAS_SVG = False

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas as pdf_canvas
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


# ---------------------------------------------------------------------------
# PCB parser: extract what we need for the drawing
# ---------------------------------------------------------------------------

@dataclass
class FpData:
    ref: str
    value: str
    x: float
    y: float
    angle: float
    layer: str      # "F.Cu" or "B.Cu"
    # Courtyard bounding box (approximate, from footprint block)
    cx1: float = 0.0; cy1: float = 0.0
    cx2: float = 0.0; cy2: float = 0.0
    fab_lines: List[Tuple] = field(default_factory=list)  # (x1,y1,x2,y2)


@dataclass
class BoardOutline:
    lines: List[Tuple] = field(default_factory=list)   # (x1,y1,x2,y2)
    arcs:  List[Tuple] = field(default_factory=list)   # (cx,cy,sx,sy,ex,ey)
    min_x: float = 0.0; min_y: float = 0.0
    max_x: float = 100.0; max_y: float = 100.0


def _parse_footprints(content: str, side: str) -> List[FpData]:
    """Extract footprint position/reference data from PCB content."""
    target_layer = "F.Cu" if side == "front" else "B.Cu"
    footprints = []

    # Find each footprint block
    fp_pat = re.compile(r'\(footprint\s+"?[^"\s)]*"?')
    for m in fp_pat.finditer(content):
        # Walk to end of this block
        start = m.start()
        depth = 0
        i = start
        while i < len(content):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    block = content[start:i+1]
                    break
            i += 1
        else:
            continue

        # Layer check
        layer_m = re.search(r'\(layer "([^"]+)"\)', block)
        if not layer_m:
            continue
        fp_layer = layer_m.group(1)
        if fp_layer != target_layer:
            continue

        # Position
        at_m = re.search(r'\(at\s+([\-\d.]+)\s+([\-\d.]+)(?:\s+([\-\d.]+))?\)', block)
        if not at_m:
            continue
        fx = float(at_m.group(1))
        fy = float(at_m.group(2))
        fangle = float(at_m.group(3)) if at_m.group(3) else 0.0

        # Reference
        ref_m = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
        if not ref_m:
            ref_m = re.search(r'\(fp_text\s+reference\s+"([^"]+)"', block)
        ref = ref_m.group(1) if ref_m else "?"

        # Value
        val_m = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
        if not val_m:
            val_m = re.search(r'\(fp_text\s+value\s+"([^"]+)"', block)
        value = val_m.group(1) if val_m else ""

        # Approximate courtyard from fab layer lines
        fab_lines = []
        for fl in re.finditer(r'\(fp_line\s+\(start\s+([\-\d.]+)\s+([\-\d.]+)\)\s+\(end\s+([\-\d.]+)\s+([\-\d.]+)\)\s+\(layer\s+"F\.Fab"\)', block):
            lx1, ly1 = float(fl.group(1)), float(fl.group(2))
            lx2, ly2 = float(fl.group(3)), float(fl.group(4))
            # Transform from local to global coordinates
            a = math.radians(fangle)
            def rot(px, py):
                return (
                    fx + px * math.cos(a) - py * math.sin(a),
                    fy + px * math.sin(a) + py * math.cos(a)
                )
            glx1, gly1 = rot(lx1, ly1)
            glx2, gly2 = rot(lx2, ly2)
            fab_lines.append((glx1, gly1, glx2, gly2))

        # Bounding box from fab lines
        if fab_lines:
            xs = [p[0] for l in fab_lines for p in [(l[0],l[1]),(l[2],l[3])]]
            ys = [p[1] for l in fab_lines for p in [(l[0],l[1]),(l[2],l[3])]]
            cx1, cy1, cx2, cy2 = min(xs), min(ys), max(xs), max(ys)
        else:
            cx1 = cy1 = cx2 = cy2 = 0.0

        footprints.append(FpData(
            ref=ref, value=value, x=fx, y=fy, angle=fangle,
            layer=fp_layer, cx1=cx1, cy1=cy1, cx2=cx2, cy2=cy2,
            fab_lines=fab_lines
        ))

    return footprints


def _parse_board_outline(content: str) -> BoardOutline:
    outline = BoardOutline()
    xs, ys = [], []

    for m in re.finditer(r'\(gr_line\s+\(start\s+([\-\d.]+)\s+([\-\d.]+)\)\s+\(end\s+([\-\d.]+)\s+([\-\d.]+)\)\s+\(layer\s+"Edge\.Cuts"\)', content):
        x1, y1, x2, y2 = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
        outline.lines.append((x1, y1, x2, y2))
        xs += [x1, x2]; ys += [y1, y2]

    for m in re.finditer(r'\(gr_arc.*?\(layer\s+"Edge\.Cuts"\)', content, re.DOTALL):
        block = m.group(0)
        s = re.search(r'\(start\s+([\-\d.]+)\s+([\-\d.]+)\)', block)
        e = re.search(r'\(end\s+([\-\d.]+)\s+([\-\d.]+)\)', block)
        if s and e:
            sx, sy = float(s.group(1)), float(s.group(2))
            ex, ey = float(e.group(1)), float(e.group(2))
            outline.arcs.append((sx, sy, ex, ey, sx, sy))   # simplified
            xs += [sx, ex]; ys += [sy, ey]

    if xs:
        outline.min_x, outline.max_x = min(xs), max(xs)
        outline.min_y, outline.max_y = min(ys), max(ys)

    return outline


# ---------------------------------------------------------------------------
# SVG generator
# ---------------------------------------------------------------------------

SVG_SCALE = 5.0   # pixels per mm
MARGIN    = 20    # pixels margin

COLORS = {
    "board":      "#1a3a1a",
    "fab_line":   "#f0f0f0",
    "silk":       "#ffffff",
    "courtyard":  "#ffaa00",
    "ref_text":   "#ffff00",
    "outline":    "#ffff00",
    "grid":       "#2a2a2a",
    "table_bg":   "#f8f8f8",
    "table_head": "#ccddcc",
}


def _mm_to_px(v: float, origin: float = 0.0) -> float:
    return (v - origin) * SVG_SCALE + MARGIN


def generate_assembly_drawing_svg(
    pcb_path: str,
    side: str = "front",
    output_path: str = None,
) -> str:
    """
    Generate an SVG assembly drawing for `side` ("front" or "back").
    Returns SVG text. If output_path given, also writes to file.
    """
    if not HAS_SVG:
        return "# svgwrite not installed. Run: pip install svgwrite"

    content = Path(pcb_path).read_text(encoding="utf-8")
    footprints = _parse_footprints(content, side)
    outline    = _parse_board_outline(content)

    board_w_mm = outline.max_x - outline.min_x
    board_h_mm = outline.max_y - outline.min_y
    svg_w = int(board_w_mm * SVG_SCALE) + 2 * MARGIN + 220   # extra for table
    svg_h = int(board_h_mm * SVG_SCALE) + 2 * MARGIN + 60    # extra for title

    dwg = svgwrite.Drawing(output_path or "assembly.svg",
                            size=(f"{svg_w}px", f"{svg_h}px"))

    # Background
    dwg.add(dwg.rect((0, 0), (svg_w, svg_h), fill="#222222"))

    # Board outline
    def px(x): return _mm_to_px(x, outline.min_x)
    def py(y): return _mm_to_px(y, outline.min_y)

    for (x1, y1, x2, y2) in outline.lines:
        dwg.add(dwg.line(
            (px(x1), py(y1)), (px(x2), py(y2)),
            stroke=COLORS["outline"], stroke_width=1.5
        ))

    # Footprints
    for fp in footprints:
        if fp.fab_lines:
            for (lx1, ly1, lx2, ly2) in fp.fab_lines:
                dwg.add(dwg.line(
                    (px(lx1), py(ly1)), (px(lx2), py(ly2)),
                    stroke=COLORS["fab_line"], stroke_width=0.8
                ))
        else:
            # Fallback: draw a small cross at the component centre
            cx, cy = px(fp.x), py(fp.y)
            dwg.add(dwg.line((cx-4, cy), (cx+4, cy), stroke=COLORS["fab_line"], stroke_width=0.8))
            dwg.add(dwg.line((cx, cy-4), (cx, cy+4), stroke=COLORS["fab_line"], stroke_width=0.8))

        # Reference designator
        dwg.add(dwg.text(
            fp.ref,
            insert=(px(fp.x), py(fp.y) - 3),
            fill=COLORS["ref_text"],
            font_size="7px",
            font_family="monospace",
            text_anchor="middle",
        ))

        # Pin-1 indicator: small filled circle at component position + offset toward pin 1
        a = math.radians(fp.angle)
        pin1_offset = 1.5  # mm approximate
        p1x = fp.x + pin1_offset * math.cos(a + math.pi)
        p1y = fp.y + pin1_offset * math.sin(a + math.pi)
        dwg.add(dwg.circle((px(p1x), py(p1y)), r=2,
                             fill=COLORS["courtyard"], opacity=0.8))

    # Title block
    project_name = Path(pcb_path).stem
    title_y = int(board_h_mm * SVG_SCALE) + 2 * MARGIN + 15
    dwg.add(dwg.text(
        f"ASSEMBLY DRAWING — {project_name.upper()} — {side.upper()} SIDE",
        insert=(MARGIN, title_y),
        fill="white", font_size="11px", font_family="sans-serif",
    ))
    dwg.add(dwg.text(
        f"Board: {board_w_mm:.1f} x {board_h_mm:.1f} mm  |  Components: {len(footprints)}",
        insert=(MARGIN, title_y + 16),
        fill="#aaaaaa", font_size="9px", font_family="sans-serif",
    ))

    # Component table (right side)
    table_x = int(board_w_mm * SVG_SCALE) + 2 * MARGIN + 10
    table_y = MARGIN
    row_h = 14
    col_w_ref = 50; col_w_val = 140

    dwg.add(dwg.rect((table_x, table_y),
                      (col_w_ref + col_w_val, row_h),
                      fill=COLORS["table_head"]))
    dwg.add(dwg.text("Ref", insert=(table_x + 3, table_y + 10),
                      fill="black", font_size="9px", font_weight="bold"))
    dwg.add(dwg.text("Value", insert=(table_x + col_w_ref + 3, table_y + 10),
                      fill="black", font_size="9px", font_weight="bold"))

    for i, fp in enumerate(sorted(footprints, key=lambda f: f.ref)):
        ry = table_y + (i + 1) * row_h
        bg = COLORS["table_bg"] if i % 2 == 0 else "#eeeeee"
        dwg.add(dwg.rect((table_x, ry), (col_w_ref + col_w_val, row_h), fill=bg))
        dwg.add(dwg.text(fp.ref, insert=(table_x + 3, ry + 10),
                          fill="black", font_size="8px"))
        # Truncate long values
        val_text = fp.value[:22] if fp.value else ""
        dwg.add(dwg.text(val_text, insert=(table_x + col_w_ref + 3, ry + 10),
                          fill="#333333", font_size="8px"))

    svg_text = dwg.tostring()
    if output_path:
        Path(output_path).write_text(svg_text, encoding="utf-8")
        print(f"Assembly drawing written: {output_path}")

    return svg_text


def generate_assembly_drawing(
    pcb_path: str,
    side: str = "front",
    output_path: str = None,
) -> str:
    """Convenience wrapper: returns SVG text."""
    return generate_assembly_drawing_svg(pcb_path, side, output_path)


def generate_assembly_pdf(pcb_path: str, output_path: str, side: str = "front") -> None:
    """Generate a PDF assembly drawing using reportlab."""
    if not HAS_PDF:
        print("reportlab not installed. Run: pip install reportlab")
        return

    content = Path(pcb_path).read_text(encoding="utf-8")
    footprints = _parse_footprints(content, side)
    outline    = _parse_board_outline(content)

    page_w, page_h = landscape(A4)
    c = pdf_canvas.Canvas(output_path, pagesize=landscape(A4))

    board_w = outline.max_x - outline.min_x
    board_h = outline.max_y - outline.min_y

    scale = min((page_w - 60*mm) / (board_w * mm),
                (page_h - 40*mm) / (board_h * mm))

    ox = 20 * mm
    oy = page_h - 20 * mm

    def bx(x): return ox + (x - outline.min_x) * mm * scale
    def by(y): return oy - (y - outline.min_y) * mm * scale

    # Board outline
    c.setStrokeColorRGB(1, 1, 0)
    c.setLineWidth(1)
    for (x1, y1, x2, y2) in outline.lines:
        c.line(bx(x1), by(y1), bx(x2), by(y2))

    # Components
    c.setFont("Helvetica", 5)
    for fp in footprints:
        cx, cy = bx(fp.x), by(fp.y)
        if fp.fab_lines:
            c.setStrokeColorRGB(0.9, 0.9, 0.9)
            for (lx1, ly1, lx2, ly2) in fp.fab_lines:
                c.line(bx(lx1), by(ly1), bx(lx2), by(ly2))
        else:
            c.setStrokeColorRGB(0.9, 0.9, 0.9)
            c.line(cx - 3, cy, cx + 3, cy)
            c.line(cx, cy - 3, cx, cy + 3)

        c.setFillColorRGB(1, 1, 0)
        c.drawCentredString(cx, cy + 4, fp.ref)

    # Title
    c.setFont("Helvetica-Bold", 10)
    c.setFillColorRGB(0, 0, 0)
    project = Path(pcb_path).stem
    c.drawString(20 * mm, 15 * mm,
                 f"Assembly Drawing — {project} — {side.upper()} side"
                 f"   ({board_w:.1f} x {board_h:.1f} mm, {len(footprints)} components)")

    c.save()
    print(f"PDF assembly drawing written: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate KiCad PCB assembly drawing")
    parser.add_argument("pcb", help="Input .kicad_pcb file")
    parser.add_argument("--out",  default=None, help="Output SVG file path")
    parser.add_argument("--pdf",  action="store_true", help="Also generate PDF")
    parser.add_argument("--side", default="front", choices=["front","back"],
                        help="Board side (default: front)")
    args = parser.parse_args()

    out_svg = args.out or (Path(args.pcb).stem + f"_assembly_{args.side}.svg")
    generate_assembly_drawing_svg(args.pcb, side=args.side, output_path=out_svg)

    if args.pdf:
        out_pdf = Path(out_svg).with_suffix(".pdf")
        generate_assembly_pdf(args.pcb, str(out_pdf), side=args.side)


if __name__ == "__main__":
    main()
