from neoview.utils.units import (
    UNITS,
    format_length,
    format_size,
    normalize_unit,
    pt_to_mm,
    pt_to_pica,
)


def test_pt_to_mm():
    assert abs(pt_to_mm(72.0) - 25.4) < 1e-6


def test_pt_to_pica():
    assert pt_to_pica(12.0) == 1.0


def test_format_size():
    text = format_size(72.0, 36.0)
    assert text == "W: 72.0pt (6.00pc, 25.40mm)  H: 36.0pt (3.00pc, 12.70mm)"


def test_format_size_zero_and_negative_values():
    text = format_size(0.0, -12.0)
    assert text == "W: 0.0pt (0.00pc, 0.00mm)  H: -12.0pt (-1.00pc, -4.23mm)"


def test_format_length_in_each_unit():
    # 72 pt is one inch: 6 pc, 25.4 mm.
    assert format_length(72.0, "pt") == "72.0 pt"
    assert format_length(72.0, "pc") == "6.00 pc"
    assert format_length(72.0, "mm") == "25.4 mm"
    assert format_length(72.0, "in") == "1.000 in"
    assert set(UNITS) == {"pt", "pc", "mm", "in"}


def test_format_length_unknown_unit_falls_back_to_points():
    assert normalize_unit("furlong") == "pt"
    assert format_length(10.0, "furlong") == "10.0 pt"
