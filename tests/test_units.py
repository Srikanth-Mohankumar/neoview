from neoview.utils.units import pt_to_mm, pt_to_pica, format_size


def test_pt_to_mm():
    assert abs(pt_to_mm(72.0) - 25.4) < 1e-6


def test_pt_to_pica():
    assert pt_to_pica(12.0) == 1.0


def test_format_size():
    text = format_size(72.0, 36.0)
    assert "W: 72.0pt" in text
    assert "H: 36.0pt" in text
