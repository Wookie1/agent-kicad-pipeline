#!/usr/bin/env python3
"""
pcb_pipeline_mcp.py  v1.0.0

FastMCP server providing 8 high-level KiCad PCB design tools for Agent Zero.

Tools
-----
pcb_init        Create project scaffold (dirs, .kicad_pro, empty files)
pcb_schematic   High-level schematic: components[] + nets[] → .kicad_sch + .net
pcb_search_lib  Search KiCad symbol / footprint libraries
pcb_layout      Import netlist → PCB, run connectivity-aware placement
pcb_route       Auto-route via Freerouter JAR
pcb_drc         Run DRC, return structured violation list
pcb_export      Export Gerbers, drill, BOM, pick-and-place, PDF
pcb_status      Return current project phase, file list, basic stats

Environment variables (set in docker run -e and settings.json mcp_servers env):
  KICAD_CLI_PATH    Path to kicad-cli or kicad-cli-xvfb wrapper
                    Default: /usr/local/bin/kicad-cli-xvfb
  KICAD_SYMBOL_LIBS Directory containing symbol .kicad_sym libraries
                    Default: /kicad-support/symbols
  KICAD_FOOTPRINT_LIBS Directory containing .pretty footprint dirs
                    Default: /kicad-support/footprints
  FREEROUTING_JAR   Path to freerouting.jar
                    Default: /a0/usr/freerouting/freerouting.jar
  SKILLS_DIR        Root of skills directory inside Docker
                    Default: /a0/usr/skills
  SNAPEDA_API_KEY   SnapEDA API token for pcb_search_web (get from snapeda.com → Account → API)
                    Default: "" (pcb_search_web returns error if not set)

Run:
  /a0/usr/skills-venv/bin/python3 /a0/usr/tools/pcb-pipeline/pcb_pipeline_mcp.py
"""

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# ── Environment ───────────────────────────────────────────────────────────────

KICAD_CLI        = os.environ.get("KICAD_CLI_PATH", "/usr/local/bin/kicad-cli-xvfb")
SYMBOL_LIBS_DIR  = Path(os.environ.get("KICAD_SYMBOL_LIBS", "/kicad-support/symbols"))
FP_LIBS_DIR      = Path(os.environ.get("KICAD_FOOTPRINT_LIBS", "/kicad-support/footprints"))
FREEROUTING_JAR  = os.environ.get("FREEROUTING_JAR",
                                   "/a0/usr/freerouting/freerouting.jar")
SKILLS_DIR       = Path(os.environ.get("SKILLS_DIR", "/a0/usr/skills"))
SNAPEDA_API_KEY  = os.environ.get("SNAPEDA_API_KEY", "")
SNAPEDA_BASE     = "https://www.snapeda.com/api/v1"
TOOLS_DIR        = Path(__file__).parent  # same dir as this script when deployed
DISPLAY_ENV      = {"DISPLAY": ":99"}
STATE_FILE       = ".pcb_pipeline_state.json"

# ── Paths to helper scripts ───────────────────────────────────────────────────

def _script(name: str) -> Path:
    """Locate a helper script; try tools dir, then skills dir."""
    local = TOOLS_DIR / name
    if local.exists():
        return local
    # Find in skills tree
    for p in SKILLS_DIR.rglob(name):
        return p
    return local  # may not exist; caller checks


BATCH_SCH    = _script("batch_schematic.py")
SCH_TO_PCB   = _script("sch_to_pcb_sync.py")
FREEROUTER_PY = _script("kicad_freerouter.py")
PREFLIGHT_PY  = _script("schematic_preflight.py")

SKILLS_VENV_PY = "/a0/usr/skills-venv/bin/python3"
SYS_PY         = "/usr/bin/python3"

mcp = FastMCP("pcb-pipeline")


# ── Subprocess helper ─────────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 120,
         needs_display: bool = False) -> tuple[int, str]:
    """
    Run a subprocess; return (returncode, combined stdout+stderr).
    """
    env = {**os.environ}
    if needs_display:
        env.update(DISPLAY_ENV)
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env
        )
        out = (r.stdout + r.stderr).strip()
        return r.returncode, out
    except subprocess.TimeoutExpired:
        return -1, f"Timed out after {timeout}s"
    except Exception as exc:
        return -2, str(exc)


# ── State persistence ─────────────────────────────────────────────────────────

def _read_state(project_dir: Path) -> dict:
    p = project_dir / STATE_FILE
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception:
            pass
    return {}


