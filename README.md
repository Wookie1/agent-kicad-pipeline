# agent-kicad-pipeline

KiCad 9.0 PCB design automation for AI agents.

Provides a **FastMCP server** (`pcb-pipeline`) that exposes eight high-level tools covering the full PCB design flow, plus a set of **Agent Zero skills** and **sub-agent profiles** for multi-agent orchestration.

Works with any MCP-capable agent framework (Agent Zero, Claude Desktop, Cursor, etc.).

---

## What's inside

```
agent-kicad-pipeline/
├── pcb-pipeline/                  FastMCP server — the core artifact
│   ├── pcb_pipeline_mcp.py        8 high-level MCP tools
│   ├── schematic_builder.py       Auto-layout schematic + netlist from component/net lists
│   ├── pcb_placer.py              Connectivity-aware footprint placement (no pcbnew needed)
│   ├── requirements.txt           fastmcp
│   └── settings-snippet.json      MCP server config block for Agent Zero settings.json
│
├── pcb-design-agents/             Agent Zero sub-agent profiles
│   ├── pcb-orchestrator/          Top-level router
│   ├── pcb-requirements/          Requirements capture
│   ├── pcb-schematic/             Schematic entry
│   ├── pcb-layout/                PCB layout
│   ├── pcb-drc-dfm/               DRC + design-for-manufacture review
│   ├── pcb-export/                Manufacturing file export
│   ├── pcb-vision-parts/          Vision-based part identification
│   └── pcb-quality/               Final quality gate
│
├── kicad-project-init/            Skill: scaffold a new KiCad project
├── kicad-schematic-design/        Skill: schematic entry scripts
├── kicad-pcb-layout/              Skill: footprint placement scripts
├── kicad-route-pcb/               Skill: Freerouter auto-routing
├── kicad-run-drc/                 Skill: DRC checks
├── kicad-manufacturing-export/    Skill: Gerber / BOM / CPL / STEP export
├── kicad-create-custom-symbol/    Skill: custom symbol creation
├── kicad-create-custom-footprint/ Skill: custom footprint creation
├── kicad-import-dxf/              Skill: import DXF board outlines
│
├── install_pcb_pipeline.sh        Installer: copy + pip-install into Docker container
└── run_agent_zero.sh              Docker startup script (skills-venv, Xvfb, env vars)
```

---

## pcb-pipeline MCP tools

| Tool | Input | What it does |
|------|-------|-------------|
| `pcb_init` | project name, board size, fab | Creates project scaffold (dirs, `.kicad_pro`, placeholder schematic) |
| `pcb_schematic` | `components[]`, `nets[]` | Auto-places symbols, generates `.kicad_sch` + `.net` — **no coordinates needed** |
| `pcb_search_lib` | query, type | Searches symbol / footprint libraries, returns `lib_id` strings ready to use |
| `pcb_layout` | project dir, optional hints | Imports netlist → PCB, runs connectivity-aware footprint placement |
| `pcb_route` | project dir | Auto-routes via Freerouter JAR |
| `pcb_drc` | project dir | Runs KiCad DRC, returns structured violation list |
| `pcb_export` | project dir, fab | Exports Gerbers, drill, BOM, CPL, schematic PDF, PCB PDF, STEP |
| `pcb_status` | project dir | Returns current phase, file list, stats |

### Why a pipeline server instead of individual MCP calls?

The raw `kicad-mcp` tools require 30–50+ individual calls for a complete board and expose several reliability pitfalls:

- `run_erc` segfaults headlessly (SIGSEGV) on KiCad 9
- `update_pcb_from_schematic` fails without a live display
- `pcbnew.LoadBoard()` silently returns `None` without `DISPLAY=:99`
- Agents must manually calculate component coordinates on every call

The pipeline server handles all environment complexity server-side. An agent describes *what* to build; the server figures out *how*.

---

## Quick start

### Prerequisites (Docker container)

- KiCad 9.0 (`apt-get install kicad` on Kali Linux)
- Java (`apt-get install default-jre-headless`) — required for Freerouter
- Freerouting JAR at `/a0/usr/freerouting/freerouting.jar`
- Persistent Xvfb on `:99` (started by `run_agent_zero.sh`)
- Agent Zero Docker image: `agent0ai/agent-zero:latest`

### Install the MCP server

```bash
# From the macOS host — copies scripts into data volume, installs fastmcp
./install_pcb_pipeline.sh agent-zero
```

