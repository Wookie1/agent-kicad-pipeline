---
name: "kicad-project-init"
description: "Initialize a new KiCad PCB project: create directory structure, .kicad_pro, .kicad_sch, and .kicad_pcb files with correct defaults. Use this at the very start of every PCB design task before any other KiCad skill."
version: "1.1.0"
author: "kicad-pcb-skills"
tags: ["kicad", "pcb", "initialization", "project", "setup"]
trigger_patterns:
  - "new pcb project"
  - "create kicad project"
  - "start pcb design"
  - "initialize board"
  - "new board design"
---

# KiCad Project Initialization

## Overview
Creates a complete, valid KiCad 9.0 project on disk. Every other KiCad skill depends on the paths this skill produces. Run this exactly once per design.

## Required Inputs
| Input | Example | Notes |
|-------|---------|-------|
| `project_dir` | `/workspace/pcb` | Parent directory — created if absent |
| `project_name` | `motor_controller` | Lowercase, no spaces; becomes filename stem |
| `title` | `Motor Controller v1` | Human-readable title for title blocks |
| `revision` | `v1.0` | Design revision string |
| `company` | `Acme Corp` | Optional |


> **⚠️ IMPORTANT — Directory nesting:**
> `create_kicad_project.py` always creates a `<project_name>/` subdirectory inside
> `--project-dir`. Do NOT create the project subdirectory yourself before running.
>
> `--project-dir "/a0/usr/projects/pcb-design/workspace/pcb" --name "myboard"` creates:
> - `project_dir`    = `.../workspace/pcb/myboard/`
> - `project_path`   = `.../workspace/pcb/myboard/myboard.kicad_pro`
> - `schematic_path` = `.../workspace/pcb/myboard/myboard.kicad_sch`
> - `pcb_path`       = `.../workspace/pcb/myboard/myboard.kicad_pcb`

## Step 1 — Create the project

> **Project workspace for this deployment:** `/a0/usr/projects/pcb-design/workspace/pcb/`
> Always create new projects under this directory.

```bash
/a0/usr/skills-venv/bin/python3 /a0/usr/projects/pcb-design/.a0proj/skills/kicad-project-init/scripts/create_kicad_project.py \
  --project-dir "/a0/usr/projects/pcb-design/workspace/pcb" \
  --name "project_name" \
  --title "Project Title" \
  --revision "v1.0" \
  --company "Company Name"
```
Creates: `<project_name>.kicad_pro`, `.kicad_sch`, `.kicad_pcb`, and output subdirs (`gerbers/`, `bom/`, `assembly/`, `3d/`, `routing/`).

## Step 2 — Verify with MCP
```
get_project_structure(project_path="/a0/usr/projects/pcb-design/workspace/pcb/<project_name>/<project_name>.kicad_pro")
```
Confirm the response shows both `schematic` and `pcb` file references.

## Step 3 — Run diagnostics (first use only)
```
diagnose_kicad_paths()
```
If this reports missing paths, fix before proceeding — all export tools will fail.

## Step 4 — Record outputs
Save these paths — every subsequent skill needs them:
- `project_path`   = `<root>/<name>.kicad_pro`
- `schematic_path` = `<root>/<name>.kicad_sch`
- `pcb_path`       = `<root>/<name>.kicad_pcb`
- `project_dir`    = `<root>/`

## Success Criteria
- Script exits with code 0
- `get_project_structure` returns both schematic and pcb paths
- `diagnose_kicad_paths` shows no errors

## Error Recovery
| Error | Fix |
|-------|-----|
| `Permission denied` | Check write permissions on `project_dir` |
| `skills-venv not found` | Re-run `run_agent_zero.sh` to rebuild the venv |
| `get_project_structure` returns empty | Re-run script; verify `.kicad_pro` extension |

## Next Skill
→ **kicad-import-dxf** if the user provided a DXF board outline
→ **kicad-create-custom-symbol** if any component lacks a standard library symbol
→ **kicad-schematic-design** if using standard parts with a rectangular board