def _write_state(project_dir: Path, updates: dict):
    state = _read_state(project_dir)
    state.update(updates)
    (project_dir / STATE_FILE).write_text(json.dumps(state, indent=2), "utf-8")


# ── Tool: pcb_init ────────────────────────────────────────────────────────────

@mcp.tool()
def pcb_init(
    project_name: str,
    output_dir: str = "/workspace/pcb",
    board_width_mm: float = 80.0,
    board_height_mm: float = 60.0,
    fab: str = "jlcpcb",
) -> dict:
    """
    Create a KiCad project scaffold.

    Args:
      project_name   : Short name, e.g. "led_driver" (no spaces)
      output_dir     : Parent directory on the Docker filesystem
      board_width_mm : PCB width in mm
      board_height_mm: PCB height in mm
      fab            : Target fab ("jlcpcb" | "pcbway" | "generic")

    Returns:
      {"project_dir": str, "files": [str], "ok": bool}
    """
    project_dir = Path(output_dir) / project_name
    project_dir.mkdir(parents=True, exist_ok=True)

    # .kicad_pro
    pro = {
        "meta": {"filename": f"{project_name}.kicad_pro", "version": 1},
        "board": {"design_settings": {}},
        "libraries": {},
        "net_settings": {},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [],
    }
    (project_dir / f"{project_name}.kicad_pro").write_text(
        json.dumps(pro, indent=2), "utf-8"
    )

    # Empty schematic placeholder
    sch_placeholder = (
        f'(kicad_sch\n'
        f'  (version 20231120)\n'
        f'  (generator "pcb-pipeline")\n'
        f'  (generator_version "1.0")\n'
        f'  (paper "A4")\n'
        f'  (title_block (title "{project_name}") (rev "v1.0"))\n'
        f'  (lib_symbols)\n'
        f'  (sheet_instances (path "/" (page "1")))\n'
        f')\n'
    )
    (project_dir / f"{project_name}.kicad_sch").write_text(sch_placeholder, "utf-8")

    files = [str(p.relative_to(project_dir)) for p in project_dir.iterdir()]

    _write_state(project_dir, {
        "phase": "init",
        "project_name": project_name,
        "board_width_mm": board_width_mm,
        "board_height_mm": board_height_mm,
        "fab": fab,
    })

    return {
        "project_dir": str(project_dir),
        "files": sorted(files),
        "ok": True,
    }


# ── Tool: pcb_schematic ───────────────────────────────────────────────────────

@mcp.tool()
def pcb_schematic(
    project_dir: str,
    components: list[dict],
    nets: list[dict],
) -> dict:
    """
    Generate a KiCad schematic and netlist from high-level component+net data.
    No coordinates needed — auto-layout is applied.

    Args:
      project_dir: Path to KiCad project directory
      components : List of component dicts:
                   [{"ref":"U1","lib_id":"Timer:NE555","value":"NE555",
                     "footprint":"Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"}, ...]
                   lib_id format: "LibName:SymbolName"
                   footprint format: "LibName:FootprintName"
      nets       : List of net dicts:
                   [{"name":"VCC","pins":[["U1","8"],["C1","1"]]}, ...]
                   Power net names (VCC/GND/+5V/GND etc.) get power symbols.
                   All others get net labels.

    Returns:
      {"schematic_path": str, "net_path": str, "config_path": str,
       "preflight": str, "warnings": [str], "ok": bool}
    """
    # Import here so the MCP server doesn't need it at startup
    # (schematic_builder.py is in the same directory)
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        import schematic_builder
    except ImportError as exc:
        return {"ok": False, "warnings": [f"Cannot import schematic_builder: {exc}"],
                "schematic_path": "", "net_path": "", "config_path": "", "preflight": ""}

    result = schematic_builder.build(
        components  = components,
        nets        = nets,
        project_dir = project_dir,
        batch_script = str(BATCH_SCH) if BATCH_SCH.exists() else None,
        python_exe   = SKILLS_VENV_PY,
    )

    _write_state(Path(project_dir), {
        "phase": "schematic",
        "components": len(components),
        "nets": len(nets),
    })

    return result


# ── Tool: pcb_search_lib ──────────────────────────────────────────────────────

