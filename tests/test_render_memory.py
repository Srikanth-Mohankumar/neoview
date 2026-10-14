"""Scrolling a long document must not keep a full-resolution pixmap for every visited page.

Regression test for the "600+ page book hangs / runs out of memory" report: every PageItem
kept its last render forever and the cache was capped by entry count, not bytes. The
autouse fixture in conftest.py clears the shared cache after each test, so the leak has to
be caught inside one test that walks through many pages.
"""

from __future__ import annotations

from pathlib import Path

import fitz
from PySide6.QtWidgets import QApplication

from neoview.ui.page_item import PageItem
from neoview.ui.pdf_view import PdfView

N_PAGES = 40
PLACEHOLDER_EDGE = 64  # PageItem placeholders are 64 px on the long edge


def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    for i in range(N_PAGES):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"page {i + 1}", fontsize=14)
    doc.save(str(path))
    doc.close()


def _bytes(pixmap) -> int:
    return pixmap.width() * pixmap.height() * max(1, pixmap.depth()) // 8


def _full_res(view: PdfView) -> list[int]:
    return [
        i for i, p in enumerate(view._pages)
        if max(p.pixmap().width(), p.pixmap().height()) > PLACEHOLDER_EDGE
    ]


def test_scrolling_through_a_long_document_keeps_memory_bounded(tmp_path, qtbot, monkeypatch):
    pdf = tmp_path / "long.pdf"
    _make_pdf(pdf)
    view = PdfView()
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    QApplication.processEvents()
    assert view.open_document(str(pdf))
    view.fit_width()
    QApplication.processEvents()

    # One rendered page at this zoom, and a cache budget of six of them.
    page_px = 595 * view.zoom * 842 * view.zoom * view.devicePixelRatioF() ** 2
    page_bytes = int(page_px * 4)
    budget = 6 * page_bytes
    monkeypatch.setattr(PageItem, "CACHE_BUDGET_BYTES", budget, raising=False)

    # Visible pages (at most 2 at fit width in a 600 px viewport) plus the neighbours a
    # view may keep rendered on each side.
    keep = getattr(PdfView, "KEEP_RENDERED_PAGES", 4)
    max_full_res = 2 + 2 * keep

    pending = getattr(view, "pending_render_count", lambda: 0)
    try:
        for target in range(N_PAGES):
            view.go_to_page(target)
            QApplication.processEvents()
            view._rerender_pages()  # what the scroll timer does once scrolling pauses
            qtbot.waitUntil(lambda: pending() == 0, timeout=5000)
            held = _full_res(view)
            cache = sum(_bytes(p) for p in PageItem._PIXMAP_CACHE.values())
            assert len(held) <= max_full_res, (
                f"after visiting page {target + 1}: {len(held)} pages hold full-res pixmaps")
            assert cache <= budget, (
                f"after visiting page {target + 1}: cache holds {cache} bytes > {budget}")
        # The current page really is rendered, i.e. the bounds did not come from rendering
        # nothing at all.
        assert view.current_page in _full_res(view)
    finally:
        view.close_document()
    # Closing the only open document leaves nothing cached.
    assert sum(_bytes(p) for p in PageItem._PIXMAP_CACHE.values()) == 0


def test_close_document_empties_this_documents_cache(tmp_path, qtbot):
    pdf = tmp_path / "long.pdf"
    _make_pdf(pdf)
    view = PdfView()
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    QApplication.processEvents()
    assert view.open_document(str(pdf))
    for target in range(0, 12, 3):
        view.go_to_page(target)
        view._rerender_pages()
        qtbot.waitUntil(lambda: view.pending_render_count() == 0, timeout=5000)
    assert PageItem.cache_bytes() > 0
    view.close_document()
    assert PageItem.cache_bytes() == 0
    assert view._pages == []
