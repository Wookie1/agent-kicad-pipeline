#!/bin/bash
set -e

# ---------------------------------------------------------------------------
# Agent Zero + KiCad PCB skills startup script
#
# kicad-cli NOTE: The macOS KiCad binary is Mach-O format and CANNOT run
# inside a Linux Docker container (exec format error). kicad-cli is installed
# as a Linux binary from the Kali apt repos after the container starts.
# The agent0ai/agent-zero image is Kali Linux (NOT Ubuntu — PPAs don't work).
# KiCad symbol/footprint libraries from the macOS install ARE safe to mount
# since they are architecture-independent data files.
# ---------------------------------------------------------------------------

# Remove any stopped container with the same name (e.g. after a reboot)
docker rm -f agent-zero 2>/dev/null || true

docker run -d \
  -p 50001:80 \
  -v ~/agent-zero-data:/a0/usr \
  -v ~/agent-zero-pcb:/workspace/pcb \
  -v ~/agent-zero-tools/kicad-mcp:/a0/tools/kicad-mcp \
  -v /Applications/KiCad/KiCad.app/Contents/SharedSupport:/kicad-support:ro \
  -e KICAD_CLI_PATH=/usr/local/bin/kicad-cli-xvfb \
  -e KICAD_SYMBOL_LIBS=/kicad-support/symbols \
  -e KICAD_FOOTPRINT_LIBS=/kicad-support/footprints \
  -e FREEROUTING_JAR=/a0/usr/freerouting/freerouting.jar \
  -e DISPLAY=:99 \
  --name agent-zero \
  agent0ai/agent-zero:latest

echo "Container started. Waiting for it to be ready..."
sleep 5

# ---------------------------------------------------------------------------
# Install Linux kicad-cli from distro repos (Kali Linux = Debian-based).
# NOTE: Ubuntu PPAs do NOT work on Kali — use plain apt-get.
# The agent0ai/agent-zero image is Kali Linux (arm64 or amd64).
# Kali rolling has KiCad 9.x in its repos — no extra repo needed.
# Skipped if already installed; persists for the life of the container.
# First run takes ~3-5 minutes (downloads ~400 MB of deps).
# ---------------------------------------------------------------------------
docker exec -e DEBIAN_FRONTEND=noninteractive agent-zero bash -c "
  if /usr/bin/kicad-cli --version &>/dev/null; then
    echo \"kicad-cli already installed: \$(/usr/bin/kicad-cli --version | head -1)\"
  else
    echo 'Installing kicad from Kali repos — first run only (~3-5 min)...'
    apt-get update -q
    apt-get install -y -q --no-install-recommends kicad
    echo \"kicad-cli installed: \$(/usr/bin/kicad-cli --version | head -1)\"
  fi
"

# ---------------------------------------------------------------------------
# Set up kicad-mcp virtual environment (uv)
# ---------------------------------------------------------------------------
docker exec agent-zero bash -c "cd /a0/tools/kicad-mcp && curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env && uv sync"