@mcp.tool()
def pcb_search_lib(
    query: str,
    search_type: str = "symbol",
    max_results: int = 12,
) -> dict:
    """
    Search KiCad symbol or footprint libraries.

    Args:
      query       : Part name, value, or keyword (e.g. "NE555", "0402", "SOIC-8")
      search_type : "symbol" or "footprint"
      max_results : Maximum number of results to return

    Returns:
      {"results": [{"lib_id": str, "description": str}], "count": int, "ok": bool}
    """
    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    if search_type == "symbol":
        lib_dir = SYMBOL_LIBS_DIR
        ext     = ".kicad_sym"
    else:
        lib_dir = FP_LIBS_DIR
        ext     = ".kicad_mod"

    if not lib_dir.exists():
        return {"results": [], "count": 0, "ok": False,
                "error": f"Library directory not found: {lib_dir}"}

    for lib_file in sorted(lib_dir.rglob(f"*{ext}")):
        if len(results) >= max_results:
            break
        lib_name = lib_file.parent.stem if search_type == "footprint" else lib_file.stem

        if search_type == "footprint":
            sym_name = lib_file.stem
            if pattern.search(sym_name) or pattern.search(lib_name):
                results.append({
                    "lib_id":      f"{lib_name}:{sym_name}",
                    "description": "",
                })
        else:
            try:
                content = lib_file.read_text("utf-8", errors="ignore")
                for m in re.finditer(
                    r'\(symbol\s+"([^"]+)"', content
                ):
                    sym_name = m.group(1)
                    if ":" in sym_name:
                        continue  # nested sub-symbol
                    if pattern.search(sym_name) or pattern.search(lib_name):
                        # Try to extract description
                        desc_m = re.search(
                            rf'\(symbol\s+"{re.escape(sym_name)}".*?'
                            r'\(property\s+"Description"\s+"([^"]*)"',
                            content, re.DOTALL
                        )
                        desc = desc_m.group(1) if desc_m else ""
                        results.append({
                            "lib_id":      f"{lib_name}:{sym_name}",
                            "description": desc,
                        })
                    if len(results) >= max_results:
                        break
            except Exception:
                continue

    return {"results": results, "count": len(results), "ok": True}


# ── Tool: pcb_layout ─────────────────────────────────────────────────────────

@mcp.tool()
def pcb_layout(
    project_dir: str,
    hints: dict | None = None,
) -> dict:
    """
    Import netlist into a KiCad PCB file and run connectivity-aware placement.

    Args:
      project_dir: Path to KiCad project directory (must contain .net and .kicad_sch)
      hints      : Optional {ref: {x: float, y: float}} manual placement overrides
                   Example: {"J1": {"x": 5.0, "y": 30.0}}

    Returns:
      {"pcb_path": str, "placed": int, "drc_violations": int,
       "warnings": [str], "ok": bool}
    """
    project_dir = Path(project_dir)
    state       = _read_state(project_dir)
    project_name = project_dir.name
    hints       = hints or {}

    net_path = project_dir / f"{project_name}.net"
    pcb_path = project_dir / f"{project_name}.kicad_pcb"
    sch_path = project_dir / f"{project_name}.kicad_sch"
    warnings = []

    board_w = state.get("board_width_mm",  80.0)
    board_h = state.get("board_height_mm", 60.0)

    # ── Step 1: Sync schematic → PCB (creates footprints, zones) ─────────────
    if SCH_TO_PCB.exists():
        sync_cmd = [SYS_PY, str(SCH_TO_PCB), str(sch_path), str(pcb_path),
                    "--width", str(board_w), "--height", str(board_h)]
        rc, out = _run(sync_cmd, timeout=90, needs_display=True)
        if rc != 0:
            warnings.append(f"sch_to_pcb_sync.py warning (rc={rc}): {out[:300]}")
        # Even partial output may have created the file
    elif not pcb_path.exists():
        warnings.append(f"sch_to_pcb_sync.py not found at {SCH_TO_PCB}; "
                        "PCB file must already exist")
        return {"pcb_path": str(pcb_path), "placed": 0,
                "drc_violations": -1, "warnings": warnings, "ok": False}

    # ── Step 2: Place footprints ──────────────────────────────────────────────
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        import pcb_placer
    except ImportError as exc:
        return {"pcb_path": str(pcb_path), "placed": 0,
                "drc_violations": -1,
                "warnings": [f"Cannot import pcb_placer: {exc}"],
                "ok": False}

    place_result = pcb_placer.place(
        net_path  = net_path if net_path.exists() else "",
        pcb_path  = pcb_path,
        board_w   = board_w,
        board_h   = board_h,
        hints     = hints,
    )
    warnings.extend(place_result.get("warnings", []))
    placed = place_result.get("placed", 0)

    # ── Step 3: Quick DRC unconnected check ───────────────────────────────────
    drc_violations = -1
    if pcb_path.exists():
        drc_out_dir = project_dir / "drc_out"
        drc_out_dir.mkdir(exist_ok=True)
        drc_cmd = [
            KICAD_CLI, "pcb", "drc",
            "--output", str(drc_out_dir / "drc_report.json"),
            "--format", "json",
            "--schematic-parity",
            str(pcb_path),
        ]
        rc, drc_out = _run(drc_cmd, timeout=120, needs_display=True)
        drc_json = drc_out_dir / "drc_report.json"
        if drc_json.exists():
            try:
                drc_data = json.loads(drc_json.read_text("utf-8"))
                drc_violations = len(drc_data.get("violations", []))
            except Exception:
                pass

    _write_state(project_dir, {
        "phase": "layout",
        "placed": placed,
        "drc_violations_post_layout": drc_violations,
    })

    return {
        "pcb_path":       str(pcb_path),
        "placed":         placed,
        "drc_violations": drc_violations,
        "warnings":       warnings,
        "ok":             place_result.get("ok", False),
    }


