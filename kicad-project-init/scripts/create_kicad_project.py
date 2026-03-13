#!/usr/bin/env python3
"""
create_kicad_project.py — KiCad project scaffold generator

Creates a complete, valid KiCad project directory with correct defaults:
  - <project_name>.kicad_pro   (JSON project file with sensible design rules)
  - <project_name>.kicad_sch   (empty schematic with title block)
  - <project_name>.kicad_pcb   (empty PCB with full layer stack)
  - gerbers/ bom/ assembly/ 3d/ routing/  (output subdirectories)

Usage:
    python3 create_kicad_project.py \\
        --project-dir /path/to/parent \\
        --name project_name \\
        --title "Project Title" \\
        --revision "v1.0" \\
        --company "Company Name"
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import date
from pathlib import Path


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# .kicad_pro — JSON project file
# ---------------------------------------------------------------------------

def _kicad_pro(name: str) -> dict:
    return {
        "board": {
            "3dviewports": [],
            "design_settings": {
                "defaults": {
                    "board_outline_line_width": 0.05,
                    "copper_line_width": 0.2,
                    "copper_text_italic": False,
                    "copper_text_size_h": 1.5,
                    "copper_text_size_v": 1.5,
                    "copper_text_thickness": 0.3,
                    "copper_text_upright": False,
                    "courtyard_line_width": 0.05,
                    "fab_line_width": 0.1,
                    "fab_text_italic": False,
                    "fab_text_size_h": 1.0,
                    "fab_text_size_v": 1.0,
                    "fab_text_thickness": 0.15,
                    "fab_text_upright": False,
                    "other_line_width": 0.15,
                    "other_text_italic": False,
                    "other_text_size_h": 1.0,
                    "other_text_size_v": 1.0,
                    "other_text_thickness": 0.15,
                    "other_text_upright": False,
                    "pads": {
                        "drill": 0.762,
                        "height": 1.524,
                        "width": 1.524,
                    },
                    "silk_line_width": 0.12,
                    "silk_text_italic": False,
                    "silk_text_size_h": 1.0,
                    "silk_text_size_v": 1.0,
                    "silk_text_thickness": 0.15,
                    "silk_text_upright": False,
                    "zones": {"min_clearance": 0.5},
                },
                "diff_pair_dimensions": [],
                "drc_exclusions": [],
                "meta": {"version": 2},
                "rule_severities": {},
                "rules": {
                    "min_clearance": 0.2,
                    "min_copper_edge_clearance": 0.5,
                    "min_hole_clearance": 0.25,
                    "min_hole_to_hole": 0.25,
                    "min_microvia_diameter": 0.2,
                    "min_microvia_drill": 0.1,
                    "min_silk_clearance": 0.0,
                    "min_text_height": 0.5,
                    "min_through_hole_diameter": 0.3,
                    "min_track_width": 0.2,
                    "min_via_annular_width": 0.1,
                    "min_via_diameter": 0.4,
                    "solder_mask_clearance": 0.0,
                    "solder_mask_min_width": 0.0,
                    "solder_paste_clearance": 0.0,
                    "solder_paste_margin_ratio": 0.0,
                    "use_height_for_length_calcs": True,
                },
                "track_widths": [0.2, 0.4, 0.8],
                "via_dimensions": [{"diameter": 0.8, "drill": 0.4}],
            },
            "ipc2581": {
                "dist": "",
                "distpn": "",
                "internal_id": "",
                "mfr": "",
                "mpn": "",
            },
            "layer_presets": [],
            "viewports": [],
        },
        "boards": [],
        "cvpcb": {"equivalence_files": []},
        "erc": {
            "erc_exclusions": [],
            "meta": {"version": 0},
            "pin_map": [
                [0, 0, 0, 0, 0, 0, 2, 0, 2, 2, 0, 2],
                [0, 4, 0, 1, 0, 1, 2, 0, 2, 2, 0, 2],
                [0, 0, 0, 0, 0, 0, 2, 0, 2, 2, 0, 2],
                [0, 1, 0, 0, 0, 0, 2, 0, 1, 1, 0, 2],
                [0, 0, 0, 0, 0, 0, 2, 0, 2, 2, 0, 2],
                [0, 1, 0, 0, 0, 0, 2, 0, 1, 1, 0, 2],
                [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
                [0, 0, 0, 0, 0, 0, 2, 0, 2, 2, 0, 2],
                [2, 2, 2, 1, 2, 1, 2, 2, 2, 2, 0, 2],
                [2, 2, 2, 1, 2, 1, 2, 2, 2, 0, 0, 2],
                [0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 2],
                [2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2],
            ],
            "rule_severities": {
                "bus_definition_conflict": "error",
                "bus_entry_needed": "error",
                "bus_label_syntax": "error",
                "bus_to_bus_conflict": "error",
                "bus_to_net_conflict": "error",
                "conflicting_netclasses": "error",
                "different_unit_footprint": "error",
                "different_unit_net": "error",
                "duplicate_reference": "error",
                "duplicate_sheet_names": "error",
                "endpoint_off_grid": "warning",
                "extra_units": "error",
                "global_label_dangling": "warning",
                "hier_label_mismatch": "error",
                "label_dangling": "warning",
                "lib_symbol_issues": "ignore",
                "missing_bidi_pin": "warning",
                "missing_power_pin": "error",
                "missing_unit": "warning",
                "multiple_net_names": "warning",
                "net_not_bus_member": "warning",
                "no_connect_connected": "warning",
                "no_connect_dangling": "error",
                "pin_not_connected": "error",
                "pin_not_driven": "error",
                "pin_to_pin": "warning",
                "power_pin_not_driven": "error",
                "similar_labels": "warning",
                "simulation_model_issue": "ignore",
                "unannotated_symbol": "error",
                "unit_value_mismatch": "error",
                "unresolved_variable": "error",
                "wire_dangling": "error",
            },
        },
        "libraries": {
            "pinned_footprint_libs": [],
            "pinned_symbol_libs": [],
        },
        "meta": {
            "filename": f"{name}.kicad_pro",
            "version": 1,
        },
        "net_settings": {
            "classes": [
                {
                    "bus_width": 12.0,
                    "clearance": 0.2,
                    "diff_pair_gap": 0.25,
                    "diff_pair_via_gap": 0.25,
                    "diff_pair_width": 0.2,
                    "line_style": 0,
                    "microvia_diameter": 0.3,
                    "microvia_drill": 0.1,
                    "name": "Default",
                    "pcb_color": "rgba(0, 0, 0, 0.000)",
                    "schematic_color": "rgba(0, 0, 0, 0.000)",
                    "track_width": 0.25,
                    "via_diameter": 0.8,
                    "via_drill": 0.4,
                    "wire_width": 6.0,
                }
            ],
            "meta": {"version": 3},
            "net_colors": {},
            "netclass_assignments": {},
            "netclass_patterns": [],
        },
        "pcbnew": {
            "last_paths": {
                "gencad": "",
                "idf": "",
                "netlist": "",
                "plot": "",
                "pos_files": "",
                "specctra_dsn": "",
                "step": "",
                "svg": "",
                "vrml": "",
            },
            "page_layout_descr_file": "",
        },
        "schematic": {
            "annotate_start_num": 0,
            "drawing": {
                "dashed_lines_dash_length_ratio": 12.0,
                "dashed_lines_gap_length_ratio": 3.0,
                "default_line_thickness": 6.0,
                "default_text_size": 50.0,
                "field_names": [],
                "intersheets_ref_own_page": False,
                "intersheets_ref_prefix": "",
                "intersheets_ref_short": False,
                "intersheets_ref_show": False,
                "intersheets_ref_suffix": "",
                "junction_size_choice": 3,
                "label_size_ratio": 0.375,
                "operating_point_overlay_i_precision": 3,
                "operating_point_overlay_i_range": "~A",
                "operating_point_overlay_v_precision": 3,
                "operating_point_overlay_v_range": "~V",
                "overbar_offset_ratio": 1.23,
                "pin_symbol_size": 25.0,
                "text_offset_ratio": 0.15,
            },
            "legacy_lib_dir": "",
            "legacy_lib_list": [],
            "meta": {"version": 1},
            "net_format_name": "",
            "page_layout_descr_file": "",
            "plot_directory": "",
            "spice_adjust_passive_values": False,
            "spice_current_sheet_as_root": False,
            "spice_external_command": "spice %I",
            "spice_model_current_sheet_as_root": True,
            "spice_save_all_currents": False,
            "spice_save_all_dissipations": False,
            "spice_save_all_voltages": False,
            "subpart_first_id": 65,
            "subpart_id_separator": 0,
        },
        "sheets": [],
        "text_variables": {},
    }


# ---------------------------------------------------------------------------
# .kicad_sch — empty schematic (s-expression)
# ---------------------------------------------------------------------------

def _kicad_sch(title: str, revision: str, company: str, today: str) -> str:
    return f"""\
