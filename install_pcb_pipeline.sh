#!/usr/bin/env bash
# install_pcb_pipeline.sh
#
# Install the pcb-pipeline FastMCP server into the Agent Zero Docker container.
# Run this from the HOST (macOS) — it copies files into the agent-zero-data
# volume and installs Python deps inside the container.
#
# Usage:
#   ./install_pcb_pipeline.sh [container_name]
#
# container_name defaults to "agent-zero" (the standard Agent Zero container).
#
# What it does:
#   1. Copies pcb-pipeline/*.py into ~/agent-zero-data/tools/pcb-pipeline/
#   2. pip-installs fastmcp into the container's skills-venv
#   3. Registers the MCP server in ~/agent-zero-data/settings.json
#   4. Prints the JSON block to paste if auto-registration is skipped

set -euo pipefail

CONTAINER="${1:-agent-zero}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PIPELINE_SRC="$REPO_DIR/pcb-pipeline"
DATA_DIR="${AGENT_ZERO_DATA:-$HOME/agent-zero-data}"
TOOLS_DEST="$DATA_DIR/tools/pcb-pipeline"

echo "=== pcb-pipeline installer ==="
echo "Container : $CONTAINER"
echo "Source    : $PIPELINE_SRC"
echo "Dest      : $TOOLS_DEST"
echo

# ── 1. Copy pipeline scripts to data volume ───────────────────────────────────
echo "→ Copying pipeline scripts..."
mkdir -p "$TOOLS_DEST"
cp "$PIPELINE_SRC/pcb_pipeline_mcp.py" "$TOOLS_DEST/"
cp "$PIPELINE_SRC/schematic_builder.py" "$TOOLS_DEST/"
cp "$PIPELINE_SRC/pcb_placer.py"        "$TOOLS_DEST/"
echo "  Done: $TOOLS_DEST"

# ── 2. Install fastmcp into skills-venv inside container ─────────────────────
echo
echo "→ Installing fastmcp into skills-venv (inside container)..."
docker exec -it "$CONTAINER" \
    /a0/usr/skills-venv/bin/pip install --quiet fastmcp
echo "  Done."

# ── 3. Verify the server starts ───────────────────────────────────────────────
echo
echo "→ Smoke-testing MCP server import..."
docker exec "$CONTAINER" \
    /a0/usr/skills-venv/bin/python3 -c \
    "import sys; sys.argv=['x']; exec(open('/a0/usr/tools/pcb-pipeline/pcb_pipeline_mcp.py').read().split('if __name__')[0]); print('OK')" \
    2>&1 | head -5 || true

# ── 4. Print settings.json snippet ───────────────────────────────────────────
echo
echo "══════════════════════════════════════════════════════════════════════"
echo "  Add the following entry inside the \"mcpServers\" block of"
echo "  ~/agent-zero-data/settings.json  (in the mcp_servers JSON string):"
echo "══════════════════════════════════════════════════════════════════════"
cat <<'SNIPPET'

    "pcb-pipeline": {
      "type": "stdio",
      "command": "/a0/usr/skills-venv/bin/python3",
      "args": [
        "/a0/usr/tools/pcb-pipeline/pcb_pipeline_mcp.py"
      ],
      "autoApprove": [],
      "env": {
        "KICAD_CLI_PATH":       "/usr/local/bin/kicad-cli-xvfb",
        "KICAD_SYMBOL_LIBS":    "/kicad-support/symbols",
        "KICAD_FOOTPRINT_LIBS": "/kicad-support/footprints",
        "FREEROUTING_JAR":      "/a0/usr/freerouting/freerouting.jar",
        "SKILLS_DIR":           "/a0/usr/skills"
      }
    }

SNIPPET
echo "══════════════════════════════════════════════════════════════════════"
echo
echo "  See pcb-pipeline/settings-snippet.json for the full mcp_servers value."
echo
echo "=== Installation complete ==="