# ── Tool: pcb_route ──────────────────────────────────────────────────────────

@mcp.tool()
def pcb_route(
    project_dir: str,
) -> dict:
    """
    Auto-route the PCB using Freerouter.

    Requires:
      - Placed .kicad_pcb in project_dir
      - freerouting.jar at FREEROUTING_JAR
      - Java (default-jre-headless)

    Returns:
      {"pcb_path": str, "routed": int, "total_nets": int,
       "completion_pct": float, "warnings": [str], "ok": bool}
    """
    project_dir  = Path(project_dir)
    project_name = project_dir.name
    pcb_path     = project_dir / f"{project_name}.kicad_pcb"
    warnings     = []

    if not pcb_path.exists():
        return {"pcb_path": str(pcb_path), "routed": 0, "total_nets": 0,
                "completion_pct": 0.0, "warnings": ["PCB file not found"], "ok": False}

    if not FREEROUTER_PY.exists():
        return {"pcb_path": str(pcb_path), "routed": 0, "total_nets": 0,
                "completion_pct": 0.0,
                "warnings": [f"kicad_freerouter.py not found at {FREEROUTER_PY}"],
                "ok": False}

    if not Path(FREEROUTING_JAR).exists():
        return {"pcb_path": str(pcb_path), "routed": 0, "total_nets": 0,
                "completion_pct": 0.0,
                "warnings": [f"freerouting.jar not found at {FREEROUTING_JAR}"],
                "ok": False}

    route_cmd = [
        SYS_PY, str(FREEROUTER_PY),
        str(pcb_path),
        "--jar", FREEROUTING_JAR,
    ]
    rc, out = _run(route_cmd, timeout=300, needs_display=True)

    # Parse completion stats from freerouter output
    routed    = 0
    total     = 0
    for line in out.splitlines():
        m = re.search(r'(\d+)\s*/\s*(\d+)\s*(?:nets?|connections?)\s*routed', line, re.I)
        if m:
            routed = int(m.group(1))
            total  = int(m.group(2))
            break
    # Fallback: look for "Completed: X%"
    if total == 0:
        m = re.search(r'completed[:\s]+(\d+(?:\.\d+)?)\s*%', out, re.I)
        if m:
            completion_pct = float(m.group(1))
        else:
            completion_pct = 100.0 if rc == 0 else 0.0
    else:
        completion_pct = round(100.0 * routed / total, 1) if total > 0 else 0.0

    if rc != 0:
        warnings.append(f"Freerouter exited {rc}: {out[-300:]}")

    _write_state(project_dir, {
        "phase": "routed",
        "routing_completion_pct": completion_pct,
    })

    return {
        "pcb_path":        str(pcb_path),
        "routed":          routed,
        "total_nets":      total,
        "completion_pct":  completion_pct,
        "freerouter_log":  out[-800:],
        "warnings":        warnings,
        "ok":              rc == 0,
    }


# ── Tool: pcb_drc ─────────────────────────────────────────────────────────────