(kicad_sch
  (version 20231120)
  (generator "eeschema")
  (generator_version "9.0")
  (uuid "{_uuid()}")
  (paper "A4")
  (title_block
    (title "{title}")
    (date "{today}")
    (rev "{revision}")
    (company "{company}")
  )
  (lib_symbols)
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


# ---------------------------------------------------------------------------
# .kicad_pcb — empty PCB with full standard 2-layer stack (s-expression)
# ---------------------------------------------------------------------------

def _kicad_pcb(title: str, revision: str, company: str, today: str) -> str:
    return f"""\
(kicad_pcb
  (version 20240108)
  (generator "pcbnew")
  (generator_version "9.0")
  (general
    (thickness 1.6)
    (legacy_teardrops no)
  )
  (paper "A4")
  (title_block
    (title "{title}")
    (date "{today}")
    (rev "{revision}")
    (company "{company}")
  )
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhesive" user "B.Adhesive")
    (33 "F.Adhesive" user "F.Adhesive")
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.Silkscreen" user)
    (37 "F.Silkscreen" user)
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (40 "User.Drawings" user)
    (41 "User.Comments" user)
    (42 "User.Eco1" user)
    (43 "User.Eco2" user)
    (44 "Edge.Cuts" user)
    (45 "Margin" user)
    (46 "B.Courtyard" user)
    (47 "F.Courtyard" user)
    (48 "B.Fab" user)
    (49 "F.Fab" user)
  )
  (setup
    (pad_to_mask_clearance 0)
    (pcbplotparams
      (layerselection 0x00010fc_ffffffff)
      (plot_on_all_layers_selection 0x0000000_00000000)
      (disableapertmacros false)
      (usegerberextensions true)
      (usegerberattributes true)
      (usegerberadvancedattributes true)
      (creategerberjobfile true)
      (dashed_line_dash_ratio 12.000000)
      (dashed_line_gap_ratio 3.000000)
      (svguseinch false)
      (svgprecision 4)
      (excludeedgelayer true)
      (plotframeref false)
      (viasonmask false)
      (mode 1)
      (useauxorigin false)
      (hpglpennumber 1)
      (hpglpenspeed 20)
      (hpglpendiameter 15.000000)
      (dxfpolygonmode true)
      (dxfimperialunits true)
      (dxfusepcbnewfont true)
      (psnegative false)
      (psa4output false)
      (plotreference true)
      (plotvalue true)
      (plotfptext true)
      (plotinvisibletext false)
      (sketchpadsonfab false)
      (subtractmaskfromsilk true)
      (outputformat 1)
      (mirror false)
      (drillshape 1)
      (scaleselection 1)
      (outputdirectory "manufacturing/gerbers/")
    )
  )
  (net 0 "")
)
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def create_project(
    project_dir: str,
    name: str,
    title: str = "",
    revision: str = "v1.0",
    company: str = "",
) -> dict[str, str]:
    """
    Create a KiCad project.  Returns paths dict:
      project_path, schematic_path, pcb_path, project_dir
    """
    project_name = name.strip().replace(" ", "_")
    root = Path(project_dir).expanduser().resolve() / project_name
    root.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    if not title:
        title = project_name.replace("_", " ").title()

    # Output subdirectories
    for subdir in ("gerbers", "bom", "assembly", "3d", "routing"):
        (root / subdir).mkdir(exist_ok=True)

    # .kicad_pro
    pro_path = root / f"{project_name}.kicad_pro"
    pro_path.write_text(json.dumps(_kicad_pro(project_name), indent=2))

    # .kicad_sch
    sch_path = root / f"{project_name}.kicad_sch"
    sch_path.write_text(_kicad_sch(title, revision, company, today))

    # .kicad_pcb
    pcb_path = root / f"{project_name}.kicad_pcb"
    pcb_path.write_text(_kicad_pcb(title, revision, company, today))

    return {
        "project_path": str(pro_path),
        "schematic_path": str(sch_path),
        "pcb_path": str(pcb_path),
        "project_dir": str(root),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a new KiCad PCB project with correct file structure and defaults.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 create_kicad_project.py --project-dir ~/designs --name motor_ctrl
  python3 create_kicad_project.py \\
      --project-dir /home/user/boards \\
      --name usb_hub \\
      --title "USB Hub v1" \\
      --revision "v1.0" \\
      --company "Acme Corp"
""",
    )
    parser.add_argument(
        "--project-dir", required=True,
        help="Parent directory — created if absent",
    )
    parser.add_argument(
        "--name", required=True,
        help="Project name (lowercase, no spaces; becomes the filename stem)",
    )
    parser.add_argument(
        "--title", default="",
        help="Human-readable title for title blocks (default: derived from name)",
    )
    parser.add_argument(
        "--revision", default="v1.0",
        help="Design revision string (default: v1.0)",
    )
    parser.add_argument(
        "--company", default="",
        help="Company name for title block",
    )
    args = parser.parse_args()

    paths = create_project(
        project_dir=args.project_dir,
        name=args.name,
        title=args.title,
        revision=args.revision,
        company=args.company,
    )

    print(f"Created project: {paths['project_dir']}")
    print(f"  project_path   = {paths['project_path']}")
    print(f"  schematic_path = {paths['schematic_path']}")
    print(f"  pcb_path       = {paths['pcb_path']}")
    print(f"  output dirs    = gerbers/ bom/ assembly/ 3d/ routing/")


if __name__ == "__main__":
    main()
