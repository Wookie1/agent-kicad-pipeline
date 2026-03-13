#!/usr/bin/env python3
"""
kicad_symbol_builder.py
-----------------------
Build a KiCad 6+ symbol (.kicad_sym) file from a Python spec dict.

Usage (CLI):
    python kicad_symbol_builder.py spec.json [--out my_lib.kicad_sym]

Usage (import):
    from helpers.kicad.kicad_symbol_builder import build_symbol_library, SymbolSpec, PinSpec
    lib_sexpr = build_symbol_library([spec1, spec2])
    open("my_lib.kicad_sym","w").write(lib_sexpr)

Pin direction values   : "input","output","bidirectional","tri_state",
                         "passive","unspecified","power_in","power_out",
                         "open_collector","open_emitter","no_connect"
Pin type values        : "line","inverted","clock","inverted_clock",
                         "input_low","clock_low","output_low",
                         "falling_edge_clock","non_logic"
Body style             : "rectangle","custom_lines"
"""

import json
import sys
import argparse
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path


def _uid() -> str:
    return str(uuid.uuid4())


def _q(s: str) -> str:
    """Wrap string in KiCad double-quotes (escape existing quotes)."""
    return '"' + s.replace('"', '\\"') + '"'


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Data classes for symbol specification
# ---------------------------------------------------------------------------

@dataclass
class PinSpec:
    """Specification for a single pin."""
    number: str                         # pin number as string, e.g. "1", "A3"
    name: str                           # pin name, e.g. "VCC", "GND", "~{RESET}"
    direction: str = "bidirectional"    # see module docstring for valid values
    pin_type: str = "line"              # graphical type
    x: float = 0.0                      # pin endpoint X (where the wire connects)
    y: float = 0.0                      # pin endpoint Y
    length: float = 2.54                # pin stub length in mm (2.54 = 100 mil)
    angle: float = 0.0                  # 0=right 90=up 180=left 270=down (degrees)
    # Derived from angle if not overridden
    name_offset: float = 1.016          # space between pin body and name text
    hide_name: bool = False
    hide_number: bool = False


@dataclass
class BodyLine:
    """A line in the symbol body (for non-rectangular bodies)."""
    x1: float; y1: float
    x2: float; y2: float
    width: float = 0.0


@dataclass
class BodyArc:
    cx: float; cy: float
    sx: float; sy: float   # start point
    ex: float; ey: float   # end point
    width: float = 0.0


@dataclass
class BodyCircle:
    cx: float; cy: float
    r: float
    filled: bool = False
    width: float = 0.0


@dataclass
class SymbolSpec:
    """Full specification for one schematic symbol."""
    name: str                           # symbol name (used as lib_id component)
    reference_prefix: str = "U"         # R, C, L, U, J, Q, etc.
    value: str = ""                     # default value (e.g. component part number)
    footprint: str = ""                 # default footprint lib_id
    datasheet: str = ""
    description: str = ""
    keywords: str = ""
    # Body geometry
    body_style: str = "rectangle"       # "rectangle" or "custom_lines"
    body_x: float = -5.08              # rectangle corner 1 X  (body_style=rectangle)
    body_y: float = -5.08              # rectangle corner 1 Y
    body_w: float = 10.16              # rectangle width
    body_h: float = 10.16             # rectangle height
    body_fill: str = "background"       # "none","background","outline"
    custom_lines: List[BodyLine] = field(default_factory=list)
    custom_arcs: List[BodyArc]   = field(default_factory=list)
    custom_circles: List[BodyCircle] = field(default_factory=list)
    pins: List[PinSpec] = field(default_factory=list)
    # Extra free-form properties (key → value)
    properties: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Auto-layout helpers
# ---------------------------------------------------------------------------

STANDARD_PITCH = 2.54   # 100 mil

def auto_layout_pins(
    left_pins: List[str],    # list of "num:name:dir" strings
    right_pins: List[str],
    top_pins: List[str]   = None,
    bottom_pins: List[str] = None,
    pitch: float = STANDARD_PITCH,
    pin_length: float = 2.54,
) -> List[PinSpec]:
    """
    Generate PinSpec objects arranged on the four sides of a box.
    Pin string format: "num:name" or "num:name:direction"
    e.g. ["1:VCC:power_in", "2:GND:power_in", "3:SCL:bidirectional"]
    Returns a list of PinSpec and the implied body bounds (for use in SymbolSpec).
    """

    def parse(pin_str: str):
        parts = pin_str.split(":")
        num  = parts[0]
        name = parts[1] if len(parts) > 1 else parts[0]
        dirn = parts[2] if len(parts) > 2 else "bidirectional"
        return num, name, dirn

    specs: List[PinSpec] = []

    def _side(pins_list, side: str):
        if not pins_list:
            return
        for i, ps in enumerate(pins_list):
            num, name, dirn = parse(ps)
            idx = i + 1
            if side == "left":
                x = -(pin_length)
                y = -(idx - 1) * pitch
                angle = 0.0
            elif side == "right":
                x = pin_length
                y = -(idx - 1) * pitch
                angle = 180.0
            elif side == "top":
                x = (idx - 1) * pitch
                y = pin_length
                angle = 270.0
            else:  # bottom
                x = (idx - 1) * pitch
                y = -(pin_length)
                angle = 90.0
            specs.append(PinSpec(
                number=num, name=name, direction=dirn,
                x=x, y=y, angle=angle, length=pin_length
            ))

    _side(left_pins,   "left")
    _side(right_pins,  "right")
    _side(top_pins,    "top")
    _side(bottom_pins, "bottom")
    return specs