@mcp.tool()
def pcb_drc(
    project_dir: str,
) -> dict:
    """
    Run KiCad DRC and return a structured violation list.

    Returns:
      {"violations": [{"type": str, "severity": str, "description": str,
                       "location": str}],
       "error_count": int, "warning_count": int,
       "unconnected_count": int, "ok": bool}
    """
    project_dir  = Path(project_dir)
    project_name = project_dir.name
    pcb_path     = project_dir / f"{project_name}.kicad_pcb"

    if not pcb_path.exists():
        return {"violations": [], "error_count": 0, "warning_count": 0,
                "unconnected_count": 0, "ok": False,
                "error": "PCB file not found"}

    drc_out_dir = project_dir / "drc_out"
    drc_out_dir.mkdir(exist_ok=True)
    report_path = drc_out_dir / "drc_report.json"

    cmd = [
        KICAD_CLI, "pcb", "drc",
        "--output",            str(report_path),
        "--format",            "json",
        "--schematic-parity",
        str(pcb_path),
    ]
    rc, out = _run(cmd, timeout=120, needs_display=True)

    violations   = []
    errors       = 0
    warnings_cnt = 0
    unconnected  = 0

    if report_path.exists():
        try:
            data = json.loads(report_path.read_text("utf-8"))
            for v in data.get("violations", []):
                severity = v.get("severity", "error").lower()
                vtype    = v.get("type", "")
                desc     = v.get("description", "")
                loc_items = v.get("items", [])
                loc = ""
                if loc_items:
                    p = loc_items[0].get("pos", {})
                    loc = f"({p.get('x',0):.2f},{p.get('y',0):.2f})"

                violations.append({
                    "type":        vtype,
                    "severity":    severity,
                    "description": desc,
                    "location":    loc,
                })
                if "unconnected" in vtype.lower() or "unconnected" in desc.lower():
                    unconnected += 1
                elif severity == "error":
                    errors += 1
                else:
                    warnings_cnt += 1
        except Exception as exc:
            violations.append({"type": "parse_error", "severity": "error",
                                "description": str(exc), "location": ""})

    _write_state(project_dir, {
        "phase": "drc",
        "drc_errors":       errors,
        "drc_warnings":     warnings_cnt,
        "drc_unconnected":  unconnected,
    })

    return {
        "violations":       violations,
        "error_count":      errors,
        "warning_count":    warnings_cnt,
        "unconnected_count": unconnected,
        "drc_stdout":       out[-500:],
        "ok":               errors == 0 and unconnected == 0,
    }


# ── Tool: pcb_export ─────────────────────────────────────────────────────────

