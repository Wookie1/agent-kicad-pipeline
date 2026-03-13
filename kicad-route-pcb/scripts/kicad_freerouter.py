#!/usr/bin/env python3
"""
kicad_freerouter.py
--------------------
Automate the full Freerouting cycle:
  1. Export Specctra DSN from KiCad PCB (via pcbnew Python module)
  2. Run Freerouting JAR headlessly
  3. Import Specctra SES back into KiCad PCB (via pcbnew Python module)
  4. Analyse routing quality
  5. Optionally iterate with changed settings

Dependencies:
  - Java (JRE/JDK 11+) on PATH
  - KiCad installed (provides pcbnew Python module via SWIG bindings)
  - freerouting JAR (detected automatically, or path supplied)

Compatibility:
  - KiCad 7.x, 8.x, 9.x: fully supported
  - KiCad 10.x: will require update — the pcbnew SWIG bindings used for
    DSN/SES export/import are deprecated in KiCad 9.0 and scheduled for
    removal in KiCad 10. The new IPC API does not yet provide Specctra
    DSN equivalents.

Usage (CLI):
    python kicad_freerouter.py board.kicad_pcb [--jar /path/to/freerouting.jar]
                               [--passes 100] [--threads 4] [--output-dir routing/]
                               [--iterate] [--report]

Usage (import):
    from helpers.kicad.kicad_freerouter import route_board, analyse_routing
    result = route_board("board.kicad_pcb", max_passes=100)
"""

import os
import sys
import re
import json
import shutil
import subprocess
import textwrap
import tempfile
import platform
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, List, Dict, Any

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RoutingStats:
    """Parsed routing quality metrics."""
    completion_pct: float = 0.0        # 0–100; 100 = fully routed
    total_connections: int = 0
    routed_connections: int = 0
    unrouted_connections: int = 0
    total_vias: int = 0
    total_segments: int = 0
    total_arc_segments: int = 0
    trace_length_mm: float = 0.0       # approximate total copper length
    layer_usage: Dict[str, int] = field(default_factory=dict)  # layer → segment count
    unrouted_nets: List[str] = field(default_factory=list)
    drc_violations: int = 0
    drc_unconnected: int = 0
    drc_errors: int = 0
    freerouter_log: str = ""
    iteration: int = 1


@dataclass
class RoutingResult:
    success: bool = False
    completed: bool = False            # True only if 100% routed
    pcb_path: str = ""
    dsn_path: str = ""
    ses_path: str = ""
    stats: Optional[RoutingStats] = None
    iterations: List[RoutingStats] = field(default_factory=list)
    report: str = ""
    message: str = ""


# ---------------------------------------------------------------------------
# Java / JAR finder
# ---------------------------------------------------------------------------

JAR_SEARCH_PATHS = [
    # Plugin-installed freerouting
    Path.home() / ".kicad_plugins" / "kicad_freerouting-plugin" / "jar" / "freerouting.jar",
    Path.home() / ".kicad_plugins" / "kicad_freerouting-plugin" / "jar" / "freerouting-EXECUTABLE.jar",
    # macOS application bundle
    Path("/Applications/KiCad/KiCad.app/Contents/PlugIns/freerouting.jar"),
    # KiCad 7/8 scripting plugins
    Path.home() / ".kicad" / "scripting" / "plugins" / "kicad_freerouting-plugin" / "jar" / "freerouting.jar",
    # Windows
    Path(os.environ.get("APPDATA", "")) / "kicad" / "scripting" / "plugins" / "kicad_freerouting-plugin" / "jar" / "freerouting.jar",
    # Common standalone locations
    Path.home() / "freerouting" / "freerouting.jar",
    Path("/opt/freerouting/freerouting.jar"),
]


def find_freerouting_jar(hint: str = None) -> Optional[Path]:
    """Find freerouting JAR. Returns None if not found."""
    if hint and Path(hint).exists():
        return Path(hint)

    # Check env var
    env_jar = os.environ.get("FREEROUTING_JAR")
    if env_jar and Path(env_jar).exists():
        return Path(env_jar)

    # Check well-known paths
    for p in JAR_SEARCH_PATHS:
        if p.exists():
            return p

    # Search PATH
    for name in ("freerouting.jar", "freerouting-EXECUTABLE.jar"):
        result = shutil.which(name)
        if result:
            return Path(result)

    return None


