# PCB Design Agents for Agent Zero

Specialized agent profiles for full-stack KiCad PCB design.
Each directory is an Agent Zero **agent profile** — a named persona with custom prompts.

---

## Format Corrections vs. Original JSON

| Your JSON field | Agent Zero reality | Fix applied |
|---|---|---|
| Single `agents.json` with all agents | One directory per agent | Split into 8 profile folders |
| `"entry": true` | No entry field — Agent 0 is set globally in UI | Removed |
| `"tools": [...]` in agent.json | Not listed there; auto-discovered by filename | Removed; usage described in role prompts |
| `"tools": ["subagent_caller"]` | No such tool; correct name is `call_subordinate` | Fixed in orchestrator role prompt |
| `"tools": ["image_loader"]` | No such tool; correct name is `vision_load` | Fixed in vision-parts role prompt |
| `"model": "ollama:fast_reasoner"` | Not in agent.json; per-profile via settings.json; format `provider/name` | Each profile now has settings.json |
| `"model": "cloud:strong_checker"` | `cloud` is not a valid provider; use `openai`, `anthropic`, etc. | Fixed in pcb-quality/settings.json |

---

## Directory Structure

```
pcb-design-agents/
├── README.md
├── settings-snippet.json              ← global settings.json reference (model names to customise)
├── project-instructions.md            ← paste into Agent Zero project Instructions field
│
├── pcb-orchestrator/                  ← entry-point profile (set in Agent Zero UI)
│   ├── agent.json
│   ├── settings.json                  ← sets orchestrator model
│   └── prompts/
│       └── agent.system.main.role.md  ← workflow + delegation table
│
├── pcb-requirements/                  ← natural language → structured requirements doc
│   ├── agent.json
│   ├── settings.json
│   └── prompts/agent.system.main.role.md
│
├── pcb-schematic/                     ← schematic + netlist generation
├── pcb-layout/                        ← footprint placement + routing
├── pcb-drc-dfm/                       ← DRC/DFM checks + auto-fix
├── pcb-export/                        ← Gerbers + fab package
├── pcb-vision-parts/                  ← image/datasheet analysis (optional)
└── pcb-quality/                       ← final sign-off against requirements doc
    (each: agent.json + settings.json + prompts/agent.system.main.role.md)
```

---

## Deployment — Project-Scoped (correct approach)

These profiles are designed to live **inside a specific Agent Zero project**, not globally.
Project-level profiles take highest precedence and do not pollute the global profile list.

### Step 1 — Create the project in Agent Zero UI first

In the web UI: **Projects → New Project** → give it a name (e.g. `kicad-pcb`).
Agent Zero creates `/a0/usr/projects/kicad-pcb/.a0proj/` automatically.

### Step 2 — Copy profiles into the project's agent folder

```bash
# On your host machine — ~/agent-zero-data maps to /a0/usr/ in the container
PROJECT_NAME="kicad-pcb"   # match exactly what you named it in the UI

mkdir -p ~/agent-zero-data/projects/$PROJECT_NAME/.a0proj/agents/

cp -r pcb-design-agents/pcb-* \
      ~/agent-zero-data/projects/$PROJECT_NAME/.a0proj/agents/
```

Agent Zero automatically discovers all profile directories in `.a0proj/agents/` —
**no `agents.json` registration file is needed** for project-local profiles.

### Step 3 — Activate the orchestrator profile

In Agent Zero UI: **Settings → Agent Profile → pcb-orchestrator**

> ⚠ This is a global setting — it applies across all projects in the current session.
> Switch back to `agent0` (or your default) when working outside this project.
> There is currently no per-project active-profile field in Agent Zero.

### Step 4 — Paste the project instructions

Open the project in Agent Zero UI → **Instructions** tab → paste the full contents of
`project-instructions.md`.

---

## Model Configuration

Each profile has its own `settings.json` with a `chat_model` override.
Agent Zero's built-in `_15_load_profile_settings.py` extension loads this automatically
when a sub-agent is spawned with that profile — no custom code required.

Edit the `settings.json` in each profile directory to match your actual model tags:

| Profile | Default model | Change to |
|---------|--------------|-----------|
| `pcb-orchestrator` | `ollama/qwen2.5:14b-instruct` | Your fast reasoner |
| `pcb-requirements` | `ollama/qwen2.5:7b` | Your small general model |
| `pcb-schematic` | `ollama/qwen2.5-coder:7b` | Your small coder |
| `pcb-layout` | `ollama/qwen2.5-coder:7b` | Your small coder |
| `pcb-drc-dfm` | `ollama/qwen2.5-coder:7b` | Your small coder |
| `pcb-export` | `ollama/qwen2.5:7b` | Your small general model |
| `pcb-vision-parts` | `ollama/minicpm-v:8b` | Your vision-capable model |
| `pcb-quality` | `openai/gpt-4o` | Your strong checker |

For `pcb-vision-parts`, keep `"vision": true` in settings.json so Agent Zero enables
the vision tool for that profile.

---

## How Delegation Works

The orchestrator uses `call_subordinate` (the LLM generates this JSON):

```json
{
  "tool_name": "call_subordinate",
  "tool_args": {
    "message": "Design the schematic. Requirements: /workspace/pcb/requirements/myboard_requirements.md. Paths: schematic=/workspace/pcb/myboard/myboard.kicad_sch ...",
    "profile": "pcb-schematic",
    "reset": "true"
  }
}
```

- `profile` must exactly match the directory name under `.a0proj/agents/`
- `reset: "true"` destroys any previous subordinate and starts fresh
- Sub-agents are stateless — pass all file paths in `message` every time

---

## PCB Workflow Summary

```
User request
    │
    ▼
pcb-orchestrator (Agent 0)
    │
    ├──► pcb-requirements  →  _requirements.md           (Phase 0)
    ├──► pcb-vision-parts  →  parts_analysis.json        (Phase 0, if images)
    ├──► pcb-schematic     →  .kicad_sch + .net          (Phase 1 → Gate 1)
    ├──► pcb-layout        →  placed + routed .kicad_pcb (Phase 2–3 → Gates 2–3)
    ├──► pcb-drc-dfm       →  drc_report.json            (loops until clean)
    ├──► pcb-quality       →  Quality Report PASS/FAIL   (Phase 4 → Gate 4)
    └──► pcb-export        →  fab package .zip           (Phase 5)
```