@mcp.tool()
def pcb_export(
    project_dir: str,
    fab: str = "",
    include: list[str] | None = None,
) -> dict:
    """
    Export manufacturing files.

    Args:
      project_dir: KiCad project directory
      fab        : "jlcpcb" | "pcbway" | "generic" (overrides state if set)
      include    : Subset of ["gerbers","drill","bom","cpl","pdf","step"]
                   Defaults to all.

    Returns:
      {"files": [str], "warnings": [str], "ok": bool}
    """
    project_dir  = Path(project_dir)
    project_name = project_dir.name
    pcb_path     = project_dir / f"{project_name}.kicad_pcb"
    sch_path     = project_dir / f"{project_name}.kicad_sch"
    state        = _read_state(project_dir)

    if not fab:
        fab = state.get("fab", "generic")
    include = set(include) if include else {"gerbers","drill","bom","cpl","pdf","step"}

    out_dir = project_dir / "fab"
    out_dir.mkdir(exist_ok=True)

    exported = []
    warnings = []

    # ── Gerbers ───────────────────────────────────────────────────────────────
    if "gerbers" in include and pcb_path.exists():
        gerber_dir = out_dir / "gerbers"
        gerber_dir.mkdir(exist_ok=True)
        cmd = [
            KICAD_CLI, "pcb", "export", "gerbers",
            "--output", str(gerber_dir),
            str(pcb_path),
        ]
        rc, out_txt = _run(cmd, timeout=60, needs_display=True)
        if rc == 0:
            exported.extend(str(p.relative_to(project_dir))
                            for p in gerber_dir.glob("*"))
        else:
            warnings.append(f"Gerber export failed (rc={rc}): {out_txt[:200]}")

    # ── Drill ─────────────────────────────────────────────────────────────────
    if "drill" in include and pcb_path.exists():
        drill_dir = out_dir / "gerbers"
        drill_dir.mkdir(exist_ok=True)
        cmd = [
            KICAD_CLI, "pcb", "export", "drill",
            "--output", str(drill_dir) + "/",
            "--format", "excellon",
            str(pcb_path),
        ]
        rc, out_txt = _run(cmd, timeout=60, needs_display=True)
        if rc == 0:
            exported.extend(str(p.relative_to(project_dir))
                            for p in drill_dir.glob("*.drl"))
        else:
            warnings.append(f"Drill export failed (rc={rc}): {out_txt[:200]}")

    # ── PDF (schematic) ───────────────────────────────────────────────────────
    if "pdf" in include and sch_path.exists():
        sch_pdf = out_dir / f"{project_name}_schematic.pdf"
        cmd = [
            KICAD_CLI, "sch", "export", "pdf",
            "--output", str(sch_pdf),
            str(sch_path),
        ]
        rc, out_txt = _run(cmd, timeout=60, needs_display=True)
        if rc == 0 and sch_pdf.exists():
            exported.append(str(sch_pdf.relative_to(project_dir)))
        else:
            warnings.append(f"Schematic PDF export failed (rc={rc}): {out_txt[:200]}")

    # ── PCB PDF ───────────────────────────────────────────────────────────────
    if "pdf" in include and pcb_path.exists():
        pcb_pdf = out_dir / f"{project_name}_pcb.pdf"
        cmd = [
            KICAD_CLI, "pcb", "export", "pdf",
            "--output", str(pcb_pdf),
            str(pcb_path),
        ]
        rc, out_txt = _run(cmd, timeout=60, needs_display=True)
        if rc == 0 and pcb_pdf.exists():
            exported.append(str(pcb_pdf.relative_to(project_dir)))
        else:
            warnings.append(f"PCB PDF export failed (rc={rc}): {out_txt[:200]}")

    # ── BOM (Python fallback — export_bom_csv MCP tool is broken) ─────────────
    if "bom" in include and pcb_path.exists():
        bom_py = _script("generate_bom.py")
        if bom_py.exists():
            bom_out = out_dir / f"{project_name}_bom.csv"
            cmd = [SYS_PY, str(bom_py), str(pcb_path), "--output", str(bom_out)]
            rc, out_txt = _run(cmd, timeout=30)
            if rc == 0 and bom_out.exists():
                exported.append(str(bom_out.relative_to(project_dir)))
            else:
                warnings.append(f"BOM generation failed (rc={rc}): {out_txt[:200]}")
        else:
            # Simple fallback: extract refs+values from PCB text
            _generate_simple_bom(pcb_path, out_dir / f"{project_name}_bom.csv")
            bom_out = out_dir / f"{project_name}_bom.csv"
            if bom_out.exists():
                exported.append(str(bom_out.relative_to(project_dir)))

    # ── Pick-and-place / CPL ──────────────────────────────────────────────────
    if "cpl" in include and pcb_path.exists():
        cpl_out = out_dir / f"{project_name}_cpl.csv"
        cmd = [
            KICAD_CLI, "pcb", "export", "pos",
            "--output",    str(cpl_out),
            "--format",    "csv",
            "--units",     "mm",
            "--side",      "front",
            str(pcb_path),
        ]
        rc, out_txt = _run(cmd, timeout=30, needs_display=True)
        if rc == 0 and cpl_out.exists():
            exported.append(str(cpl_out.relative_to(project_dir)))
            if fab == "jlcpcb":
                _reformat_jlcpcb_cpl(cpl_out)
        else:
            warnings.append(f"CPL export failed (rc={rc}): {out_txt[:200]}")

    # ── STEP 3D ───────────────────────────────────────────────────────────────
    if "step" in include and pcb_path.exists():
        step_out = out_dir / f"{project_name}.step"
        cmd = [
            KICAD_CLI, "pcb", "export", "step",
            "--output", str(step_out),
            "--no-dnp",
            str(pcb_path),
        ]
        rc, out_txt = _run(cmd, timeout=120, needs_display=True)
        if rc == 0 and step_out.exists():
            exported.append(str(step_out.relative_to(project_dir)))
        else:
            warnings.append(f"STEP export failed (rc={rc}): {out_txt[:200]}")

    _write_state(project_dir, {
        "phase": "exported",
        "exported_files": exported,
    })

    return {
        "files":    exported,
        "fab":      fab,
        "warnings": warnings,
        "ok":       len(exported) > 0,
    }


def _generate_simple_bom(pcb_path: Path, out_path: Path):
    """Minimal BOM extraction from PCB text when generate_bom.py is unavailable."""
    try:
        text  = pcb_path.read_text("utf-8")
        refs  = re.findall(r'\(property\s+"Reference"\s+"([^"]+)"', text)
        vals  = re.findall(r'\(property\s+"Value"\s+"([^"]+)"', text)
        fps   = re.findall(r'\(property\s+"Footprint"\s+"([^"]+)"', text)

        rows = ["Ref,Value,Footprint"]
        for r, v, f in zip(refs, vals, fps):
            if not r.startswith("#"):
                rows.append(f'"{r}","{v}","{f}"')
        out_path.write_text("\n".join(rows) + "\n", "utf-8")
    except Exception:
        pass


