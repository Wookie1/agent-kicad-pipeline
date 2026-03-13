#!/usr/bin/env python3
"""
create_fab_zip.py  --  package all manufacturing outputs into a fab-ready ZIP.
Usage: python3 create_fab_zip.py <project_dir> [output_zip]
"""
import sys, zipfile
from pathlib import Path
from datetime import datetime


def create_fab_zip(project_dir: str, output_zip: str = None) -> str:
    proj = Path(project_dir)
    if not proj.exists():
        print("ERROR: project_dir not found: " + str(project_dir), file=sys.stderr)
        sys.exit(1)

    pro_files = list(proj.glob("*.kicad_pro"))
    if not pro_files:
        print("ERROR: No .kicad_pro file found in " + str(project_dir), file=sys.stderr)
        sys.exit(1)
    project_name = pro_files[0].stem

    if not output_zip:
        date_str = datetime.now().strftime("%Y%m%d")
        output_zip = str(proj / (project_name + "_fab_" + date_str + ".zip"))

    files_to_include = []

    # Gerbers (required)
    gerber_dir = proj / "gerbers"
    if gerber_dir.exists():
        for f in gerber_dir.iterdir():
            if f.is_file() and f.stat().st_size > 0:
                files_to_include.append((f, "gerbers/" + f.name))

    # BOM (skip header-only files <100 bytes)
    bom_dir = proj / "bom"
    if bom_dir.exists():
        for f in bom_dir.iterdir():
            if f.is_file() and f.stat().st_size > 100:
                files_to_include.append((f, "bom/" + f.name))

    # Assembly (pick-and-place + assembly drawing)
    asm_dir = proj / "assembly"
    if asm_dir.exists():
        for f in asm_dir.iterdir():
            if f.is_file() and f.stat().st_size > 0:
                files_to_include.append((f, "assembly/" + f.name))

    # STEP model
    d3_dir = proj / "3d"
    if d3_dir.exists():
        for f in d3_dir.iterdir():
            if f.is_file() and f.suffix.lower() == ".step":
                files_to_include.append((f, "3d/" + f.name))

    # PDFs
    for f in proj.glob("*.pdf"):
        if f.stat().st_size > 0:
            files_to_include.append((f, f.name))

    # IPC-356 netlist
    for f in proj.glob("*.ipc"):
        if f.stat().st_size > 0:
            files_to_include.append((f, f.name))

    if not files_to_include:
        print("WARNING: No files found to include in ZIP", file=sys.stderr)
        sys.exit(1)

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for src_path, arc_name in files_to_include:
            zf.write(src_path, arc_name)
            sz = src_path.stat().st_size
            print("  + " + arc_name + "  (" + str(sz) + " bytes)")

    zip_size = Path(output_zip).stat().st_size
    print("\nFab ZIP: " + output_zip)
    print("Size: " + str(zip_size) + " bytes  |  Files: " + str(len(files_to_include)))
    return output_zip


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: " + sys.argv[0] + " <project_dir> [output_zip.zip]")
        sys.exit(1)
    out = sys.argv[2] if len(sys.argv) > 2 else None
    create_fab_zip(sys.argv[1], out)
