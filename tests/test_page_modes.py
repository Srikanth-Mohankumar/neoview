import pytest
from PySide6.QtGui import QColor, QImage

from neoview.ui.page_modes import (
    COLOR_MODES,
    PAGE_MODES,
    Rect,
    apply_color_mode,
    layout_pages,
    page_background,
    page_rows,
)

A4 = (595.0, 842.0)
LETTER_LANDSCAPE = (792.0, 612.0)
SPACING = 20.0


def _centre_x(rect: Rect) -> float:
    return rect.x + rect.w / 2.0


# -- rows ----------------------------------------------------------------------------


def test_modes_are_exposed():
    assert PAGE_MODES == ("single", "continuous", "two-page", "two-page-cover")
    assert COLOR_MODES == ("normal", "night", "sepia")


@pytest.mark.parametrize("mode", ["single", "continuous"])
def test_single_column_rows(mode):
    assert page_rows(mode, 3) == [(0,), (1,), (2,)]


def test_two_page_rows_even_and_odd():
    assert page_rows("two-page", 4) == [(0, 1), (2, 3)]
    assert page_rows("two-page", 5) == [(0, 1), (2, 3), (4,)]
    assert page_rows("two-page", 1) == [(0,)]


def test_cover_rows_even_and_odd():
    assert page_rows("two-page-cover", 1) == [(0,)]
    assert page_rows("two-page-cover", 4) == [(0,), (1, 2), (3,)]
    assert page_rows("two-page-cover", 5) == [(0,), (1, 2), (3, 4)]


def test_rows_empty_document():
    assert page_rows("two-page", 0) == []
    layout = layout_pages([], 800, 1.0, SPACING, "continuous")
    assert layout.rects == [] and layout.rows == []
    assert layout.scene_height == 0.0


def test_unknown_mode_rejected():
    with pytest.raises(ValueError):
        page_rows("three-page", 3)
    with pytest.raises(ValueError):
        layout_pages([A4], 800, 1.0, SPACING, "book")
    with pytest.raises(ValueError):
        layout_pages([A4], 800, 0.0, SPACING, "continuous")


# -- continuous / single -------------------------------------------------------------


def test_continuous_matches_current_pdfview_layout():
    """Reproduce PdfView._layout_pages: y starts at gap, pages centred on the widest."""
    sizes = [A4, LETTER_LANDSCAPE, A4]
    zoom = 1.5
    layout = layout_pages(sizes, 0, zoom, SPACING, "continuous")

    max_w = max(w for w, _ in sizes) * zoom
    y = SPACING
    for (w, h), rect in zip(sizes, layout.rects):
        assert rect.x == pytest.approx((max_w - w * zoom) / 2)
        assert rect.y == pytest.approx(y)
        assert rect.w == pytest.approx(w * zoom)
        assert rect.h == pytest.approx(h * zoom)
        y += h * zoom + SPACING
    assert layout.scene_width == pytest.approx(max_w)
    assert layout.scene_height == pytest.approx(y)
    assert not layout.paged


def test_continuous_centres_in_wide_viewport():
    layout = layout_pages([A4, A4], 2000, 1.0, SPACING, "continuous")
    assert layout.scene_width == 2000
    for rect in layout.rects:
        assert _centre_x(rect) == pytest.approx(1000)


def test_single_mode_is_paged_with_continuous_geometry():
    sizes = [A4, LETTER_LANDSCAPE, A4]
    single = layout_pages(sizes, 900, 1.0, SPACING, "single")
    cont = layout_pages(sizes, 900, 1.0, SPACING, "continuous")
    assert single.paged
    assert single.rects == cont.rects
    bounds = single.row_bounds(single.row_of(1))
    assert bounds == single.rects[1]


# -- two-page ------------------------------------------------------------------------