def _reformat_jlcpcb_cpl(cpl_path: Path):
    """Rename columns to JLCPCB expected format."""
    try:
        text = cpl_path.read_text("utf-8")
        text = text.replace("Ref,", "Designator,")
        text = text.replace(",PosX,", ",Mid X,")
        text = text.replace(",PosY,", ",Mid Y,")
        text = text.replace(",Rot,", ",Rotation,")
        text = text.replace(",Side,", ",Layer,")
        cpl_path.write_text(text, "utf-8")
    except Exception:
        pass


# ── Helper: footprint metadata parser ────────────────────────────────────────

def _parse_footprint_metadata(fp_path: str) -> dict:
    """Parse pad count, minimum pitch, and courtyard dims from a .kicad_mod file."""
    try:
        text = Path(fp_path).read_text("utf-8")

        # Pad count (unique pad numbers)
        pads = re.findall(r'\(pad\s+"?(\d+)"?\s+', text)
        pad_count = len(set(pads))

        # Pad XY positions → estimate minimum pitch
        pad_xy = re.findall(
            r'\(pad\s+\S+\s+\S+\s+\S+\s+\(at\s+([-\d.]+)\s+([-\d.]+)', text)
        pitch = None
        if len(pad_xy) >= 2:
            xs = sorted(set(float(x) for x, _ in pad_xy))
            ys = sorted(set(float(y) for _, y in pad_xy))
            gaps = (
                [round(xs[i+1] - xs[i], 4) for i in range(len(xs)-1)] +
                [round(ys[i+1] - ys[i], 4) for i in range(len(ys)-1)]
            )
            valid = [g for g in gaps if g > 0.05]
            pitch = min(valid) if valid else None

        # Courtyard bounding box
        crtyd = re.search(r'F\.Courtyard(.*?)(?=\n\s*\(gr_|\n\s*\(pad|\Z)',
                          text, re.DOTALL)
        cw = ch = None
        if crtyd:
            xy_vals = re.findall(r'\(xy\s+([-\d.]+)\s+([-\d.]+)\)', crtyd.group(1))
            if xy_vals:
                xs_c = [float(x) for x, _ in xy_vals]
                ys_c = [float(y) for _, y in xy_vals]
                cw = round(max(xs_c) - min(xs_c), 3)
                ch = round(max(ys_c) - min(ys_c), 3)

        return {
            "pad_count":    pad_count,
            "pad_pitch_mm": pitch,
            "courtyard_mm": {"w": cw, "h": ch} if cw and ch else None,
        }
    except Exception:
        return {"pad_count": None, "pad_pitch_mm": None, "courtyard_mm": None}


# ── Tool: pcb_search_web ──────────────────────────────────────────────────────

