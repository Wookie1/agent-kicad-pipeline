#!/usr/bin/env python3
"""
schematic_preflight.py — Pre-ERC validation for KiCad schematics.

Checks BEFORE running ERC:
  1. Duplicate reference designators
  2. Components with missing or empty Footprint assignments
  3. Power symbols that appear only once (likely floating / disconnected supply)
  4. Net labels that appear only once (dangling label — nothing to connect to)
  5. Schematic file structure (parenthesis balance)
  6. Summary statistics (component count, net count, label count)

Exit codes:
  0 — PASS (no errors; warnings may still be present)
  1 — FAIL (one or more errors found)

Usage:
    /usr/bin/python3 schematic_preflight.py /path/to/board.kicad_sch
    /usr/bin/python3 schematic_preflight.py /path/to/board.kicad_sch --strict
    /usr/bin/python3 schematic_preflight.py /path/to/board.kicad_sch --json
    /usr/bin/python3 schematic_preflight.py /path/to/board.kicad_sch --summary

Always run with /usr/bin/python3 — the venv Python may not have all required modules.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# S-expression block extractor
# ---------------------------------------------------------------------------

def _extract_symbol_blocks(text: str) -> list[str]:
    """
    Extract all top-level (symbol (lib_id ...) ...) blocks from a schematic.
    These represent placed component instances.
    Library definition blocks inside (lib_symbols ...) are excluded.
    """
    blocks: list[str] = []
    pattern = re.compile(r'\(symbol\s+\(')
    n = len(text)
    for m in pattern.finditer(text):
        start = m.start()
        depth = 0
        j = start
        while j < n:
            if text[j] == '(':
                depth += 1
            elif text[j] == ')':
                depth -= 1
                if depth == 0:
                    blocks.append(text[start:j + 1])
                    break
            j += 1
    return blocks


# ---------------------------------------------------------------------------
# Property extraction
# ---------------------------------------------------------------------------

_PROP_RE = re.compile(
    r'\(property\s+"([^"]+)"\s+"([^"]*)"',
    re.IGNORECASE,
)

_LIB_ID_RE = re.compile(r'\(lib_id\s+"([^"]+)"')

# Matches (label "NAME" ...) — net labels
_LABEL_RE = re.compile(r'\(label\s+"([^"]+)"')

# Matches (global_label "NAME" ...) — global labels
_GLOBAL_LABEL_RE = re.compile(r'\(global_label\s+"([^"]+)"')

# Matches (wire (pts ...) ...) — wire segments
_WIRE_RE = re.compile(r'\(wire\s+\(pts')


def _get_property(block: str, prop_name: str) -> Optional[str]:
    """Return the value of the named property from a symbol block, or None."""
    for m in _PROP_RE.finditer(block):
        if m.group(1).lower() == prop_name.lower():
            return m.group(2)
    return None


def _get_lib_id(block: str) -> Optional[str]:
    m = _LIB_ID_RE.search(block)
    return m.group(1) if m else None


def _is_power_symbol(lib_id: Optional[str]) -> bool:
    if lib_id is None:
        return False
    return lib_id.startswith("power:") or "PWR_FLAG" in lib_id


# ---------------------------------------------------------------------------
# Parenthesis balance check
# ---------------------------------------------------------------------------

def _check_paren_balance(text: str) -> int:
    """Return net parenthesis depth. 0 = balanced. Nonzero = malformed file."""
    depth = 0
    in_string = False
    escape_next = False
    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
    return depth


# ---------------------------------------------------------------------------
# Core preflight logic
# ---------------------------------------------------------------------------

def preflight(
    sch_path: str,
    strict: bool = False,
) -> dict:
    """
    Run all preflight checks on *sch_path*.

    Returns a dict:
      {
        "file": str,
        "symbols_scanned": int,
        "power_nets": int,
        "net_labels": int,
        "wire_count": int,
        "paren_balance": int,
        "errors": list[str],
        "warnings": list[str],
        "passed": bool,
      }
    """
    path = Path(sch_path).expanduser().resolve()
    if not path.exists():
        return {
            "file": str(path),
            "symbols_scanned": 0,
            "power_nets": 0,
            "net_labels": 0,
            "wire_count": 0,
            "paren_balance": -1,
            "errors": [f"File not found: {path}"],
            "warnings": [],
            "passed": False,
        }

    text = path.read_text(encoding="utf-8")
    blocks = _extract_symbol_blocks(text)

    errors: list[str] = []
    warnings: list[str] = []
    refs_seen: Counter = Counter()
    power_net_count: Counter = Counter()

    # ---- Check 0: Parenthesis balance ----
    paren_balance = _check_paren_balance(text)
    if paren_balance != 0:
        errors.append(
            f"MALFORMED FILE: parenthesis balance = {paren_balance} (expected 0). "
            "The schematic file has unmatched parentheses — it may be truncated or corrupted."
        )

    # ---- Check 0b: sheet_instances block (KiCad 9.0 requirement) ----
    if '(sheet_instances' not in text:
        errors.append(
            "MISSING SHEET_INSTANCES: the schematic has no (sheet_instances) block. "
            "KiCad 9.0 requires this at the root level for reference designators to resolve. "
            "Without it, all references display as 'R?', 'D?', etc."
        )

    # ---- Count wires ----
    wire_count = len(_WIRE_RE.findall(text))

    # ---- Count net labels (regular and global) ----
    label_names: Counter = Counter()
    for m in _LABEL_RE.finditer(text):
        label_names[m.group(1)] += 1
    for m in _GLOBAL_LABEL_RE.finditer(text):
        label_names[m.group(1)] += 1

    # ---- Process component symbols ----
    for block in blocks:
        ref = _get_property(block, "Reference")
        if ref is None:
            continue

        lib_id = _get_lib_id(block)

        # ---------- Power symbols ----------
        if ref.startswith("#") or _is_power_symbol(lib_id):
            net = _get_property(block, "Value") or ""
            if net and net != "~":
                power_net_count[net] += 1
            continue  # Power ports do not need footprints

        # ---------- Regular components ----------
        refs_seen[ref] += 1

        footprint = _get_property(block, "Footprint")
        if footprint is None or footprint.strip() == "":
            errors.append(
                f"MISSING FOOTPRINT: {ref} ({lib_id or 'unknown lib'}) "
                "has no footprint assigned — assign before running ERC."
            )

    # ---- Check 1: Duplicate references ----
    for ref, count in sorted(refs_seen.items()):
        if count > 1:
            errors.append(
                f"DUPLICATE REFERENCE: '{ref}' appears {count} times — "
                "each component must have a unique reference designator."
            )

    # ---- Check 3: Single-use power nets ----
    for net, count in sorted(power_net_count.items()):
        if count == 1:
            warnings.append(
                f"SINGLE-USE POWER NET: '{net}' appears only once — "
                "check for a missing PWR_FLAG or a disconnected supply symbol."
            )

    # ---- Check 4: Dangling net labels (appear only once) ----
    # A net label that appears only once has nothing to connect to.
    # Exception: labels that match a power net name are intentional references.
    power_net_names = set(power_net_count.keys())
    for label, count in sorted(label_names.items()):
        if count == 1 and label not in power_net_names:
            warnings.append(
                f"SINGLE-USE NET LABEL: '{label}' appears only once — "
                "no other label shares this name, so it connects to nothing. "
                "Check for a typo or missing matching label."
            )

    # ---- Check 5: Schematic has at least some content ----
    if len(refs_seen) == 0 and paren_balance == 0:
        warnings.append(
            "EMPTY SCHEMATIC: No regular component symbols found. "
            "Check that schematic design has been completed."
        )

    # ---- Check 6: Wire count sanity ----
    # For a design with N components, we expect at least N/2 wires.
    # Very low wire count relative to components suggests incomplete wiring.
    if len(refs_seen) > 4 and wire_count < len(refs_seen) // 2:
        warnings.append(
            f"LOW WIRE COUNT: {wire_count} wires for {len(refs_seen)} components — "
            "the schematic may be incompletely wired. "
            "Consider running analyze_schematic_connections() for a full connectivity check."
        )

    passed = len(errors) == 0
    if strict and warnings:
        passed = False

    return {
        "file": str(path),
        "symbols_scanned": len(refs_seen),
        "power_nets": len(power_net_count),
        "net_labels": len(label_names),
        "wire_count": wire_count,
        "paren_balance": paren_balance,
        "errors": errors,
        "warnings": warnings,
        "passed": passed,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _print_report(result: dict, strict: bool) -> None:
    print(f"Preflight: {Path(result['file']).name}")
    print(f"  Components scanned : {result['symbols_scanned']}")
    print(f"  Power nets found   : {result['power_nets']}")
    print(f"  Net labels found   : {result['net_labels']}")
    print(f"  Wire segments      : {result['wire_count']}")
    print(f"  Paren balance      : {result['paren_balance']} (0 = OK)")
    print()

    if result["errors"]:
        print(f"ERRORS ({len(result['errors'])}):")
        for e in result["errors"]:
            print(f"  ✗ {e}")
        print()
    else:
        print("  No errors.")

    if result["warnings"]:
        print(f"WARNINGS ({len(result['warnings'])}):")
        for w in result["warnings"]:
            print(f"  ⚠ {w}")
        print()

    total_issues = len(result["errors"])
    if strict:
        total_issues += len(result["warnings"])

    if result["passed"] and total_issues == 0:
        print("RESULT: PASS — ready for ERC")
    else:
        print(
            f"RESULT: FAIL — {total_issues} issue(s) must be resolved before running ERC"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pre-ERC preflight check for KiCad schematics.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Checks performed:
  1. Parenthesis balance (malformed file detection)
  2. Duplicate reference designators (error)
  3. Components with no footprint assignment (error)
  4. Power nets that appear only once (warning)
  5. Net labels that appear only once / dangling (warning)
  6. Wire count vs component count sanity (warning)

Exit code 0 = PASS, exit code 1 = FAIL.

Always run with /usr/bin/python3:
  /usr/bin/python3 schematic_preflight.py board.kicad_sch
  /usr/bin/python3 schematic_preflight.py board.kicad_sch --strict
  /usr/bin/python3 schematic_preflight.py board.kicad_sch --json
""",
    )
    parser.add_argument(
        "schematic",
        help="Path to the .kicad_sch file to check",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (non-zero exit if any warnings)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Print results as JSON instead of human-readable text",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only the summary line (PASS/FAIL + counts), no details",
    )
    args = parser.parse_args()

    result = preflight(args.schematic, strict=args.strict)

    if args.json_output:
        print(json.dumps(result, indent=2))
    elif args.summary:
        status = "PASS" if result["passed"] else "FAIL"
        print(
            f"{status} | components={result['symbols_scanned']} "
            f"power_nets={result['power_nets']} "
            f"labels={result['net_labels']} "
            f"wires={result['wire_count']} "
            f"errors={len(result['errors'])} "
            f"warnings={len(result['warnings'])}"
        )
    else:
        _print_report(result, strict=args.strict)

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()