def find_java() -> Optional[str]:
    """Find Java executable."""
    java = shutil.which("java")
    if java:
        return java
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        j = Path(java_home) / "bin" / "java"
        if j.exists():
            return str(j)
    return None


# ---------------------------------------------------------------------------
# KiCad Python interpreter finder
# ---------------------------------------------------------------------------

KICAD_PYTHON_CANDIDATES = [
    # macOS
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3",
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.11/bin/python3",
    "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.12/bin/python3",
    # Linux
    "/usr/lib/kicad/lib/python3/dist-packages",  # check sys.path instead
    # Windows
    r"C:\Program Files\KiCad\8.0\bin\python3.exe",
    r"C:\Program Files\KiCad\7.0\bin\python3.exe",
]


def find_kicad_python() -> Optional[str]:
    """
    Find a Python interpreter that has the 'pcbnew' module.
    Returns the path to the Python executable, or None.
    """
    # Try the current interpreter first
    try:
        import pcbnew  # noqa: F401
        return sys.executable
    except ImportError:
        pass

    # Try candidate paths
    for candidate in KICAD_PYTHON_CANDIDATES:
        if Path(candidate).exists():
            result = subprocess.run(
                [candidate, "-c", "import pcbnew; print('ok')"],
                capture_output=True, text=True, timeout=10
            )
            if "ok" in result.stdout:
                return candidate

    # Fallback: try system python3 with kicad pythonpath
    for pyexec in ("python3", "python"):
        p = shutil.which(pyexec)
        if not p:
            continue
        result = subprocess.run(
            [p, "-c", "import pcbnew; print('ok')"],
            capture_output=True, text=True, timeout=10
        )
        if "ok" in result.stdout:
            return p

    return None


# ---------------------------------------------------------------------------
# DSN export — kicad-cli primary, pcbnew fallback
# ---------------------------------------------------------------------------
# kicad-cli pcb export specctra uses KICAD_CLI_PATH (= kicad-cli-xvfb wrapper)
# which sets DISPLAY=:99 so the persistent Xvfb handles the GTK requirement.
# pcbnew.LoadBoard() fallback also needs DISPLAY=:99 — passed in subprocess env.

DSN_EXPORT_SCRIPT = textwrap.dedent('''\
import sys, pcbnew
# KiCad 9.0 headless: InitSettings() must be called before LoadBoard()
for _fn in ("InitSettings",):
    _f = getattr(pcbnew, _fn, None)
    if _f:
        try: _f()
        except Exception: pass
# KiCad 9.0+: ExportSpecctraDSN replaces deprecated SPECCTRA_DB().ExportPCB()
board = pcbnew.LoadBoard(sys.argv[1])
if board is None:
    sys.exit(
        "pcbnew.LoadBoard() returned None even after InitSettings().\\n"
        "This should not happen if kicad-cli export specctra is used instead."
    )
if hasattr(pcbnew, 'ExportSpecctraDSN'):
    result = pcbnew.ExportSpecctraDSN(board, sys.argv[2])
    if not result:
        sys.exit("DSN export failed (ExportSpecctraDSN returned False)")
else:
    # KiCad < 9.0 fallback
    specctra = pcbnew.SPECCTRA_DB()
    err = specctra.ExportPCB(sys.argv[2], board)
    if err:
        sys.exit(f"DSN export error: {err}")
print(f"DSN exported: {sys.argv[2]}")
''')

SES_IMPORT_SCRIPT = textwrap.dedent('''\
import sys, pcbnew
# KiCad 9.0 headless: InitSettings() must be called before LoadBoard()
for _fn in ("InitSettings",):
    _f = getattr(pcbnew, _fn, None)
    if _f:
        try: _f()
        except Exception: pass
# KiCad 9.0+: ImportSpecctraSES replaces deprecated SPECCTRA_DB().ImportSES()
board = pcbnew.LoadBoard(sys.argv[1])
if board is None:
    sys.exit(
        "pcbnew.LoadBoard() returned None even after InitSettings().\\n"
        "Ensure DISPLAY=:99 is set and Xvfb is running:\\n"
        "  nohup Xvfb :99 -screen 0 1280x1024x24 &\\n"
        "Or use manual routing via add_trace MCP calls as fallback."
    )
if hasattr(pcbnew, 'ImportSpecctraSES'):
    result = pcbnew.ImportSpecctraSES(board, sys.argv[2])
    if not result:
        sys.exit("SES import failed (ImportSpecctraSES returned False)")
else:
    # KiCad < 9.0 fallback
    specctra = pcbnew.SPECCTRA_DB()
    err = specctra.ImportSES(sys.argv[2])
    if err:
        sys.exit(f"SES import error: {err}")
    specctra.FromSESSION(board)
# Fill copper zones after SES import — required to connect GND pads via copper pour
# Without zone fill, DRC reports GND unconnected items (false positives)
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
board.Save(sys.argv[1])
print(f"SES imported + zones filled: {sys.argv[2]}")
''')


