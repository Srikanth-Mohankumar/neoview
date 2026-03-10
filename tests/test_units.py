from neoview.utils.units import pt_to_mm, pt_to_pica, format_size


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