# ---------------------------------------------------------------------------
# S-expression generators
# ---------------------------------------------------------------------------

def _property_sexpr(key: str, value: str, x: float, y: float,
                    ref: int = 0, hide: bool = False,
                    font_size: float = 1.27) -> str:
    vis = ' (hide yes)' if hide else ''
    return (
        f'    (property {_q(key)} {_q(value)}\n'
        f'      (at {_fmt(x)} {_fmt(y)} 0)\n'
        f'      (effects\n'
        f'        (font (size {_fmt(font_size)} {_fmt(font_size)}))\n'
        f'      ){vis}\n'
        f'    )\n'
    )


def _pin_sexpr(pin: PinSpec) -> str:
    hide_name   = ' (name (hide yes))' if pin.hide_name   else ''
    hide_number = ' (number (hide yes))' if pin.hide_number else ''
    return (
        f'    (pin {pin.direction} {pin.pin_type}\n'
        f'      (at {_fmt(pin.x)} {_fmt(pin.y)} {_fmt(pin.angle)})\n'
        f'      (length {_fmt(pin.length)})\n'
        f'      (name {_q(pin.name)}\n'
        f'        (effects (font (size 1.27 1.27))){hide_name}\n'
        f'      )\n'
        f'      (number {_q(pin.number)}\n'
        f'        (effects (font (size 1.27 1.27))){hide_number}\n'
        f'      )\n'
        f'    )\n'
    )


def _rect_sexpr(x1, y1, x2, y2, fill: str = "background") -> str:
    return (
        f'    (rectangle\n'
        f'      (start {_fmt(x1)} {_fmt(y1)})\n'
        f'      (end   {_fmt(x2)} {_fmt(y2)})\n'
        f'      (stroke (width 0) (type default))\n'
        f'      (fill (type {fill}))\n'
        f'    )\n'
    )


def _line_body_sexpr(bl: BodyLine) -> str:
    return (
        f'    (polyline\n'
        f'      (pts (xy {_fmt(bl.x1)} {_fmt(bl.y1)}) (xy {_fmt(bl.x2)} {_fmt(bl.y2)}))\n'
        f'      (stroke (width {_fmt(bl.width)}) (type default))\n'
        f'      (fill (type none))\n'
        f'    )\n'
    )


def _circle_body_sexpr(bc: BodyCircle) -> str:
    fill = "outline" if bc.filled else "none"
    return (
        f'    (circle\n'
        f'      (center {_fmt(bc.cx)} {_fmt(bc.cy)})\n'
        f'      (radius {_fmt(bc.r)})\n'
        f'      (stroke (width {_fmt(bc.width)}) (type default))\n'
        f'      (fill (type {fill}))\n'
        f'    )\n'
    )


def _symbol_sexpr(spec: SymbolSpec) -> str:
    lines = []
    lines.append(f'  (symbol {_q(spec.name)}\n')
    lines.append(f'    (pin_names (offset 1.016))\n')
    lines.append(f'    (in_bom yes) (on_board yes)\n')

    # Standard properties
    ref_val = spec.value if spec.value else spec.name
    lines.append(_property_sexpr("Reference", spec.reference_prefix, -2.54, 2.54, ref=0))
    lines.append(_property_sexpr("Value",     ref_val,               0,     -2.54, ref=1))
    lines.append(_property_sexpr("Footprint", spec.footprint,        0,     -5.08, ref=2, hide=True))
    lines.append(_property_sexpr("Datasheet", spec.datasheet,        0,     -7.62, ref=3, hide=True))

    if spec.description:
        lines.append(_property_sexpr("Description", spec.description, 0, 0, hide=True))
    if spec.keywords:
        lines.append(_property_sexpr("ki_keywords", spec.keywords, 0, 0, hide=True))

    # Extra user properties
    for k, v in spec.properties.items():
        lines.append(_property_sexpr(k, v, 0, 0, hide=True))

    # Body sub-symbol (unit 1, style 1)
    lines.append(f'    (symbol {_q(spec.name + "_1_1")}\n')

    if spec.body_style == "rectangle":
        x1 = spec.body_x
        y1 = spec.body_y
        x2 = spec.body_x + spec.body_w
        y2 = spec.body_y + spec.body_h
        lines.append(_rect_sexpr(x1, y1, x2, y2, spec.body_fill))
    else:
        for bl in spec.custom_lines:
            lines.append(_line_body_sexpr(bl))
        for bc in spec.custom_circles:
            lines.append(_circle_body_sexpr(bc))

    for pin in spec.pins:
        lines.append(_pin_sexpr(pin))

    lines.append('    )\n')   # close _1_1 sub-symbol
    lines.append('  )\n')     # close symbol
    return "".join(lines)


