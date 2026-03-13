```python
#!/usr/bin/env python3
import argparse
import pcbnew

def mm_to_iu(mm):
    return pcbnew.FromMM(mm)

def iu_to_mm(iu):
    return iu / 1e6

def get_edge_bounds(board):
    """
    Infer current board extents from the Edge.Cuts bounding box.
    Returns (x0_mm, y0_mm, width_mm, height_mm) or None if not usable.
    """
    bbox = board.GetBoardEdgesBoundingBox()
    if bbox is None:
        return None

    w = bbox.GetWidth()
    h = bbox.GetHeight()
    if w <= 0 or h <= 0:
        return None

    x0 = bbox.GetX()
    y0 = bbox.GetY()
    return iu_to_mm(x0), iu_to_mm(y0), iu_to_mm(w), iu_to_mm(h)

def clear_edge_cuts(board):
    edge_layer = pcbnew.Edge_Cuts
    to_delete = [d for d in board.GetDrawings() if d.GetLayer() == edge_layer]
    for d in to_delete:
        board.Remove(d)
    return len(to_delete)

def add_rect_outline(board, x0_mm, y0_mm, width_mm, height_mm):
    edge_layer = pcbnew.Edge_Cuts

    x0 = mm_to_iu(x0_mm)
    y0 = mm_to_iu(y0_mm)
    x1 = mm_to_iu(x0_mm + width_mm)
    y1 = mm_to_iu(y0_mm + height_mm)

    def add_seg(xs, ys, xe, ye):
        seg = pcbnew.PCB_SHAPE(board)
        seg.SetShape(pcbnew.S_SEGMENT)
        seg.SetLayer(edge_layer)
        seg.SetStart(pcbnew.VECTOR2I(int(xs), int(ys)))
        seg.SetEnd(pcbnew.VECTOR2I(int(xe), int(ye)))
        board.Add(seg)

    # bottom, right, top, left
    add_seg(x0, y0, x1, y0)
    add_seg(x1, y0, x1, y1)
    add_seg(x1, y1, x0, y1)
    add_seg(x0, y1, x0, y0)

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Clear duplicate/malformed Edge.Cuts and rebuild a clean "
            "rectangular board outline, inferring size from the existing "
            "outline when possible."
        )
    )
    parser.add_argument("--pcb", required=True, help="Path to .kicad_pcb file")
    parser.add_argument(
        "--default-width",
        type=float,
        default=50.0,
        help="Fallback width in mm if no usable outline exists (default 50.0)",
    )
    parser.add_argument(
        "--default-height",
        type=float,
        default=25.0,
        help="Fallback height in mm if no usable outline exists (default 25.0)",
    )
    args = parser.parse_args()

    board = pcbnew.LoadBoard(args.pcb)

    # Try to infer current outline dimensions
    inferred = get_edge_bounds(board)
    if inferred is not None:
        x0_mm, y0_mm, width_mm, height_mm = inferred
        mode = "inferred"
    else:
        x0_mm, y0_mm = 0.0, 0.0
        width_mm, height_mm = args.default_width, args.default_height
        mode = "default"

    removed = clear_edge_cuts(board)
    add_rect_outline(board, x0_mm, y0_mm, width_mm, height_mm)
    board.Save(args.pcb)

    print(
        f"[outline] Mode={mode}, removed {removed} Edge.Cuts items, "
        f"set {width_mm:.3f}x{height_mm:.3f}mm outline at ({x0_mm:.3f},{y0_mm:.3f})"
    )

if __name__ == "__main__":
    main()