def normalize_mcp_symbols(sch_path: Path, project_name: str = "") -> int:
    """
    Convert MCP-placed symbols from KiCad 6 to KiCad 9 format.
    Fixes that enable kicad-cli netlist export on mixed-format schematics:
      1. Remove (id N) from property definitions
      2. Add (dnp no) where missing
      3. Add (instances) blocks to symbols that lack them
    Returns number of fixes applied.
    Call this before running kicad-cli sch export netlist.
    """
    import re, uuid
    text = sch_path.read_text(encoding="utf-8")
    if not project_name:
        project_name = sch_path.stem
    fixes = 0

    # Fix 1: Remove (id N) property fields (KiCad 6 format not read by kicad-cli 9)
    count_before = len(re.findall(r'\(id \d+\)', text))
    text = re.sub(r'\s*\(id \d+\)', '', text)
    fixes += count_before

    # Fix 2: Add (dnp no) where (in_bom yes) (on_board yes) appears without it
    old_flag = '(in_bom yes) (on_board yes)'
    new_flag = '(in_bom yes) (on_board yes) (dnp no)'
    if old_flag in text and new_flag not in text:
        text = text.replace(old_flag, new_flag)
        fixes += text.count(new_flag)

    # Fix 3: Add (instances) blocks to MCP symbols missing them
    pattern = re.compile(r'\(symbol \(lib_id "(?!power:)[^"]+"')
    for m in pattern.finditer(text):
        start = m.start()
        depth, end = 0, start
        for i, ch in enumerate(text[start:], start):
            if ch == '(': depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        block = text[start:end]
        if '(instances' in block:
            continue
        ref_m = re.search(r'"Reference" "([^"]+)"', block)
        if not ref_m or ref_m.group(1).startswith('#'):
            continue
        ref = ref_m.group(1)
        inst = (
            f'    (instances\n'
            f'      (project "{project_name}"\n'
            f'        (path "/"\n'
            f'          (reference "{ref}")\n'
            f'          (unit 1)\n'
            f'        )\n'
            f'      )\n'
            f'    )'
        )
        text = text[:end-1] + '\n' + inst + text[end-1:]
        fixes += 1
        # Restart after modification
        pattern = re.compile(r'\(symbol \(lib_id "(?!power:)[^"]+"')
        break

    sch_path.write_text(text, encoding="utf-8")
    return fixes