def build_symbol_library(specs: List[SymbolSpec], version: int = 20231120) -> str:
    """Return the complete .kicad_sym file content."""
    lines = []
    lines.append(f'(kicad_symbol_lib\n')
    lines.append(f'  (version {version})\n')
    lines.append(f'  (generator "kicad_symbol_builder.py")\n')
    for spec in specs:
        lines.append(_symbol_sexpr(spec))
    lines.append(')\n')
    return "".join(lines)


# ---------------------------------------------------------------------------
# Dict → SymbolSpec loader (for JSON / agent use)
# ---------------------------------------------------------------------------

def spec_from_dict(d: Dict[str, Any]) -> SymbolSpec:
    """
    Convert a plain dict (e.g. from JSON) to a SymbolSpec.

    Minimal dict example:
    {
      "name": "MY_IC",
      "reference_prefix": "U",
      "value": "MY_IC_V1",
      "description": "Custom controller IC",
      "footprint": "Package_QFP:LQFP-32_7x7mm_P0.8mm",
      "pins": [
        {"number":"1","name":"VCC","direction":"power_in","x":-5.08,"y":0,"angle":0},
        {"number":"2","name":"GND","direction":"power_in","x":-5.08,"y":-2.54,"angle":0},
        {"number":"3","name":"MOSI","direction":"input","x":5.08,"y":0,"angle":180}
      ]
    }

    For auto_layout, you can instead provide:
    {
      "name": "MY_IC",
      "auto_layout": {
        "left_pins":  ["1:VCC:power_in","2:GND:power_in"],
        "right_pins": ["3:MOSI:input","4:MISO:output"]
      }
    }
    """
    pins = []

    if "auto_layout" in d:
        al = d["auto_layout"]
        pins = auto_layout_pins(
            left_pins   = al.get("left_pins", []),
            right_pins  = al.get("right_pins", []),
            top_pins    = al.get("top_pins"),
            bottom_pins = al.get("bottom_pins"),
            pitch       = al.get("pitch", STANDARD_PITCH),
            pin_length  = al.get("pin_length", STANDARD_PITCH),
        )
    else:
        for pd in d.get("pins", []):
            pins.append(PinSpec(**{k: v for k, v in pd.items() if k in PinSpec.__dataclass_fields__}))

    custom_lines   = [BodyLine(**l)   for l in d.get("custom_lines",   [])]
    custom_arcs    = [BodyArc(**a)    for a in d.get("custom_arcs",    [])]
    custom_circles = [BodyCircle(**c) for c in d.get("custom_circles", [])]

    return SymbolSpec(
        name             = d["name"],
        reference_prefix = d.get("reference_prefix", "U"),
        value            = d.get("value", d["name"]),
        footprint        = d.get("footprint", ""),
        datasheet        = d.get("datasheet", ""),
        description      = d.get("description", ""),
        keywords         = d.get("keywords", ""),
        body_style       = d.get("body_style", "rectangle"),
        body_x           = d.get("body_x", -5.08),
        body_y           = d.get("body_y", -5.08),
        body_w           = d.get("body_w", 10.16),
        body_h           = d.get("body_h", 10.16),
        body_fill        = d.get("body_fill", "background"),
        custom_lines     = custom_lines,
        custom_arcs      = custom_arcs,
        custom_circles   = custom_circles,
        pins             = pins,
        properties       = d.get("properties", {}),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build KiCad .kicad_sym from JSON spec")
    parser.add_argument("spec", help="JSON file with list of symbol specs, or a single spec dict")
    parser.add_argument("--out", default=None, help="Output .kicad_sym file (default: stdout)")
    args = parser.parse_args()

    raw = json.loads(Path(args.spec).read_text())
    if isinstance(raw, dict):
        raw = [raw]  # single symbol

    specs = [spec_from_dict(d) for d in raw]
    lib_content = build_symbol_library(specs)

    if args.out:
        Path(args.out).write_text(lib_content, encoding="utf-8")
        print(f"Written to {args.out}")
    else:
        print(lib_content)


if __name__ == "__main__":
    main()