def _export_dsn_cli(pcb_path: str, dsn_path: str) -> tuple[bool, str]:
    """Try DSN export via kicad-cli (headless-safe, no display needed)."""
    kicad_cli = os.environ.get("KICAD_CLI_PATH", "")
    if not kicad_cli or not Path(kicad_cli).exists():
        kicad_cli = shutil.which("kicad-cli") or "/usr/bin/kicad-cli"
    if not Path(kicad_cli).exists():
        return False, "kicad-cli not found"
    result = subprocess.run(
        [kicad_cli, "pcb", "export", "specctra",
         "--output", dsn_path, pcb_path],
        capture_output=True, text=True, timeout=60
    )
    ok = result.returncode == 0 and Path(dsn_path).exists()
    msg = result.stdout.strip() or result.stderr.strip()
    return ok, f"kicad-cli: {msg}" if ok else f"kicad-cli failed: {msg}"


def _display_env() -> dict:
    """Return env with DISPLAY=:99 for pcbnew subprocess calls.
    The persistent Xvfb on :99 (started by run_agent_zero.sh) handles
    GTK/wxWidgets initialisation for both kicad-cli and pcbnew."""
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":99")
    return env


def export_dsn(pcb_path: str, dsn_path: str, kicad_python: str) -> tuple[bool, str]:
    """Export .kicad_pcb → .dsn. Tries kicad-cli first (via KICAD_CLI_PATH wrapper
    which sets DISPLAY=:99), then falls back to pcbnew Python module."""
    # Primary: kicad-cli via kicad-cli-xvfb wrapper (sets DISPLAY=:99 automatically)
    ok, msg = _export_dsn_cli(pcb_path, dsn_path)
    if ok:
        return ok, msg

    # Fallback: pcbnew Python API — pass DISPLAY=:99 so the persistent Xvfb is used
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(DSN_EXPORT_SCRIPT)
        script_path = f.name

    try:
        result = subprocess.run(
            [kicad_python, script_path, pcb_path, dsn_path],
            capture_output=True, text=True, timeout=60, env=_display_env()
        )
        ok = result.returncode == 0 and Path(dsn_path).exists()
        msg = result.stdout.strip() or result.stderr.strip()
        return ok, msg
    finally:
        Path(script_path).unlink(missing_ok=True)


