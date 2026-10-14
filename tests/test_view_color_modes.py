"""PdfView reading colour modes: applied to rendered pages, keyed in the pixmap cache."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from neoview import theme
from neoview.ui.page_item import PageItem
from neoview.ui.pdf_view import PdfView


def _make_pdf(path: Path, n_pages: int = 6) -> Path:
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=300, height=400)
        # Mostly white paper with black text and a red bar near the bottom.
        page.insert_text((30, 50), f"page {i + 1}", fontsize=24)
        page.draw_rect(fitz.Rect(30, 330, 270, 370), color=(1, 0, 0), fill=(1, 0, 0))
    # Overwrite in place, like a TeX rebuild: Windows refuses to delete (what doc.save does)
    # a file the viewer still has open.
    Path(path).write_bytes(doc.tobytes())
    doc.close()
    return path


@pytest.fixture
def view(qtbot, tmp_path):
    v = PdfView()
    qtbot.addWidget(v)
    v.resize(500, 450)
    v.show()
    assert v.open_document(str(_make_pdf(tmp_path / "doc.pdf")))
    v.set_zoom(1.0, immediate=True)
    _wait_sharp(qtbot, v)
    yield v
    v.close_document()


def _wait_sharp(qtbot, view):
    def sharp():
        QApplication.processEvents()
        if view.pending_render_count():
            return False
        for idx in view._visible_page_indices():
            page = view._pages[idx]
            if page.needs_render(view.zoom, view._render_factor(page)):
                return False
        return True

    qtbot.waitUntil(sharp, timeout=5000)


def _paper(page: PageItem) -> QColor:
    """Colour of blank paper near the page's top-right corner."""
    img = page.pixmap().toImage()
    return img.pixelColor(int(img.width() * 0.9), int(img.height() * 0.3))


def _red_bar(page: PageItem) -> QColor:
    img = page.pixmap().toImage()
    return img.pixelColor(img.width() // 2, int(img.height() * 350 / 400))


def test_default_and_validation(view):
    assert view.color_mode() == "normal"
    with pytest.raises(ValueError):
        view.set_color_mode("neon")


def test_signal_emitted_once(view):
    seen = []
    view.color_mode_changed.connect(seen.append)
    view.set_color_mode("sepia")
    view.set_color_mode("sepia")
    assert seen == ["sepia"]


def test_normal_pages_are_white(view):
    paper = _paper(view._pages[0])
    assert min(paper.red(), paper.green(), paper.blue()) >= 250


def test_night_mode_darkens_paper_and_keeps_red(qtbot, view):
    view.set_color_mode("night")
    _wait_sharp(qtbot, view)
    page = view._pages[0]
    assert page.rendered_color_mode == "night"
    paper = _paper(page)
    assert max(paper.red(), paper.green(), paper.blue()) <= 5
    red = _red_bar(page)
    assert red.red() > 150 and red.red() > red.green() + 80  # still red, not cyan


def test_sepia_mode_warms_paper(qtbot, view):
    view.set_color_mode("sepia")
    _wait_sharp(qtbot, view)
    paper = _paper(view._pages[0])
    assert paper.red() > paper.blue() + 15
    assert paper.red() > 200


def test_color_mode_is_part_of_cache_key(qtbot, view):
    view.set_color_mode("night")
    _wait_sharp(qtbot, view)
    modes = {key[4] for key in PageItem._PIXMAP_CACHE}
    assert {"normal", "night"} <= modes
    # Switching back reuses the cached normal renders at once: nothing to wait for.
    view.set_color_mode("normal")
    for idx in view._visible_page_indices():
        page = view._pages[idx]
        assert page.rendered_color_mode == "normal"
        assert not page.is_preview
    assert min(_paper(view._pages[0]).getRgb()[:3]) >= 250


def test_placeholders_use_mode_paper_colour(view):
    view.set_color_mode("night")
    far = view._pages[-1]
    far.release(view.zoom)
    assert far.is_blank
    color = far.pixmap().toImage().pixelColor(1, 1)
    assert max(color.red(), color.green(), color.blue()) <= 5


def test_night_canvas_is_dark(view):
    light_canvas = QColor(theme.tokens()["canvas"])
    view.set_color_mode("night")
    canvas = view.backgroundBrush().color()
    assert canvas == QColor(theme.tokens("dark")["canvas"])
    assert canvas.lightness() < 80
    view.set_color_mode("normal")
    assert view.backgroundBrush().color() == light_canvas


def test_reload_keeps_color_mode(qtbot, view):
    view.set_color_mode("night")
    _make_pdf(Path(view.doc_path), 4)
    assert view.reload_document()
    _wait_sharp(qtbot, view)
    assert view.color_mode() == "night"
    assert all(p.color_mode == "night" for p in view._pages)
    assert max(_paper(view._pages[0]).getRgb()[:3]) <= 5


def test_cache_stays_within_byte_budget(qtbot, view, monkeypatch):
    one_page = PageItem._pixmap_bytes(view._pages[0].pixmap())
    monkeypatch.setattr(PageItem, "CACHE_BUDGET_BYTES", 3 * one_page)
    for mode in ("night", "sepia", "normal", "night"):
        view.set_color_mode(mode)
        _wait_sharp(qtbot, view)
        assert PageItem.cache_bytes() <= 3 * one_page
