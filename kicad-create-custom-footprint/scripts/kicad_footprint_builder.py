#!/usr/bin/env python3
"""
kicad_footprint_builder.py
--------------------------
Build a KiCad 6+ footprint (.kicad_mod) file from a Python spec dict.

Supports common package families via factory helpers:
  - SMD pads (any pitch/size)
  - Through-hole pads (round, square, oval)
  - Courtyard, fab layer, silkscreen auto-generation
  - IPC-7351 body outlines

Usage (CLI):
    python kicad_footprint_builder.py spec.json [--out MyPkg.kicad_mod]

Usage (import):
    from helpers.kicad.kicad_footprint_builder import (
        build_footprint, FootprintSpec, PadSpec,
        make_soic, make_qfp, make_tht_dip
    )
    fp_text = build_footprint(make_soic(8, pitch=1.27, pad_w=1.6, pad_h=0.6))
"""

import json
import sys
import math
import uuid
import argparse
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path


def _uid() -> str:
    return str(uuid.uuid4())


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _q(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PadSpec:
    """Single pad definition."""
    number: str                      # pad number string "1","2","A1", etc.
    pad_type: str = "smd"            # "smd","thru_hole","np_thru_hole"
    shape: str = "rect"              # "circle","rect","oval","roundrect","trapezoid","custom"
    x: float = 0.0
    y: float = 0.0
    w: float = 1.6                   # pad width (X dimension)
    h: float = 0.6                   # pad height (Y dimension)
    drill: float = 0.0               # drill diameter (for thru-hole)
    drill_oval_h: float = 0.0        # oval drill height (0 = round)
    angle: float = 0.0
    layers: List[str] = field(default_factory=lambda: ["F.Cu","F.Paste","F.Mask"])
    # roundrect radius ratio (0.25 typical)
    roundrect_ratio: float = 0.25
    net_name: str = ""               # optional net assignment


@dataclass
class FpLine:
    x1: float; y1: float; x2: float; y2: float
    layer: str = "F.Silkscreen"
    width: float = 0.12


@dataclass
class FpArc:
    cx: float; cy: float
    sx: float; sy: float
    ex: float; ey: float
    layer: str = "F.Silkscreen"
    width: float = 0.12


@dataclass
class FpCircle:
    cx: float; cy: float; r: float
    layer: str = "F.Silkscreen"
    width: float = 0.12
    fill: bool = False


@dataclass
class FpText:
    text: str
    x: float = 0.0; y: float = 0.0
    angle: float = 0.0
    layer: str = "F.Silkscreen"
    size: float = 1.0
    thickness: float = 0.15
    bold: bool = False
    kind: str = "user"   # "reference","value","user"


@dataclass
class FootprintSpec:
    name: str
    description: str = ""
    keywords: str = ""
    pads: List[PadSpec] = field(default_factory=list)
    lines: List[FpLine] = field(default_factory=list)
    arcs: List[FpArc] = field(default_factory=list)
    circles: List[FpCircle] = field(default_factory=list)
    texts: List[FpText] = field(default_factory=list)
    layer: str = "F.Cu"
    smd: bool = True
    fab_layer: bool = True   # auto-generate F.Fab body outline from courtyard
    courtyard_expand: float = 0.5    # expand fab outline by this for courtyard
    # manual courtyard override
    courtyard_lines: List[FpLine] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Package factory helpers
# ---------------------------------------------------------------------------

def make_soic(
    pin_count: int,            # total pins (must be even)
    pitch: float = 1.27,       # pitch in mm
    pad_w: float = 1.6,        # pad length (X)
    pad_h: float = 0.6,        # pad width (Y)
    row_spacing: float = 5.4,  # centre-to-centre between rows (Y)
    body_w: float = 3.9,       # body width
    body_h: float = None,      # body height (auto if None)
    name: str = None,
) -> FootprintSpec:
    """Generate an SOIC / SO / SOP footprint."""
    n_side = pin_count // 2
    if body_h is None:
        body_h = (n_side - 1) * pitch + 2.0

    fp_name = name or f"SOIC-{pin_count}_W{body_w:.1f}mm_P{pitch:.2f}mm"
    spec = FootprintSpec(name=fp_name,
                         description=f"SOIC {pin_count} pin, {pitch}mm pitch",
                         keywords="SOIC SO SMD IC")

    half = (n_side - 1) * pitch / 2.0
    row_x = row_spacing / 2.0

    for i in range(n_side):
        y = half - i * pitch
        # Left side (pad 1 at top-left)
        spec.pads.append(PadSpec(
            number=str(i + 1), pad_type="smd", shape="rect" if i == 0 else "rect",
            x=-row_x, y=y, w=pad_w, h=pad_h,
            layers=["F.Cu", "F.Paste", "F.Mask"]
        ))
        # Right side (bottom-right is pin 2*n_side)
        spec.pads.append(PadSpec(
            number=str(pin_count - i), pad_type="smd", shape="rect",
            x=row_x, y=-y, w=pad_w, h=pad_h,
            layers=["F.Cu", "F.Paste", "F.Mask"]
        ))

    # Pin 1 indicator on silk
    spec.lines.append(FpLine(-row_x - pad_w/2 - 0.4, half + 0.5,
                              -row_x - pad_w/2 - 0.4, half - 0.5,
                              layer="F.Silkscreen", width=0.12))
    # Courtyard
    cx = row_x + pad_w/2 + 0.5
    cy = body_h/2 + 0.5
    spec.courtyard_lines = _rect_lines(-cx, -cy, cx, cy, layer="F.Courtyard", width=0.05)
    # Fab body
    _add_fab_body(spec, -body_w/2, -body_h/2, body_w, body_h)
    _add_ref_value(spec)
    return spec


def make_qfp(
    total_pins: int,
    pitch: float = 0.8,
    pad_w: float = 1.5,
    pad_h: float = 0.5,
    body_w: float = 7.0,
    body_h: float = 7.0,
    name: str = None,
) -> FootprintSpec:
    """Generate a QFP footprint (square QFP assumed; use body_w/body_h for LQFP)."""
    n_side = total_pins // 4
    fp_name = name or f"QFP-{total_pins}_W{body_w:.1f}mm_P{pitch:.2f}mm"
    spec = FootprintSpec(name=fp_name,
                         description=f"QFP {total_pins} pins, {pitch}mm pitch",
                         keywords="QFP LQFP SMD IC")

    half_n = (n_side - 1) * pitch / 2.0
    row_x = (body_w / 2) + pad_w / 2 + 0.5   # approximate span to pad centre

    pin = 1
    # Bottom side (pins go left to right)
    for i in range(n_side):
        x = -half_n + i * pitch
        spec.pads.append(PadSpec(number=str(pin), pad_type="smd", shape="rect",
                                  x=x, y=row_x, w=pad_h, h=pad_w,
                                  layers=["F.Cu","F.Paste","F.Mask"]))
        pin += 1
    # Right side (bottom to top)
    for i in range(n_side):
        y = half_n - i * pitch
        spec.pads.append(PadSpec(number=str(pin), pad_type="smd", shape="rect",
                                  x=row_x, y=y, w=pad_w, h=pad_h,
                                  layers=["F.Cu","F.Paste","F.Mask"]))
        pin += 1
    # Top side (right to left)
    for i in range(n_side):
        x = half_n - i * pitch
        spec.pads.append(PadSpec(number=str(pin), pad_type="smd", shape="rect",
                                  x=x, y=-row_x, w=pad_h, h=pad_w,
                                  layers=["F.Cu","F.Paste","F.Mask"]))
        pin += 1
    # Left side (top to bottom)
    for i in range(n_side):
        y = -half_n + i * pitch
        spec.pads.append(PadSpec(number=str(pin), pad_type="smd", shape="rect",
                                  x=-row_x, y=y, w=pad_w, h=pad_h,
                                  layers=["F.Cu","F.Paste","F.Mask"]))
        pin += 1

    _add_fab_body(spec, -body_w/2, -body_h/2, body_w, body_h)
    cy_r = row_x + pad_w/2 + 0.5
    spec.courtyard_lines = _rect_lines(-cy_r, -cy_r, cy_r, cy_r, layer="F.Courtyard", width=0.05)
    _add_ref_value(spec)
    return spec


def make_tht_dip(
    pin_count: int,
    pitch: float = 2.54,
    row_spacing: float = 7.62,
    drill: float = 0.8,
    pad_d: float = 1.6,
    body_w: float = 6.35,
    name: str = None,
) -> FootprintSpec:
    """Generate a DIP through-hole footprint."""
    n_side = pin_count // 2
    fp_name = name or f"DIP-{pin_count}_W{row_spacing:.2f}mm"
    spec = FootprintSpec(name=fp_name, smd=False,
                         description=f"DIP {pin_count} pin THT",
                         keywords="DIP THT IC")

    half = (n_side - 1) * pitch / 2.0
    row_x = row_spacing / 2.0

    for i in range(n_side):
        y = half - i * pitch
        shape = "rect" if i == 0 else "circle"  # pin 1 is square
        spec.pads.append(PadSpec(
            number=str(i + 1), pad_type="thru_hole", shape=shape,
            x=-row_x, y=y, w=pad_d, h=pad_d, drill=drill,
            layers=["*.Cu","*.Mask"]
        ))
        spec.pads.append(PadSpec(
            number=str(pin_count - i), pad_type="thru_hole", shape="circle",
            x=row_x, y=-y, w=pad_d, h=pad_d, drill=drill,
            layers=["*.Cu","*.Mask"]
        ))

    body_h = (n_side - 1) * pitch + 2.5
    _add_fab_body(spec, -body_w/2, -body_h/2, body_w, body_h)
    cx = row_x + pad_d/2 + 0.5
    cy = body_h/2 + 0.5
    spec.courtyard_lines = _rect_lines(-cx, -cy, cx, cy, layer="F.Courtyard", width=0.05)
    _add_ref_value(spec)
    return spec


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _rect_lines(x1, y1, x2, y2, layer="F.Fab", width=0.1) -> List[FpLine]:
    return [
        FpLine(x1, y1, x2, y1, layer, width),
        FpLine(x2, y1, x2, y2, layer, width),
        FpLine(x2, y2, x1, y2, layer, width),
        FpLine(x1, y2, x1, y1, layer, width),
    ]


def _add_fab_body(spec: FootprintSpec, x, y, w, h):
    # Rectangle with chamfer at pin-1 corner
    x2, y2 = x + w, y + h
    c = min(w, h) * 0.1  # chamfer size
    spec.lines += [
        FpLine(x + c, y,  x2,  y,  layer="F.Fab", width=0.1),
        FpLine(x2,  y,  x2, y2,  layer="F.Fab", width=0.1),
        FpLine(x2, y2,  x, y2,  layer="F.Fab", width=0.1),
        FpLine(x,  y2,  x, y + c, layer="F.Fab", width=0.1),
        FpLine(x,  y + c, x + c, y, layer="F.Fab", width=0.1),  # chamfer
    ]


def _add_ref_value(spec: FootprintSpec):
    spec.texts.append(FpText("${REFERENCE}", x=0, y=-3, kind="reference",
                              layer="F.Silkscreen", size=1.0))
    spec.texts.append(FpText("${VALUE}", x=0, y=3, kind="value",
                              layer="F.Fab", size=1.0))


# ---------------------------------------------------------------------------
# S-expression generators
# ---------------------------------------------------------------------------

def _pad_sexpr(pad: PadSpec) -> str:
    layers = " ".join(f'"{l}"' for l in pad.layers)
    drill_str = ""
    if pad.pad_type == "thru_hole":
        if pad.drill_oval_h > 0:
            drill_str = f'    (drill oval {_fmt(pad.drill)} {_fmt(pad.drill_oval_h)})\n'
        else:
            drill_str = f'    (drill {_fmt(pad.drill)})\n'
    rr = f'    (roundrect_rratio {_fmt(pad.roundrect_ratio)})\n' if pad.shape == "roundrect" else ""
    return (
        f'  (pad {_q(pad.number)} {pad.pad_type} {pad.shape}\n'
        f'    (at {_fmt(pad.x)} {_fmt(pad.y)}{(" " + _fmt(pad.angle)) if pad.angle else ""})\n'
        f'    (size {_fmt(pad.w)} {_fmt(pad.h)})\n'
        f'{drill_str}'
        f'{rr}'
        f'    (layers {layers})\n'
        f'    (tstamp {_uid()})\n'
        f'  )\n'
    )


def _line_sexpr(l: FpLine) -> str:
    return (
        f'  (fp_line\n'
        f'    (start {_fmt(l.x1)} {_fmt(l.y1)})\n'
        f'    (end   {_fmt(l.x2)} {_fmt(l.y2)})\n'
        f'    (layer {_q(l.layer)})\n'
        f'    (width {_fmt(l.width)})\n'
        f'  )\n'
    )


def _circle_sexpr(c: FpCircle) -> str:
    fill = "(fill filled)" if c.fill else ""
    return (
        f'  (fp_circle\n'
        f'    (center {_fmt(c.cx)} {_fmt(c.cy)})\n'
        f'    (end {_fmt(c.cx + c.r)} {_fmt(c.cy)})\n'
        f'    (layer {_q(c.layer)})\n'
        f'    (width {_fmt(c.width)})\n'
        f'    {fill}\n'
        f'  )\n'
    )


def _text_sexpr(t: FpText) -> str:
    bold = "(bold yes)" if t.bold else ""
    return (
        f'  (fp_text {t.kind} {_q(t.text)}\n'
        f'    (at {_fmt(t.x)} {_fmt(t.y)}{(" " + _fmt(t.angle)) if t.angle else ""})\n'
        f'    (layer {_q(t.layer)})\n'
        f'    (effects\n'
        f'      (font (size {_fmt(t.size)} {_fmt(t.size)}) (thickness {_fmt(t.thickness)}) {bold})\n'
        f'    )\n'
        f'  )\n'
    )


def build_footprint(spec: FootprintSpec, version: int = 20231120) -> str:
    """Return the complete .kicad_mod file content."""
    lines = []
    layer = spec.layer
    attr = "smd" if spec.smd else "through_hole"

    lines.append(f'(footprint {_q(spec.name)}\n')
    lines.append(f'  (version {version})\n')
    lines.append(f'  (generator "kicad_footprint_builder.py")\n')
    lines.append(f'  (layer {_q(layer)})\n')
    lines.append(f'  (descr {_q(spec.description)})\n')
    lines.append(f'  (tags {_q(spec.keywords)})\n')
    lines.append(f'  (attr {attr})\n')

    for txt in spec.texts:
        lines.append(_text_sexpr(txt))

    for l in spec.lines:
        lines.append(_line_sexpr(l))
    for c in spec.circles:
        lines.append(_circle_sexpr(c))
    for cl in spec.courtyard_lines:
        lines.append(_line_sexpr(cl))
    for pad in spec.pads:
        lines.append(_pad_sexpr(pad))

    lines.append(')\n')
    return "".join(lines)


# ---------------------------------------------------------------------------
# Dict → FootprintSpec loader
# ---------------------------------------------------------------------------

def spec_from_dict(d: Dict[str, Any]) -> FootprintSpec:
    """
    Minimal dict example:
    {
      "name": "MY_SOT23",
      "description": "Custom SOT-23 variant",
      "pads": [
        {"number":"1","pad_type":"smd","shape":"rect","x":-0.95,"y":0,"w":1.1,"h":0.6},
        {"number":"2","pad_type":"smd","shape":"rect","x": 0.95,"y":0,"w":1.1,"h":0.6},
        {"number":"3","pad_type":"smd","shape":"rect","x":0,"y":1.2,"w":1.1,"h":0.6}
      ]
    }

    Factory helpers ('factory' key):
    { "factory": "soic", "pin_count":8, "pitch":1.27 }
    { "factory": "qfp",  "total_pins":32, "pitch":0.8, "body_w":7, "body_h":7 }
    { "factory": "dip",  "pin_count":16, "pitch":2.54 }
    """
    if "factory" in d:
        ftype = d.pop("factory")
        if ftype == "soic":
            return make_soic(**d)
        elif ftype == "qfp":
            return make_qfp(**d)
        elif ftype == "dip":
            return make_tht_dip(**d)
        else:
            raise ValueError(f"Unknown factory: {ftype}")

    pads    = [PadSpec(**{k:v for k,v in p.items() if k in PadSpec.__dataclass_fields__})    for p in d.get("pads",    [])]
    lines   = [FpLine(**{k:v for k,v in l.items() if k in FpLine.__dataclass_fields__})      for l in d.get("lines",   [])]
    circles = [FpCircle(**{k:v for k,v in c.items() if k in FpCircle.__dataclass_fields__})  for c in d.get("circles", [])]
    texts   = [FpText(**{k:v for k,v in t.items() if k in FpText.__dataclass_fields__})      for t in d.get("texts",   [])]
    cy_lines= [FpLine(**{k:v for k,v in l.items() if k in FpLine.__dataclass_fields__})      for l in d.get("courtyard_lines", [])]

    return FootprintSpec(
        name             = d["name"],
        description      = d.get("description",""),
        keywords         = d.get("keywords",""),
        pads             = pads,
        lines            = lines,
        circles          = circles,
        texts            = texts,
        courtyard_lines  = cy_lines,
        smd              = d.get("smd", True),
        fab_layer        = d.get("fab_layer", True),
        courtyard_expand = d.get("courtyard_expand", 0.5),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build KiCad .kicad_mod from JSON spec")
    parser.add_argument("spec", help="JSON file with footprint spec dict (or list of dicts)")
    parser.add_argument("--out", default=None, help="Output file (default: stdout)")
    args = parser.parse_args()

    raw = json.loads(Path(args.spec).read_text())
    if isinstance(raw, list):
        # Multi-footprint: output each to its own file in --out directory
        for item in raw:
            fp = build_footprint(spec_from_dict(item))
            if args.out:
                out_path = Path(args.out) / (item["name"] + ".kicad_mod")
                out_path.write_text(fp, encoding="utf-8")
                print(f"Written: {out_path}")
            else:
                print(fp)
    else:
        fp = build_footprint(spec_from_dict(raw))
        if args.out:
            Path(args.out).write_text(fp, encoding="utf-8")
            print(f"Written to {args.out}")
        else:
            print(fp)


if __name__ == "__main__":
    main()