def import_ses(pcb_path: str, ses_path: str, kicad_python: str) -> tuple[bool, str]:
    """Import .ses → .kicad_pcb using pcbnew Python module with DISPLAY=:99."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(SES_IMPORT_SCRIPT)
        script_path = f.name

    try:
        result = subprocess.run(
            [kicad_python, script_path, pcb_path, ses_path],
            capture_output=True, text=True, timeout=60, env=_display_env()
        )
        ok = result.returncode == 0
        msg = result.stdout.strip() or result.stderr.strip()
        return ok, msg
    finally:
        Path(script_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Freerouting invocation
# ---------------------------------------------------------------------------

def run_freerouter(
    jar_path: str,
    dsn_path: str,
    ses_path: str,
    java_path: str,
    max_passes: int = 100,
    threads: int = 4,
    timeout_s: int = 3600,
) -> tuple[bool, str]:
    """
    Invoke freerouting headlessly.
    Returns (success, log_text).
    """
    cmd = [
        java_path, "-jar", str(jar_path),
        "--gui.enabled=false",
        "-de", dsn_path,
        "-do", ses_path,
        "-mp", str(max_passes),
        "-mt", str(threads),
        "-ll", "3",   # log level: 3 = INFO
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        log = result.stdout + "\n" + result.stderr
        ok = result.returncode == 0 and Path(ses_path).exists()
        return ok, log.strip()
    except subprocess.TimeoutExpired:
        return False, f"Freerouting timed out after {timeout_s}s"
    except FileNotFoundError as e:
        return False, f"Could not launch freerouting: {e}"


# ---------------------------------------------------------------------------
# Routing quality analysis (PCB file parsing — no pcbnew needed)
# ---------------------------------------------------------------------------

def analyse_pcb_file(pcb_path: str) -> RoutingStats:
    """
    Parse the .kicad_pcb file to extract routing statistics.
    This avoids needing the pcbnew module for analysis.
    """
    content = Path(pcb_path).read_text(encoding="utf-8")

    stats = RoutingStats()

    # Count segments (traces)
    segments = re.findall(r'\(segment\s', content)
    stats.total_segments = len(segments)

    # Count arcs
    arcs = re.findall(r'\(arc\s', content)
    stats.total_arc_segments = len(arcs)

    # Count vias
    vias = re.findall(r'\(via\s', content)
    stats.total_vias = len(vias)

    # Per-layer segment count
    layer_matches = re.findall(r'\(segment\b.*?\(layer\s+"([^"]+)"\)', content)
    for layer in layer_matches:
        stats.layer_usage[layer] = stats.layer_usage.get(layer, 0) + 1

    # Approximate total trace length (sum of segment lengths)
    length_total = 0.0
    seg_coords = re.findall(
        r'\(segment\s+\(start\s+([\-\d.]+)\s+([\-\d.]+)\)\s+\(end\s+([\-\d.]+)\s+([\-\d.]+)\)',
        content
    )
    for x1, y1, x2, y2 in seg_coords:
        dx = float(x2) - float(x1)
        dy = float(y2) - float(y1)
        length_total += (dx**2 + dy**2) ** 0.5
    stats.trace_length_mm = round(length_total, 2)

    return stats


def analyse_ses_file(ses_path: str, original_netlist_nets: List[str] = None) -> dict:
    """
    Parse the SES (Specctra Session) file to check what got routed.
    Returns dict with routed_nets list and via count.
    """
    if not Path(ses_path).exists():
        return {"routed_nets": [], "via_count": 0, "parsed": False}

    content = Path(ses_path).read_text(encoding="utf-8", errors="replace")

    # Extract routed net names
    routed_nets = re.findall(r'\(net\s+"?([^"\s)]+)"?', content)

    # Count via references
    via_count = content.count("(via")

    return {
        "routed_nets": list(set(routed_nets)),
        "via_count": via_count,
        "parsed": True,
    }


def run_drc_analysis(project_path: str) -> dict:
    """
    Run kicad-cli DRC and parse results.
    Returns dict with violation counts.
    """
    drc_result = {"unconnected": 0, "errors": 0, "total": 0, "run": False, "raw": ""}

    # Find kicad-cli — prefer kicad-cli-xvfb wrapper (sets DISPLAY=:99 for headless GTK)
    kicad_cli = shutil.which("kicad-cli-xvfb") or shutil.which("kicad-cli")
    if not kicad_cli:
        for candidate in [
            "/usr/local/bin/kicad-cli-xvfb",
            "/usr/bin/kicad-cli-xvfb",
            "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
            "/usr/bin/kicad-cli",
            r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
        ]:
            if Path(candidate).exists():
                kicad_cli = candidate
                break

    if not kicad_cli:
        drc_result["raw"] = "kicad-cli not found; skipping DRC"
        return drc_result

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        out_file = f.name

    try:
        result = subprocess.run(
            [kicad_cli, "pcb", "drc",
             "--output", out_file,
             "--format", "json",
             "--schematic-parity",
             project_path],
            capture_output=True, text=True, timeout=120
        )
        drc_result["run"] = result.returncode == 0

        if Path(out_file).exists():
            try:
                data = json.loads(Path(out_file).read_text())
                violations = data.get("violations", [])
                drc_result["total"] = len(violations)
                drc_result["unconnected"] = sum(
                    1 for v in violations
                    if "unconnected" in v.get("type", "").lower()
                )
                drc_result["errors"] = drc_result["total"] - drc_result["unconnected"]
                # Extract unrouted net names
                drc_result["unrouted_nets"] = [
                    v.get("description", "") for v in violations
                    if "unconnected" in v.get("type", "").lower()
                ]
            except (json.JSONDecodeError, KeyError):
                drc_result["raw"] = result.stdout
    finally:
        Path(out_file).unlink(missing_ok=True)

    return drc_result


# ---------------------------------------------------------------------------
# Quality report generator
# ---------------------------------------------------------------------------

def build_report(result: RoutingResult, drc: dict) -> str:
    """Produce a human-readable routing quality report."""
    s = result.stats
    sep = "=" * 60

    lines = [
        sep,
        "  ROUTING QUALITY REPORT",
        sep,
        f"  Board:       {Path(result.pcb_path).name}",
        f"  Iteration:   {s.iteration}",
        "",
        "── COMPLETION ──────────────────────────────────────────",
        f"  Routed:      {s.routed_connections}/{s.total_connections} connections"
            f"  ({s.completion_pct:.1f}%)",
    ]

    if s.unrouted_nets:
        lines.append(f"  Unrouted nets ({len(s.unrouted_nets)}):")
        for net in s.unrouted_nets[:10]:
            lines.append(f"    - {net}")
        if len(s.unrouted_nets) > 10:
            lines.append(f"    ... and {len(s.unrouted_nets) - 10} more")

    lines += [
        "",
        "── ROUTING STATISTICS ──────────────────────────────────",
        f"  Trace segments: {s.total_segments}",
        f"  Arc segments:   {s.total_arc_segments}",
        f"  Vias:           {s.total_vias}",
        f"  Total length:   {s.trace_length_mm:.1f} mm",
    ]

    if s.layer_usage:
        lines.append("  Layer distribution:")
        total_seg = sum(s.layer_usage.values()) or 1
        for layer, count in sorted(s.layer_usage.items()):
            pct = 100 * count / total_seg
            lines.append(f"    {layer:<12} {count:>5} segments  ({pct:.0f}%)")

    lines += [
        "",
        "── DRC RESULT ──────────────────────────────────────────",
    ]
    if drc.get("run"):
        if drc["total"] == 0:
            lines.append("  ✓ PASS — 0 violations")
        else:
            lines.append(f"  ✗ FAIL — {drc['total']} violation(s)")
            lines.append(f"    Unconnected items: {drc['unconnected']}")
            lines.append(f"    Other DRC errors:  {drc['errors']}")
            unrouted = drc.get("unrouted_nets", [])
            if unrouted:
                lines.append(f"    Unrouted nets:")
                for n in unrouted[:8]:
                    lines.append(f"      - {n}")
    else:
        lines.append(f"  DRC not run: {drc.get('raw','')}")

    lines += [
        "",
        "── QUALITY ASSESSMENT ──────────────────────────────────",
    ]

    issues = []
    suggestions = []

    if s.completion_pct < 100:
        issues.append(f"CRITICAL: {s.unrouted_connections} connection(s) unrouted")
        suggestions.append("Re-run with more passes (--passes 200) or relax design rules")

    if drc.get("errors", 0) > 0:
        issues.append(f"DRC: {drc['errors']} rule violation(s) found")
        suggestions.append("Fix DRC violations before manufacturing — run kicad_run_drc skill")

    # Via density warning (rough heuristic: > 50 vias is notable for a 2-layer board)
    if s.total_vias > 50:
        suggestions.append(
            f"High via count ({s.total_vias}) — consider manual rerouting of"
            " congested areas to reduce layer switches"
        )

    # Layer imbalance warning
    if s.layer_usage:
        counts = list(s.layer_usage.values())
        if counts and max(counts) > 3 * min(counts) and len(counts) > 1:
            suggestions.append(
                "Uneven layer distribution — one layer is carrying most traces; "
                "add directional bias settings to freerouter for better balance"
            )

    if not issues:
        lines.append("  ✓ GOOD — routing complete, DRC clean")
        lines.append("  Ready for manufacturing export.")
    else:
        for issue in issues:
            lines.append(f"  ✗ {issue}")

    if suggestions:
        lines.append("")
        lines.append("  Suggestions:")
        for s_ in suggestions:
            lines.append(f"    • {s_}")

    lines += [
        "",
        "── SIGNAL INTEGRITY NOTES ──────────────────────────────",
        "  (Not checked automatically — review manually if needed)",
        "  • High-speed signals (>10 MHz): keep traces short and direct",
        "  • Differential pairs: check length matching in KiCad GUI",
        "  • Power traces: verify width is adequate for current (see IPC-2221)",
        "  • Decoupling caps: confirm placement is close to IC power pins",
        sep,
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main routing orchestrator
# ---------------------------------------------------------------------------

def route_board(
    pcb_path: str,
    jar_path: str = None,
    max_passes: int = 100,
    threads: int = 4,
    output_dir: str = None,
    timeout_s: int = 3600,
    iterate: bool = True,
    max_iterations: int = 3,
) -> RoutingResult:
    """
    Full routing cycle: DSN export → Freerouter → SES import → quality analysis.

    Parameters
    ----------
    pcb_path      : path to .kicad_pcb file
    jar_path      : path to freerouting JAR (auto-detected if None)
    max_passes    : freerouter max pass count per iteration
    threads       : parallel routing threads
    output_dir    : where to store DSN/SES files (default: PCB file directory)
    timeout_s     : per-iteration freerouter timeout
    iterate       : if True, re-try with more passes if not 100% complete
    max_iterations: maximum retry attempts

    Returns
    -------
    RoutingResult
    """
    result = RoutingResult(pcb_path=pcb_path)

    if not Path(pcb_path).exists():
        result.message = f"PCB file not found: {pcb_path}"
        return result

    # Find tools
    kicad_python = find_kicad_python()
    if not kicad_python:
        result.message = (
            "KiCad Python (with pcbnew) not found. "
            "Ensure KiCad is installed and pcbnew is importable. "
            "On macOS: /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/..."
        )
        return result

    jar = find_freerouting_jar(jar_path)
    if not jar:
        result.message = (
            "Freerouting JAR not found. "
            "Download from https://github.com/freerouting/freerouting/releases "
            "and set FREEROUTING_JAR environment variable, "
            "or install the KiCad Freerouter plugin."
        )
        return result

    java = find_java()
    if not java:
        result.message = "Java not found. Install JRE and ensure 'java' is on PATH."
        return result

    if output_dir is None:
        output_dir = str(Path(pcb_path).parent / "routing")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    stem = Path(pcb_path).stem
    dsn_path = str(Path(output_dir) / f"{stem}.dsn")
    result.dsn_path = dsn_path

    # ---- Step 1: Export DSN ----
    ok, msg = export_dsn(pcb_path, dsn_path, kicad_python)
    if not ok:
        result.message = f"DSN export failed: {msg}"
        return result

    # ---- Iterate ----
    all_stats = []
    passes = max_passes

    for iteration in range(1, max_iterations + 1):
        ses_path = str(Path(output_dir) / f"{stem}_iter{iteration}.ses")

        # ---- Step 2: Run Freerouter ----
        ok, log = run_freerouter(
            str(jar), dsn_path, ses_path, java,
            max_passes=passes, threads=threads, timeout_s=timeout_s
        )

        if not ok:
            result.message = f"Freerouting failed (iteration {iteration}): {log[-500:]}"
            result.stats = RoutingStats(freerouter_log=log, iteration=iteration)
            break

        # ---- Step 3: Import SES ----
        # Back up PCB before import
        backup = pcb_path + f".pre_route_iter{iteration}.bak"
        shutil.copy2(pcb_path, backup)

        ok, msg = import_ses(pcb_path, ses_path, kicad_python)
        if not ok:
            result.message = f"SES import failed (iteration {iteration}): {msg}"
            # Restore backup
            shutil.copy2(backup, pcb_path)
            break

        result.ses_path = ses_path

        # ---- Step 4: Analyse ----
        stats = analyse_pcb_file(pcb_path)
        ses_info = analyse_ses_file(ses_path)
        stats.freerouter_log = log
        stats.iteration = iteration
        stats.total_vias = max(stats.total_vias, ses_info.get("via_count", 0))

        # DRC to get unconnected count
        project_path = str(Path(pcb_path).with_suffix(".kicad_pro"))
        drc = run_drc_analysis(project_path if Path(project_path).exists() else pcb_path)
        stats.drc_violations = drc.get("total", 0)
        stats.drc_unconnected = drc.get("unconnected", 0)
        stats.drc_errors = drc.get("errors", 0)
        stats.unrouted_nets = drc.get("unrouted_nets", [])
        stats.unrouted_connections = stats.drc_unconnected

        all_stats.append(stats)
        result.iterations.append(stats)
        result.stats = stats

        # Compute completion
        if stats.total_segments > 0:
            # Rough completion: no unconnected in DRC = 100%
            stats.completion_pct = 100.0 if stats.drc_unconnected == 0 else max(
                0.0,
                100.0 - (stats.drc_unconnected / max(stats.total_segments + stats.drc_unconnected, 1)) * 100
            )
        else:
            stats.completion_pct = 0.0

        if stats.drc_unconnected == 0:
            result.completed = True
            break

        if not iterate:
            break

        # Increase passes for next iteration
        passes = min(passes * 2, 500)

    result.success = True
    if result.stats:
        project_path = str(Path(pcb_path).with_suffix(".kicad_pro"))
        drc = run_drc_analysis(project_path if Path(project_path).exists() else pcb_path)
        result.report = build_report(result, drc)
        result.message = (
            f"Routing complete after {len(all_stats)} iteration(s). "
            f"Completion: {result.stats.completion_pct:.1f}%. "
            f"Vias: {result.stats.total_vias}. "
            f"DRC: {result.stats.drc_violations} violation(s)."
        )
    else:
        result.message = "Routing did not produce usable statistics."

    return result


def analyse_routing(pcb_path: str, project_path: str = None) -> dict:
    """
    Analyse routing quality of an already-routed PCB without re-running freerouter.
    Useful for checking a board that was routed manually or by another tool.
    """
    if not Path(pcb_path).exists():
        return {"success": False, "message": f"PCB file not found: {pcb_path}"}

    stats = analyse_pcb_file(pcb_path)

    proj = project_path or str(Path(pcb_path).with_suffix(".kicad_pro"))
    drc  = run_drc_analysis(proj if Path(proj).exists() else pcb_path)

    stats.drc_violations  = drc.get("total", 0)
    stats.drc_unconnected = drc.get("unconnected", 0)
    stats.unrouted_nets   = drc.get("unrouted_nets", [])
    stats.completion_pct  = 100.0 if drc.get("unconnected", 0) == 0 else 0.0

    dummy = RoutingResult(
        success=True, pcb_path=pcb_path,
        stats=stats, completed=stats.drc_unconnected == 0
    )
    report = build_report(dummy, drc)

    return {
        "success":        True,
        "completion_pct": stats.completion_pct,
        "total_vias":     stats.total_vias,
        "total_segments": stats.total_segments,
        "trace_length_mm": stats.trace_length_mm,
        "layer_usage":    stats.layer_usage,
        "drc_violations": stats.drc_violations,
        "drc_unconnected": stats.drc_unconnected,
        "unrouted_nets":  stats.unrouted_nets,
        "report":         report,
        "is_clean":       stats.drc_violations == 0 and stats.drc_unconnected == 0,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Automate KiCad PCB routing with Freerouter")
    parser.add_argument("pcb",             help="Input .kicad_pcb file")
    parser.add_argument("--jar",           help="Path to freerouting JAR (auto-detected if omitted)")
    parser.add_argument("--passes",  type=int, default=100, help="Max autoroute passes (default 100)")
    parser.add_argument("--threads", type=int, default=4,   help="Parallel threads (default 4)")
    parser.add_argument("--output-dir",    help="Directory for DSN/SES files")
    parser.add_argument("--no-iterate",    action="store_true", help="Do not retry if incomplete")
    parser.add_argument("--max-iter", type=int, default=3,  help="Max iterations (default 3)")
    parser.add_argument("--analyse-only",  action="store_true",
                        help="Analyse existing routing without re-routing")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-iteration timeout seconds")
    args = parser.parse_args()

    if args.analyse_only:
        result = analyse_routing(args.pcb)
        print(result.get("report", json.dumps(result, indent=2)))
        return

    result = route_board(
        args.pcb,
        jar_path=args.jar,
        max_passes=args.passes,
        threads=args.threads,
        output_dir=args.output_dir,
        timeout_s=args.timeout,
        iterate=not args.no_iterate,
        max_iterations=args.max_iter,
    )

    print(result.report or result.message)
    if not result.completed:
        sys.exit(1)


if __name__ == "__main__":
    main()
