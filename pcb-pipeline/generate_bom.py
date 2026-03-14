#!/usr/bin/env python3
"""
generate_bom.py
---------------
Generate a BOM CSV from schematic_config.json.
Does NOT require kicad-cli or a valid .net file.
Reads the "symbols" or "components" array directly from schematic_config.json.

Usage:
    python3 generate_bom.py <schematic_config.json> <output_bom.csv>

Output columns:
    Reference, Value, Footprint, Quantity, Description, LCSC_Part#
"""

import json
import csv
import sys
from pathlib import Path
from collections import defaultdict


def load_config(config_path: str) -> dict:
    p = Path(config_path)
    if not p.exists():
        print(f"ERROR: schematic_config.json not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    if p.stat().st_size == 0:
        print(f"ERROR: schematic_config.json is empty: {config_path}", file=sys.stderr)
        sys.exit(1)
    return json.loads(p.read_text())


def get_components(config: dict) -> list:
    """Accept both "symbols" and "components" keys."""
    syms = config.get("symbols", config.get("components", []))
    if not syms:
        print("WARNING: No components found in schematic_config.json", file=sys.stderr)
    return syms


def get_field(sym: dict, *keys, default=""):
    """Get first matching key from a symbol dict."""
    for k in keys:
        if k in sym:
            return str(sym[k])
    return default


def generate_bom(config_path: str, output_path: str):
    config = load_config(config_path)
    components = get_components(config)

    # Group identical components (same value + footprint)
    groups = defaultdict(list)
    for sym in components:
        ref = get_field(sym, "ref", "reference", "designator")
        if not ref or ref.startswith("#"):  # skip power symbols
            continue
        val = get_field(sym, "value", "val")
        fp  = get_field(sym, "footprint", "footprint_id")
        desc = get_field(sym, "description", "desc", default="")
        lcsc = get_field(sym, "lcsc", "lcsc_part", "LCSC_Part#", default="")
        lib_id = get_field(sym, "lib_id", "library_id", "symbol")

        # Auto-generate description from lib_id if not provided
        if not desc and lib_id:
            parts = lib_id.split(":")
            desc = parts[-1] if parts else lib_id

        key = (val, fp)
        groups[key].append({
            "ref": ref, "val": val, "fp": fp,
            "desc": desc, "lcsc": lcsc
        })

    # Write CSV
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for (val, fp), items in sorted(groups.items(), key=lambda x: x[1][0]["ref"]):
        refs = ", ".join(sorted(set(i["ref"] for i in items)))
        qty  = len(items)
        desc = items[0]["desc"]
        lcsc = items[0]["lcsc"]
        rows.append({
            "Reference": refs,
            "Value": val,
            "Footprint": fp,
            "Quantity": qty,
            "Description": desc,
            "LCSC_Part#": lcsc,
        })

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Reference", "Value", "Footprint",
            "Quantity", "Description", "LCSC_Part#"
        ])
        writer.writeheader()
        writer.writerows(rows)

    total = sum(r["Quantity"] for r in rows)
    print(f"BOM written: {out_path}  ({len(rows)} line items, {total} total components)")
    for r in rows:
        print(f"  {r["Reference"]:<12} {r["Value"]:<15} x{r["Quantity"]}  {r["Footprint"]}")
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <schematic_config.json> <output_bom.csv>")
        sys.exit(1)
    generate_bom(sys.argv[1], sys.argv[2])