def test_two_page_pairs_side_by_side_with_spacing():
    layout = layout_pages([A4] * 4, 0, 1.0, SPACING, "two-page")
    r0, r1, r2, r3 = layout.rects
    w, h = A4
    assert layout.scene_width == pytest.approx(2 * w + SPACING)
    assert r0 == Rect(0, SPACING, w, h)
    assert r1 == Rect(w + SPACING, SPACING, w, h)
    assert r2.y == pytest.approx(SPACING + h + SPACING)
    assert r3.y == r2.y
    assert r2.x == r0.x and r3.x == r1.x
    assert layout.scene_height == pytest.approx(SPACING + 2 * (h + SPACING))


def test_two_page_odd_last_page_sits_in_left_slot():
    layout = layout_pages([A4] * 3, 0, 1.0, SPACING, "two-page")
    assert layout.rects[2].x == pytest.approx(layout.rects[0].x)
    assert layout.rects[2].x + layout.rects[2].w + SPACING / 2 == pytest.approx(
        layout.scene_width / 2
    )


def test_cover_mode_puts_first_page_alone_on_the_right():
    layout = layout_pages([A4] * 5, 0, 1.0, SPACING, "two-page-cover")
    cover, p1, p2, p3, p4 = layout.rects
    centre = layout.scene_width / 2
    assert cover.x == pytest.approx(centre + SPACING / 2)
    # The cover lines up with the right-hand pages of the spreads below it.
    assert cover.x == pytest.approx(p2.x)
    assert cover.x == pytest.approx(p4.x)
    # Odd pages are on the left, even pages on the right.
    assert p1.x < centre < p2.x
    assert p3.x < centre < p4.x
    assert p1.y == p2.y > cover.y
    assert p3.y == p4.y > p1.y


def test_cover_mode_even_count_last_page_on_left():
    layout = layout_pages([A4] * 4, 0, 1.0, SPACING, "two-page-cover")
    assert layout.rows == [(0,), (1, 2), (3,)]
    assert layout.rects[3].x == pytest.approx(layout.rects[1].x)


def test_mixed_sizes_centred_per_row():
    sizes = [A4, LETTER_LANDSCAPE, (300.0, 400.0), (300.0, 400.0)]
    zoom = 0.5
    layout = layout_pages(sizes, 1600, zoom, SPACING, "two-page")
    centre = 800
    for row in layout.rows:
        bounds = layout.row_bounds(layout.rows.index(row))
        assert _centre_x(bounds) == pytest.approx(centre)
    # Row 0: the shorter landscape page is centred vertically on the taller A4 page.
    a4, land = layout.rects[0], layout.rects[1]
    assert a4.h == pytest.approx(842 * zoom)
    assert land.h == pytest.approx(612 * zoom)
    assert land.y + land.h / 2 == pytest.approx(a4.y + a4.h / 2)
    assert land.x == pytest.approx(a4.x + a4.w + SPACING)
    # Row 1 starts below the tallest page of row 0.
    assert layout.rects[2].y == pytest.approx(SPACING + 842 * zoom + SPACING)


def test_scene_wide_enough_for_widest_spread():
    sizes = [(100.0, 100.0), (100.0, 100.0), (400.0, 100.0), (400.0, 100.0)]
    layout = layout_pages(sizes, 0, 1.0, SPACING, "two-page")
    assert layout.scene_width == pytest.approx(800 + SPACING)
    for rect in layout.rects:
        assert rect.x >= -1e-9
        assert rect.x + rect.w <= layout.scene_width + 1e-9


def test_row_of_and_row_bounds():
    layout = layout_pages([A4] * 5, 0, 1.0, SPACING, "two-page-cover")
    assert [layout.row_of(i) for i in range(5)] == [0, 1, 1, 2, 2]
    bounds = layout.row_bounds(1)
    assert bounds.x == pytest.approx(layout.rects[1].x)
    assert bounds.w == pytest.approx(2 * A4[0] + SPACING)
    with pytest.raises(IndexError):
        layout.row_of(9)


# -- colour --------------------------------------------------------------------------


