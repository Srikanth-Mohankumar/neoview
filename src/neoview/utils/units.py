"""Unit conversion helpers."""

from __future__ import annotations

# Measurement units offered in the UI, in menu order.
UNITS = ("pt", "pc", "mm", "in")
UNIT_LABELS = {"pt": "Points (pt)", "pc": "Picas (pc)", "mm": "Millimetres (mm)", "in": "Inches (in)"}
_PT_PER_UNIT = {"pt": 1.0, "pc": 12.0, "mm": 72.0 / 25.4, "in": 72.0}
_DECIMALS = {"pt": 1, "pc": 2, "mm": 1, "in": 3}


def pt_to_mm(pt: float) -> float:
    return pt * 25.4 / 72.0


def pt_to_pica(pt: float) -> float:
    return pt / 12.0


def format_size(w: float, h: float) -> str:
    return (
        f"W: {w:.1f}pt ({pt_to_pica(w):.2f}pc, {pt_to_mm(w):.2f}mm)  "
        f"H: {h:.1f}pt ({pt_to_pica(h):.2f}pc, {pt_to_mm(h):.2f}mm)"
    )


def normalize_unit(unit: str | None) -> str:
    """Return ``unit`` if it is one of ``UNITS``, else "pt"."""
    return unit if unit in _PT_PER_UNIT else "pt"


def pt_to_unit(pt: float, unit: str) -> float:
    return pt / _PT_PER_UNIT[normalize_unit(unit)]


def format_length(pt: float, unit: str) -> str:
    """Format a length in points in ``unit``: ``format_length(72, "in") == "1.000 in"``."""
    unit = normalize_unit(unit)
    return f"{pt_to_unit(pt, unit):.{_DECIMALS[unit]}f} {unit}"
