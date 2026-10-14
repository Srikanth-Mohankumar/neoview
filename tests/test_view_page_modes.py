"""PdfView page modes: continuous stays pixel-identical, plus single and two-page modes."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from neoview.ui.page_modes import PAGE_MODES, layout_pages
from neoview.ui.pdf_view import PdfView

# Mixed sizes: A4 portrait, US letter landscape, a small card, A4 again, ...
SIZES = [(595.0, 842.0), (792.0, 612.0), (300.0, 420.0), (595.0, 842.0), (612.0, 792.0)]


def _make_pdf(path: Path, sizes=SIZES) -> Path:
    doc = fitz.open()
    for i, (w, h) in enumerate(sizes):
        page = doc.new_page(width=w, height=h)
        page.insert_text((30, 50), f"page {i + 1}", fontsize=20)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def view(qtbot, tmp_path):
    v = PdfView()
    qtbot.addWidget(v)
    v.resize(700, 500)
    v.show()
    assert v.open_document(str(_make_pdf(tmp_path / "doc.pdf")))
    QApplication.processEvents()
    yield v
    v.close_document()


def _legacy_continuous(sizes, zoom, gap):
    """The continuous layout PdfView used before page modes existed, verbatim."""
    y = float(gap)
    max_width = max(w for w, _h in sizes) * zoom
    positions = []
    for w, h in sizes:
        positions.append(((max_width - w * zoom) / 2, y))
        y += h * zoom + gap
    return positions, (max_width, y)


@pytest.mark.parametrize("zoom", [1.0, 1.37, 0.4142, 2.5])
def test_continuous_is_pixel_identical_to_legacy_layout(view, zoom):
    view.set_zoom(zoom, immediate=True)
    positions, (scene_w, scene_h) = _legacy_continuous(SIZES, view.zoom, PdfView.PAGE_GAP)
    actual = [(p.pos().x(), p.pos().y()) for p in view._pages]
    assert actual == positions  # exact, not approx
    rect = view.scene().sceneRect()
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == (0.0, 0.0, scene_w, scene_h)
    assert view._page_positions == [y for _x, y in positions]


@pytest.mark.parametrize("zoom", [1.0, 1.37, 0.4142, 2.5])
def test_layout_pages_matches_legacy_exactly(zoom):
    positions, (scene_w, scene_h) = _legacy_continuous(SIZES, zoom, PdfView.PAGE_GAP)
    layout = layout_pages(SIZES, 0.0, zoom, float(PdfView.PAGE_GAP), "continuous")
    assert [(r.x, r.y) for r in layout.rects] == positions
    assert (layout.scene_width, layout.scene_height) == (scene_w, scene_h)


# -- mode switching ----------------------------------------------------------------------


def test_default_mode_and_validation(view):
    assert view.page_mode() == "continuous"
    with pytest.raises(ValueError):
        view.set_page_mode("three-up")


def test_set_page_mode_emits_once(qtbot, view):
    seen = []
    view.page_mode_changed.connect(seen.append)
    view.set_page_mode("two-page")
    view.set_page_mode("two-page")  # no-op
    assert seen == ["two-page"]
    assert view.page_mode() == "two-page"


@pytest.mark.parametrize("mode", PAGE_MODES)
def test_page_positions_follow_layout(view, mode):
    view.set_page_mode(mode)
    view.set_zoom(0.8, immediate=True)
    layout = layout_pages(SIZES, 0.0, view.zoom, float(PdfView.PAGE_GAP), mode)
    assert [(p.pos().x(), p.pos().y()) for p in view._pages] == [
        (r.x, r.y) for r in layout.rects
    ]


def test_two_page_places_spreads_side_by_side(view):
    view.set_page_mode("two-page")
    p = view._pages
    assert p[0].pos().y() == pytest.approx(p[1].pos().y(), abs=200)  # same row
    assert p[1].pos().x() > p[0].pos().x() + SIZES[0][0] * view.zoom
    assert p[2].pos().y() > p[0].pos().y() + SIZES[0][1] * view.zoom
    # Pages that share a row share a row-top position.
    assert view._page_positions[0] == view._page_positions[1]
    assert view._page_positions[2] == view._page_positions[3]


def test_cover_mode_first_page_alone_on_right(view):
    view.set_page_mode("two-page-cover")
    rect = view.scene().sceneRect()
    cover = view._pages[0]
    assert cover.pos().x() > rect.width() / 2  # right of the spine
    assert view._page_positions[1] == view._page_positions[2]
    assert view._page_positions[1] > view._page_positions[0]


def test_two_page_next_moves_by_spread(view):
    view.set_page_mode("two-page")
    assert view.current_page == 0
    view.next_page()
    assert view.current_page == 2
    view.next_page()
    assert view.current_page == 4
    view.next_page()  # last spread: stays
    assert view.current_page == 4
    view.prev_page()
    assert view.current_page == 2


def test_cover_next_moves_by_spread(view):
    view.set_page_mode("two-page-cover")
    view.next_page()
    assert view.current_page == 1
    view.next_page()
    assert view.current_page == 3


def test_mode_switch_keeps_current_page(view):
    view.go_to_page(3)
    assert view.current_page == 3
    view.set_page_mode("two-page")
    assert view.current_page in (2, 3)  # page 4 is in the (3, 4) spread
    assert 3 in view._layout.rows[view._page_row[view.current_page]]
    view.set_page_mode("continuous")
    assert view.current_page in (2, 3)


def test_single_mode_shows_one_page(view):
    view.set_page_mode("single")
    visible = [i for i, p in enumerate(view._pages) if p.isVisible()]
    assert visible == [0]
    rect = view.scene().sceneRect()
    page = view._pages[0]
    assert rect.top() <= page.pos().y()
    assert rect.bottom() >= page.pos().y() + SIZES[0][1] * view.zoom
    assert rect.bottom() <= view._pages[1].pos().y()  # next page is outside the scene

    view.next_page()
    assert view.current_page == 1
    assert [i for i, p in enumerate(view._pages) if p.isVisible()] == [1]
    view.go_to_page(4)
    assert view.current_page == 4
    assert view._visible_page_indices() == [4]

    view.set_page_mode("continuous")
    assert all(p.isVisible() for p in view._pages)
    assert view.current_page == 4


def test_single_mode_wheel_at_edge_turns_page(view, monkeypatch):
    view.set_page_mode("single")
    view.set_zoom(0.3, immediate=True)  # whole page fits: scroll range is empty
    QApplication.processEvents()
    monkeypatch.setattr(PdfView, "PAGE_FLIP_COOLDOWN_S", 0.0)

    def wheel(dy):
        ev = QWheelEvent(QPointF(50, 50), QPointF(50, 50), QPoint(0, 0), QPoint(0, dy),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(view.viewport(), ev)

    wheel(-120)
    assert view.current_page == 1
    wheel(-120)
    assert view.current_page == 2
    wheel(120)
    assert view.current_page == 1


def test_fit_width_two_page_fits_the_spread(view):
    view.set_page_mode("two-page")
    view.fit_width()
    rows = view._layout.rows
    row = rows[view._page_row[view.current_page]]
    width = sum(SIZES[i][0] for i in row) * view.zoom + PdfView.PAGE_GAP
    assert width <= view.viewport().width()
    assert width >= view.viewport().width() - 60


def test_reload_keeps_page_mode(view, tmp_path):
    view.set_page_mode("two-page-cover")
    _make_pdf(Path(view.doc_path), SIZES + [(595.0, 842.0)])
    assert view.reload_document()
    assert view.page_mode() == "two-page-cover"
    assert view._layout.rows[0] == (0,)
    assert len(view._pages) == len(SIZES) + 1


def test_single_mode_hides_other_pages_overlays_and_hits(view):
    from PySide6.QtCore import QRectF

    view.set_page_mode("single")
    view.set_zoom(0.25, immediate=True)  # viewport much taller than the shown page
    # A big search hit on page 2, which single mode does not show.
    view.set_search_highlights([(1, QRectF(0, 0, SIZES[1][0], SIZES[1][1]), True)])
    QApplication.processEvents()
    hidden = view._pages[1]
    centre = hidden.pos() + QPointF(SIZES[1][0] * view.zoom / 2, SIZES[1][1] * view.zoom / 2)
    assert view._get_page_at(centre) == -1
    vp = view.mapFromScene(centre)
    assert view.viewport().rect().contains(vp)
    img = view.viewport().grab().toImage()
    assert img.pixelColor(vp.x(), vp.y()).rgb() == view.backgroundBrush().color().rgb()
    # The shown page is still hit-testable.
    shown = view._pages[0]
    assert view._get_page_at(shown.pos() + QPointF(5, 5)) == 0


def _settle(qtbot, view):
    def done():
        QApplication.processEvents()
        return view.pending_render_count() == 0
    qtbot.waitUntil(done, timeout=5000)
    for _ in range(3):
        QApplication.processEvents()


@pytest.mark.parametrize("color", ["night", "sepia"])
@pytest.mark.parametrize("mode", PAGE_MODES)
def test_recoloured_paper_only_inside_page_rects(qtbot, view, mode, color):
    """Paper-coloured pixels must lie on a shown page, never on the canvas around it.

    Guards against a recoloured band or placeholder painted at the wrong offset. Mixed
    page sizes make the two-page rows differ in width, so pages sit at different x.
    """
    from PySide6.QtCore import QRect

    view.resize(1100, 700)
    view.set_page_mode(mode)
    view.set_color_mode(color)
    view.fit_page()
    _settle(qtbot, view)
    img = view.viewport().grab().toImage()
    # Page rects in viewport pixels (not sceneBoundingRect, which includes the shadow).
    page_rects = []
    for p in view._pages:
        if not p.isVisible():
            continue
        top_left = view.mapFromScene(p.pos())
        w = round(p.page_rect.width() * view.zoom)
        h = round(p.page_rect.height() * view.zoom)
        page_rects.append(QRect(top_left.x() - 1, top_left.y() - 1, w + 3, h + 3))
    assert page_rects

    def is_paper(c):
        if color == "night":
            return max(c.red(), c.green(), c.blue()) <= 8
        return abs(c.red() - 246) <= 6 and abs(c.green() - 238) <= 6 and abs(c.blue() - 218) <= 6

    stray = []
    for y in range(0, img.height(), 5):
        for x in range(0, img.width(), 5):
            c = img.pixelColor(x, y)
            if is_paper(c) and not any(r.contains(x, y) for r in page_rects):
                stray.append((x, y))
    assert not stray, f"{len(stray)} paper pixels outside pages, e.g. {stray[:5]}"