# Fix typing.List → list for Python 3.10 compatibility in kicad-mcp
docker exec agent-zero bash -c "
  for f in /a0/tools/kicad-mcp/kicad_mcp/tools/schematic_tools.py \
            /a0/tools/kicad-mcp/kicad_mcp/tools/pcb_layout_tools.py \
            /a0/tools/kicad-mcp/kicad_mcp/tools/manufacturing_tools.py \
            /a0/tools/kicad-mcp/kicad_mcp/tools/library_tools.py; do
    [ -f \"\$f\" ] && sed -i 's/List\[List\[float\]\]/list[list[float]]/g; s/List\[str\]/list[str]/g' \"\$f\"
  done
"

# ---------------------------------------------------------------------------
# Install Java runtime for Freerouter (also skipped if already installed)
# ---------------------------------------------------------------------------
docker exec -e DEBIAN_FRONTEND=noninteractive agent-zero bash -c "
  if command -v java &>/dev/null; then
    echo \"Java already installed: \$(java -version 2>&1 | head -1)\"
  else
    echo 'Installing Java runtime for Freerouter...'
    apt-get install -y -q --no-install-recommends default-jre-headless
    echo \"Java installed: \$(java -version 2>&1 | head -1)\"
  fi
"

# ---------------------------------------------------------------------------
# Install Xvfb and create kicad-cli-xvfb wrapper.
#
# KiCad's wxWidgets/GTK framework requires a display even for headless CLI
# operations (DRC, export, PCB update). A single persistent Xvfb on :99
# handles ALL display needs:
#   - kicad-cli calls (via the DISPLAY=:99 wrapper below)
#   - kicad-mcp internal pcbnew calls (use DISPLAY=:99 directly)
#   - kicad_freerouter.py pcbnew subprocess calls (pass DISPLAY=:99 in env)
#
# Note: xvfb-run (per-command Xvfb) was tested but does NOT work for
# kicad-cli pcb drc — the per-command Xvfb fails to connect before pcbnew
# initialises. DISPLAY=:99 with the persistent Xvfb is the reliable fix.
# ---------------------------------------------------------------------------
docker exec -e DEBIAN_FRONTEND=noninteractive agent-zero bash -c "
  if command -v Xvfb &>/dev/null; then
    echo 'Xvfb already installed'
  else
    echo 'Installing Xvfb...'
    apt-get install -y -q --no-install-recommends xvfb
    echo 'Xvfb installed'
  fi
"
docker exec agent-zero bash -c "
  cat > /usr/local/bin/kicad-cli-xvfb << 'WRAPPER'
#!/bin/bash
DISPLAY=:99 exec /usr/bin/kicad-cli \"\$@\"
WRAPPER
  chmod +x /usr/local/bin/kicad-cli-xvfb
  echo 'kicad-cli-xvfb wrapper created at /usr/local/bin/kicad-cli-xvfb'
"

# Start a persistent Xvfb on :99 — used by kicad-cli (via wrapper above),
# kicad-mcp pcbnew calls, and kicad_freerouter.py pcbnew subprocesses.
docker exec agent-zero bash -c "
  nohup Xvfb :99 -screen 0 1280x1024x24 >/tmp/xvfb.log 2>&1 &
  sleep 1
  pgrep -x Xvfb > /dev/null \
    && echo 'Persistent Xvfb :99 started' \
    || echo 'WARNING: Xvfb :99 failed to start — check /tmp/xvfb.log'
"

# ---------------------------------------------------------------------------
# Download Freerouting JAR to persistent volume (skipped if already present).
# JAR stored at /a0/usr/freerouting/ which maps to ~/agent-zero-data/freerouting/
# on the host — survives container restarts.
# ---------------------------------------------------------------------------
docker exec agent-zero bash -c "
  JAR=/a0/usr/freerouting/freerouting.jar
  if [ -f \"\$JAR\" ]; then
    echo \"Freerouting JAR already present: \$JAR\"
  else
    mkdir -p /a0/usr/freerouting
    echo 'Downloading Freerouting JAR from GitHub...'
    # Try latest release asset names (varies by version)
    curl -fsSL -o \"\$JAR\" \
      \"\$(curl -s https://api.github.com/repos/freerouting/freerouting/releases/latest \
         | grep browser_download_url | grep -i '\.jar' | head -1 | cut -d'\"' -f4)\" \
      && echo \"Downloaded: \$JAR\" \
      || echo 'WARNING: Freerouting download failed — routing will use manual mode'
  fi
"

# ---------------------------------------------------------------------------
# Set up skills virtual environment for PCB helper scripts
# Location: /a0/usr/skills-venv  (persists across restarts via ~/agent-zero-data mount)
# Packages: ezdxf (DXF import), svgwrite + reportlab (assembly drawings)
# ---------------------------------------------------------------------------
docker exec agent-zero bash -c "
  if [ ! -f /a0/usr/skills-venv/bin/python3 ]; then
    echo 'Creating skills-venv...'
    python3 -m venv /a0/usr/skills-venv
    /a0/usr/skills-venv/bin/pip install --quiet --upgrade pip
    /a0/usr/skills-venv/bin/pip install --quiet ezdxf svgwrite reportlab fastmcp easyeda2kicad
    echo 'skills-venv created.'
  else
    echo 'skills-venv already exists.'
    # Ensure pipeline packages are present (fastmcp + easyeda2kicad for LCSC parts)
    /a0/usr/skills-venv/bin/pip install --quiet fastmcp easyeda2kicad
  fi
"

# ---------------------------------------------------------------------------
# Copy pcb-pipeline MCP server scripts to tools directory if missing.
# Source: /a0/usr/skills/pcb-pipeline/ (skills dir on the volume)
# Dest:   /a0/usr/tools/pcb-pipeline/
# This ensures the server is available after a fresh volume setup without
# needing to re-run install_pcb_pipeline.sh manually.
# ---------------------------------------------------------------------------
docker exec agent-zero bash -c "
  DEST=/a0/usr/tools/pcb-pipeline
  SRC=/a0/usr/skills/pcb-pipeline
  if [ ! -f \"\$DEST/pcb_pipeline_mcp.py\" ]; then
    if [ -f \"\$SRC/pcb_pipeline_mcp.py\" ]; then
      mkdir -p \"\$DEST\"
      cp \"\$SRC\"/*.py \"\$DEST\"/
      echo 'pcb-pipeline scripts copied to /a0/usr/tools/pcb-pipeline/'
    else
      echo 'WARNING: pcb-pipeline scripts not found — run install_pcb_pipeline.sh from the host'
    fi
  else
    echo 'pcb-pipeline scripts already in place.'
  fi
"

echo ""
echo "Setup complete."
echo "  Skills venv : /a0/usr/skills-venv/bin/python3"
echo "  PCB workspace: /workspace/pcb"
echo "  kicad-cli   : /usr/bin/kicad-cli (Linux binary from Kali repos)"
echo ""
echo "NOTE: kicad-mcp is type=stdio — agent-zero spawns it on demand"
echo "      using KICAD_CLI_PATH from ~/agent-zero-data/settings.json."
echo "      No manual startup needed."