Then add the `pcb-pipeline` block from `pcb-pipeline/settings-snippet.json` into the `mcp_servers` JSON string in `~/agent-zero-data/settings.json`:

```json
"pcb-pipeline": {
  "type": "stdio",
  "command": "/a0/usr/skills-venv/bin/python3",
  "args": ["/a0/usr/tools/pcb-pipeline/pcb_pipeline_mcp.py"],
  "autoApprove": [],
  "env": {
    "KICAD_CLI_PATH":       "/usr/local/bin/kicad-cli-xvfb",
    "KICAD_SYMBOL_LIBS":    "/kicad-support/symbols",
    "KICAD_FOOTPRINT_LIBS": "/kicad-support/footprints",
    "FREEROUTING_JAR":      "/a0/usr/freerouting/freerouting.jar",
    "SKILLS_DIR":           "/a0/usr/skills"
  }
}
```

### Deploy Agent Zero skills and profiles

```bash
# Copy skills into the project
cp -r kicad-*/  ~/agent-zero-data/projects/pcb-design/.a0proj/skills/

# Copy sub-agent profiles
cp -r pcb-design-agents/*/  ~/agent-zero-data/projects/pcb-design/.a0proj/agents/
```

---

## Example agent prompt

```
Design a 3-channel LED driver board.

Components:
  U1  NE555 timer        Timer:NE555         Package_SO:SOIC-8_3.9x4.9mm_P1.27mm
  R1  10Ω resistor       Device:R            Resistor_SMD:R_0402_1005Metric
  R2  10Ω resistor       Device:R            Resistor_SMD:R_0402_1005Metric
  R3  10Ω resistor       Device:R            Resistor_SMD:R_0402_1005Metric
  D1  red LED            Device:LED          LED_SMD:LED_0603_1608Metric
  D2  red LED            Device:LED          LED_SMD:LED_0603_1608Metric
  D3  red LED            Device:LED          LED_SMD:LED_0603_1608Metric
  C1  100nF decoupling   Device:C            Capacitor_SMD:C_0402_1005Metric
  J1  2-pin connector    Connector:Conn_01x02 Connector_PinHeader_2.54mm:PinHeader_1x02

Nets:
  VCC  → U1.8, C1.1, J1.1
  GND  → U1.1, C1.2, R1.2, R2.2, R3.2, J1.2
  OUT  → U1.3, R1.1, R2.1, R3.1
  CH1  → R1.2, D1.A
  CH2  → R2.2, D2.A
  CH3  → R3.2, D3.A
  GND  → D1.K, D2.K, D3.K

Board: 50×40mm, target JLCPCB.
```

The orchestrator delegates through schematic → layout → route → DRC → export, returning a `fab/` folder ready to upload.

---

## Docker environment

The `skills-venv` at `/a0/usr/skills-venv/` is created by `run_agent_zero.sh` and persists in the `agent-zero-data` volume. It contains `fastmcp`, `ezdxf`, `svgwrite`, and `reportlab`.

The system `python3` at `/usr/bin/python3` provides `pcbnew` (installed with the KiCad package).

Key environment variables:

```
KICAD_CLI_PATH=/usr/local/bin/kicad-cli-xvfb  # wrapper: DISPLAY=:99 exec kicad-cli
DISPLAY=:99                                    # persistent Xvfb (run_agent_zero.sh)
FREEROUTING_JAR=/a0/usr/freerouting/freerouting.jar
```

---

## Known limitations and workarounds

| Issue | Workaround used here |
|-------|---------------------|
| `run_erc` SIGSEGV on KiCad 9 headless | `schematic_preflight.py` structural check |
| `update_pcb_from_schematic` headless fail | `sch_to_pcb_sync.py` string-manipulation sync |
| `export_bom_csv` MCP tool broken | `generate_bom.py` fallback + inline BOM from PCB text |
| `pcbnew.LoadBoard()` silent `None` | All pcbnew calls run with `DISPLAY=:99` in subprocess env |
| `track_count` always 0 post-route | `pcb_drc` `unconnected_count` used as routing completeness proxy |

---

## Security note

`settings.json` files are excluded by `.gitignore` — they can contain model API base URLs.
Never commit `*.env`, `secrets.env`, or any `settings.json` files.
API keys are stored in `~/agent-zero-data/.env` on the host, not in this repository.

---

## License

MIT