@mcp.tool()
def pcb_search_web(
    query: str,
    mpn: str = "",
    project_dir: str = "",
    max_results: int = 5,
) -> dict:
    """
    Search SnapEDA for a KiCad symbol and footprint, optionally downloading
    the best match into <project_dir>/lib/<mpn>/.

    Requires SNAPEDA_API_KEY environment variable (get from snapeda.com → Account → API).

    Args:
      query:       Human-readable description, e.g. "TPS62130 buck converter"
      mpn:         Exact manufacturer part number if known (improves match quality)
      project_dir: If provided, download the best match's KiCad files here
      max_results: How many search results to return (default 5)

    Returns:
      {
        "ok": bool,
        "matches": [{"mpn", "manufacturer", "description",
                     "has_symbol", "has_footprint", "datasheet_url", "snap_uid"}],
        "downloaded": {
          "symbol_path":    str | null,   -- absolute path to .kicad_sym
          "footprint_path": str | null,   -- absolute path to .kicad_mod
          "pad_count":      int | null,
          "pad_pitch_mm":   float | null,
          "courtyard_mm":   {"w": float, "h": float} | null,
          "mpn":            str,
          "manufacturer":   str,
          "datasheet_url":  str,
          "source":         "snapeda"
        } | null,
        "error": str | null
      }
    """
    import urllib.request
    import urllib.parse
    import urllib.error
    import zipfile

    if not SNAPEDA_API_KEY:
        return {
            "ok": False, "matches": [], "downloaded": None,
            "error": (
                "SNAPEDA_API_KEY not set. "
                "Add it to the pcb-pipeline env block in Agent Zero settings.json. "
                "Get your key at snapeda.com → Account Settings → API."
            ),
        }

    headers = {
        "Authorization": f"Token {SNAPEDA_API_KEY}",
        "Accept":        "application/json",
    }

    # ── 1. Search ─────────────────────────────────────────────────────────────
    search_term = mpn if mpn else query
    search_url = (
        f"{SNAPEDA_BASE}/parts/search/"
        f"?q={urllib.parse.quote(search_term)}&page_size={max_results}"
    )
    try:
        req = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "matches": [], "downloaded": None,
                "error": f"SnapEDA API error {e.code}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "matches": [], "downloaded": None,
                "error": f"SnapEDA search failed: {e}"}

    matches = []
    for part in data.get("results", []):
        mfr = part.get("manufacturer", "")
        if isinstance(mfr, dict):
            mfr = mfr.get("name", "")
        matches.append({
            "mpn":          part.get("mpn") or part.get("name", ""),
            "manufacturer": mfr,
            "description":  part.get("description", ""),
            "has_symbol":   bool(part.get("has_symbol")),
            "has_footprint": bool(part.get("has_footprint")),
            "datasheet_url": part.get("datasheet", ""),
            "snap_uid":     str(part.get("snap_uid") or part.get("id", "")),
        })

    if not matches:
        return {"ok": True, "matches": [], "downloaded": None,
                "error": "No results found on SnapEDA for this query"}

    # ── 2. Download best match if project_dir given ───────────────────────────
    downloaded = None
    if project_dir:
        best = next(
            (m for m in matches if m["has_symbol"] and m["has_footprint"]), None
        )
        if best and best["snap_uid"]:
            safe_mpn = re.sub(r'[^\w\-]', '_', best["mpn"])
            lib_dir  = Path(project_dir) / "lib" / safe_mpn
            lib_dir.mkdir(parents=True, exist_ok=True)

            dl_url = f"{SNAPEDA_BASE}/parts/{best['snap_uid']}/download/?file_type=kicad"
            try:
                req = urllib.request.Request(dl_url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content = resp.read()

                zip_path = lib_dir / "snapeda.zip"
                zip_path.write_bytes(content)
                with zipfile.ZipFile(zip_path) as z:
                    z.extractall(lib_dir)
                zip_path.unlink(missing_ok=True)

                sym_files = sorted(lib_dir.rglob("*.kicad_sym"))
                fp_files  = sorted(lib_dir.rglob("*.kicad_mod"))
                sym_path  = str(sym_files[0]) if sym_files else None
                fp_path   = str(fp_files[0])  if fp_files  else None

                pad_info = _parse_footprint_metadata(fp_path) if fp_path else {}

                downloaded = {
                    "symbol_path":   sym_path,
                    "footprint_path": fp_path,
                    "mpn":           best["mpn"],
                    "manufacturer":  best["manufacturer"],
                    "datasheet_url": best.get("datasheet_url", ""),
                    "source":        "snapeda",
                    **pad_info,
                }

            except zipfile.BadZipFile:
                # SnapEDA sometimes returns individual files, not a zip
                # Try saving directly as .kicad_sym / .kicad_mod
                content_str = content.decode("utf-8", errors="replace")
                if "(symbol " in content_str:
                    sym_path = str(lib_dir / f"{safe_mpn}.kicad_sym")
                    Path(sym_path).write_text(content_str, "utf-8")
                    downloaded = {
                        "symbol_path": sym_path, "footprint_path": None,
                        "mpn": best["mpn"], "manufacturer": best["manufacturer"],
                        "datasheet_url": best.get("datasheet_url", ""),
                        "source": "snapeda",
                        "pad_count": None, "pad_pitch_mm": None, "courtyard_mm": None,
                    }
                else:
                    downloaded = {
                        "error": "SnapEDA returned an unrecognised file format",
                        "source": "snapeda",
                    }
            except Exception as e:
                downloaded = {"error": f"Download failed: {e}", "source": "snapeda"}

    return {"ok": True, "matches": matches, "downloaded": downloaded, "error": None}


# ── Tool: pcb_status ─────────────────────────────────────────────────────────

@mcp.tool()
def pcb_status(
    project_dir: str,
) -> dict:
    """
    Return current project status: phase, file list, and basic stats.

    Returns:
      {"phase": str, "files": [str], "state": dict, "ok": bool}
    """
    project_dir = Path(project_dir)
    if not project_dir.exists():
        return {"phase": "not_found", "files": [], "state": {}, "ok": False}

    state = _read_state(project_dir)
    files = sorted(str(p.relative_to(project_dir))
                   for p in project_dir.rglob("*")
                   if p.is_file() and p.name != STATE_FILE)

    return {
        "phase":        state.get("phase", "unknown"),
        "project_name": project_dir.name,
        "project_dir":  str(project_dir),
        "files":        files,
        "state":        state,
        "ok":           True,
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