def _strip(colors) -> QImage:
    img = QImage(len(colors), 2, QImage.Format.Format_RGB888)
    for x, c in enumerate(colors):
        for y in range(2):
            img.setPixelColor(x, y, QColor(*c))
    return img


def _rgb(img: QImage, x: int) -> tuple[int, int, int]:
    c = img.pixelColor(x, 0)
    return c.red(), c.green(), c.blue()


def test_normal_mode_returns_identical_copy():
    img = _strip([(255, 255, 255), (10, 20, 30)])
    out = apply_color_mode(img, "normal")
    assert out == img
    assert out is not img


def test_unknown_color_mode_rejected():
    with pytest.raises(ValueError):
        apply_color_mode(_strip([(0, 0, 0)]), "neon")
    with pytest.raises(ValueError):
        page_background("neon")


def test_night_inverts_luminance():
    img = _strip([(255, 255, 255), (0, 0, 0), (128, 128, 128), (200, 200, 200)])
    out = apply_color_mode(img, "night")
    assert out.size() == img.size()
    assert max(_rgb(out, 0)) <= 2  # white paper -> black
    assert min(_rgb(out, 1)) >= 253  # black text -> white
    for x, grey in ((2, 128), (3, 200)):
        r, g, b = _rgb(out, x)
        assert r == g == b
        assert r == pytest.approx(255 - grey, abs=3)


@pytest.mark.parametrize(
    "color",
    [(255, 0, 0), (0, 0, 200), (30, 120, 30), (200, 120, 20)],
)
def test_night_keeps_hue(color):
    out = apply_color_mode(_strip([color]), "night")
    before = QColor(*color).hue()
    after = out.pixelColor(0, 0).hue()
    diff = min(abs(after - before), 360 - abs(after - before))
    assert diff <= 15, (color, _rgb(out, 0))


def test_night_turns_dark_colours_light():
    dark_blue = (0, 0, 120)
    out = apply_color_mode(_strip([dark_blue]), "night")
    assert QColor(*_rgb(out, 0)).lightness() > QColor(*dark_blue).lightness()


def test_sepia_is_warm_and_keeps_contrast():
    img = _strip([(255, 255, 255), (0, 0, 0), (128, 128, 128), (0, 0, 255)])
    out = apply_color_mode(img, "sepia")
    white, black, grey, blue = (_rgb(out, x) for x in range(4))
    for r, g, b in (white, grey, blue):
        assert r >= g >= b
        assert r > b  # warm tint
    assert sum(black) < 150  # ink stays dark
    assert sum(white) > 650  # paper stays light
    assert sum(black) < sum(grey) < sum(white)
    bg = page_background("sepia")
    assert white == pytest.approx((bg.red(), bg.green(), bg.blue()), abs=4)


def test_page_background_colours():
    assert page_background("normal") == QColor(255, 255, 255)
    assert page_background("night") == QColor(0, 0, 0)
    assert page_background("sepia").red() > page_background("sepia").blue()


def test_color_mode_keeps_device_pixel_ratio_and_handles_null():
    img = _strip([(255, 255, 255)])
    img.setDevicePixelRatio(2.0)
    assert apply_color_mode(img, "night").devicePixelRatio() == 2.0
    assert apply_color_mode(QImage(), "sepia").isNull()


def test_color_mode_handles_padded_rows():
    """Widths that are not a multiple of 4 make Grayscale8 rows padded."""
    img = QImage(5, 3, QImage.Format.Format_RGB888)
    img.fill(QColor(255, 255, 255))
    img.setPixelColor(4, 2, QColor(0, 0, 0))
    out = apply_color_mode(img, "night")
    assert max(_rgb(out, 0)) <= 2
    c = out.pixelColor(4, 2)
    assert min(c.red(), c.green(), c.blue()) >= 253
    c = out.pixelColor(3, 2)
    assert max(c.red(), c.green(), c.blue()) <= 2
