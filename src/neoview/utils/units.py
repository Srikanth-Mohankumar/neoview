"""Unit conversion helpers."""


def pt_to_mm(pt: float) -> float:
    return pt * 25.4 / 72.0


def pt_to_pica(pt: float) -> float:
    return pt / 12.0


def format_size(w: float, h: float) -> str:
    return (
        f"W: {w:.1f}pt ({pt_to_pica(w):.2f}pc, {pt_to_mm(w):.2f}mm)  "
        f"H: {h:.1f}pt ({pt_to_pica(h):.2f}pc, {pt_to_mm(h):.2f}mm)"
    )
