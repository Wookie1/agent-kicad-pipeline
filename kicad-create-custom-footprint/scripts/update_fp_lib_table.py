#!/usr/bin/env python3
"""
update_fp_lib_table.py — Register a .pretty footprint library in a KiCad project.

Reads (or creates) the project's fp-lib-table file and adds the given library
if it is not already present.  Safe to run multiple times — duplicate entries
are silently skipped.

Usage:
    python3 update_fp_lib_table.py \\
        --project /path/to/board.kicad_pro \\
        --lib-name "my_custom_footprints" \\
        --lib-path /path/to/my_custom_footprints.pretty

    # Optional description:
    python3 update_fp_lib_table.py \\
        --project /path/to/board.kicad_pro \\
        --lib-name "my_custom_footprints" \\
        --lib-path /path/to/my_custom_footprints.pretty \\
        --descr "Custom packages for motor controller"
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LIB_RE = re.compile(
    r'\(lib\s+\(name\s+"([^"]+)"\)',
    re.IGNORECASE,
)

_EMPTY_TABLE = "(fp_lib_table\n  (version 1)\n)\n"


def _registered_names(text: str) -> set[str]:
    """Return the set of library names already in the table."""
    return {m.group(1) for m in _LIB_RE.finditer(text)}


def _make_entry(name: str, uri: str, descr: str) -> str:
    return f'  (lib (name "{name}")(type "KiCad")(uri "{uri}")(options "")(descr "{descr}"))'


def _insert_before_last_paren(text: str, entry: str) -> str:
    """Insert *entry* on a new line before the final closing parenthesis."""
    stripped = text.rstrip()
    if stripped.endswith(")"):
        return stripped[:-1].rstrip() + "\n" + entry + "\n)\n"
    # Malformed table — append as best-effort
    return text + entry + "\n"


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def update_fp_lib_table(
    project_path: str,
    lib_name: str,
    lib_path: str,
    descr: str = "",
) -> str:
    """
    Register *lib_name* / *lib_path* in the project's fp-lib-table.

    Returns the absolute path to the fp-lib-table file.
    Raises FileNotFoundError if *lib_path* does not exist.
    """
    project = Path(project_path).expanduser().resolve()
    if not project.exists():
        raise FileNotFoundError(f"Project file not found: {project}")

    lib_abs = Path(lib_path).expanduser().resolve()
    if not lib_abs.exists():
        raise FileNotFoundError(
            f"Footprint library directory not found: {lib_abs}\n"
            "Run kicad_footprint_builder.py first to generate the .pretty directory."
        )
    if lib_abs.is_file():
        # User passed a .kicad_mod file instead of the .pretty directory
        if lib_abs.parent.suffix == ".pretty":
            lib_abs = lib_abs.parent
            print(f"INFO: Using parent .pretty directory: {lib_abs}")
        else:
            print(
                f"WARNING: '{lib_abs.name}' is a file, not a .pretty directory. "
                "The fp-lib-table entry should point to the enclosing .pretty folder.",
                file=sys.stderr,
            )
    if lib_abs.is_dir() and lib_abs.suffix != ".pretty":
        print(
            f"WARNING: '{lib_abs.name}' does not have a .pretty suffix. "
            "KiCad footprint libraries should be named *.pretty.",
            file=sys.stderr,
        )

    table_path = project.parent / "fp-lib-table"

    if table_path.exists():
        text = table_path.read_text(encoding="utf-8")
    else:
        text = _EMPTY_TABLE
        print(f"fp-lib-table not found — creating: {table_path}")

    existing = _registered_names(text)
    if lib_name in existing:
        print(f"Library '{lib_name}' is already registered in {table_path}")
        return str(table_path)

    entry = _make_entry(lib_name, str(lib_abs), descr)
    text = _insert_before_last_paren(text, entry)
    table_path.write_text(text, encoding="utf-8")

    print(f"Registered '{lib_name}' -> {lib_abs}")
    print(f"fp-lib-table: {table_path}")
    return str(table_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register a .pretty footprint library in the project fp-lib-table.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python3 update_fp_lib_table.py \\
      --project ~/boards/motor_ctrl/motor_ctrl.kicad_pro \\
      --lib-name "motor_ctrl_fp" \\
      --lib-path ~/boards/motor_ctrl/motor_ctrl_fp.pretty \\
      --descr "Custom footprints for motor controller board"
""",
    )
    parser.add_argument(
        "--project", required=True,
        help="Path to the .kicad_pro project file",
    )
    parser.add_argument(
        "--lib-name", required=True,
        help="Library name as it will appear in KiCad (no spaces; case-sensitive)",
    )
    parser.add_argument(
        "--lib-path", required=True,
        help="Absolute or relative path to the .pretty footprint library directory",
    )
    parser.add_argument(
        "--descr", default="",
        help="Optional human-readable description for this library",
    )
    args = parser.parse_args()

    try:
        update_fp_lib_table(
            project_path=args.project,
            lib_name=args.lib_name,
            lib_path=args.lib_path,
            descr=args.descr,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
