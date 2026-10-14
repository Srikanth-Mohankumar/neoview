"""Tests for the asynchronous, banded page render pipeline and the pixmap cache."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QApplication

from neoview.ui import render_scheduler
from neoview.ui.page_item import PageItem
from neoview.ui.pdf_view import PdfView
from neoview.ui.render_scheduler import RenderRequest, RenderScheduler, band_clips

PAGE_W, PAGE_H = 400, 600


def _make_pdf(path: Path, n_pages: int = 3, fill: tuple | None = None) -> None:
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_text((40, 60), f"page {i + 1}", fontsize=14)
        if fill is not None:
            page.draw_rect(fitz.Rect(0, 0, PAGE_W, PAGE_H), color=fill, fill=fill)
    doc.save(str(path))
    doc.close()


def _open_view(pdf: Path, qtbot) -> PdfView:
    view = PdfView()
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    QApplication.processEvents()
    assert view.open_document(str(pdf))
    return view


def _sharp(view: PdfView, idx: int = 0) -> bool:
    page = view._pages[idx]
    return (not page.is_preview and abs(page.render_zoom - view.zoom) < 0.01
            and view.pending_render_count() == 0)


def test_background_render_produces_sharp_pixmap(tmp_path, qtbot):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf)
    view = _open_view(pdf, qtbot)
    try:
        # Opening renders nothing synchronously: page 1 starts as a placeholder.
        assert view._pages[0].is_preview
        qtbot.waitUntil(lambda: _sharp(view), timeout=5000)
        page = view._pages[0]
        factor = page.render_scale_factor
        # The pixmap covers the page at zoom x factor device pixels (MuPDF rounds outward).
        assert page.pixmap().width() == pytest.approx(PAGE_W * view.zoom * factor, abs=2)
        assert page.pixmap().height() == pytest.approx(PAGE_H * view.zoom * factor, abs=2)
        # ...and is drawn at page size x zoom in scene units, as the placeholder was.
        drawn = page.mapRectToScene(QRectF(page.pixmap().rect()))
        assert drawn.width() == pytest.approx(PAGE_W * view.zoom, abs=2)
    finally:
        view.close_document()


def test_zoom_shows_scaled_preview_then_sharp(tmp_path, qtbot):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf)
    view = _open_view(pdf, qtbot)
    try:
        qtbot.waitUntil(lambda: _sharp(view), timeout=5000)
        view.set_zoom(view.zoom * 1.5)
        page = view._pages[0]
        # Immediately after the zoom the old render is shown, scaled to the new geometry.
        drawn = page.mapRectToScene(QRectF(page.pixmap().rect()))
        assert drawn.width() == pytest.approx(PAGE_W * view.zoom, abs=2)
        qtbot.waitUntil(lambda: _sharp(view), timeout=5000)
        assert page.render_zoom == pytest.approx(view.zoom, abs=0.01)
    finally:
        view.close_document()


def test_stale_generation_result_is_discarded(tmp_path, qtbot):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf)
    view = _open_view(pdf, qtbot)
    try:
        qtbot.waitUntil(lambda: _sharp(view), timeout=5000)
        page = view._pages[0]
        before = page.pixmap().cacheKey()
        junk = QImage(10, 10, QImage.Format.Format_RGB32)
        junk.fill(QColor("red"))
        view._on_page_rendered(0, view._render_generation - 1, view.zoom, 1.0, junk)
        assert page.pixmap().cacheKey() == before
    finally:
        view.close_document()


def test_renders_for_a_replaced_document_never_land(tmp_path, qtbot):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _make_pdf(first, n_pages=8)
    _make_pdf(second, n_pages=2)
    view = _open_view(first, qtbot)
    delivered: list[int] = []
    view._render_scheduler.page_rendered.connect(lambda _i, gen, *_a: delivered.append(gen))
    try:
        view._rerender_pages()  # queue renders for the first document
        assert view.pending_render_count() > 0
        assert view.open_document(str(second))
        final_generation = view._render_generation
        qtbot.waitUntil(lambda: _sharp(view), timeout=5000)
        assert delivered and set(delivered) == {final_generation}
    finally:
        view.close_document()


def test_close_document_while_render_in_flight(tmp_path, qtbot):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, n_pages=10)
    view = _open_view(pdf, qtbot)
    view.set_zoom(4.0, immediate=True)
    scheduler = view._render_scheduler
    # Run one slice so a job holds a live display list of the open document.
    scheduler._tick()
    assert scheduler._job is not None or scheduler.pending_count() > 0
    view.close_document()
    assert view.pending_render_count() == 0
    assert scheduler._job is None
    for _ in range(20):
        QApplication.processEvents()
    assert view.document is None


def test_close_view_with_pending_renders(tmp_path, qtbot):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, n_pages=10)
    view = PdfView()
    view.resize(800, 600)
    view.show()
    QApplication.processEvents()
    view.open_document(str(pdf))
    view.set_zoom(3.0, immediate=True)
    assert view.pending_render_count() > 0
    view.close_document()
    view.close()
    view.deleteLater()
    for _ in range(20):
        QApplication.processEvents()


def test_reload_invalidates_cache_and_shows_new_content(tmp_path, qtbot):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, n_pages=2)
    view = _open_view(pdf, qtbot)
    try:
        qtbot.waitUntil(lambda: _sharp(view), timeout=5000)
        old_token = view._doc_token
        assert any(k[0] == old_token for k in PageItem._PIXMAP_CACHE)
        centre = view._pages[0].pixmap().toImage().pixelColor(
            view._pages[0].pixmap().width() // 2, view._pages[0].pixmap().height() // 2)
        assert centre == QColor(255, 255, 255)

        _make_pdf(pdf, n_pages=2, fill=(1, 0, 0))  # same size, now solid red
        assert view.reload_document()
        assert not any(k[0] == old_token for k in PageItem._PIXMAP_CACHE)
        qtbot.waitUntil(lambda: _sharp(view), timeout=5000)
        pm = view._pages[0].pixmap()
        assert pm.toImage().pixelColor(pm.width() // 2, pm.height() // 2) == QColor(255, 0, 0)
    finally:
        view.close_document()


def test_far_pages_release_their_pixmaps(tmp_path, qtbot):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, n_pages=30)
    view = _open_view(pdf, qtbot)
    try:
        qtbot.waitUntil(lambda: _sharp(view), timeout=5000)
        assert not view._pages[0].is_blank
        view.last_page()
        QApplication.processEvents()
        view._rerender_pages()
        qtbot.waitUntil(lambda: _sharp(view, view.page_count - 1), timeout=5000)
        assert view._pages[0].is_blank
        far = [i for i in view._rendered_pages
               if i < view.page_count - 1 - 2 * PdfView.KEEP_RENDERED_PAGES - 2]
        assert far == []
    finally:
        view.close_document()


def _pixmap(w: int, h: int) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(QColor("white"))
    return pm


def test_cache_budget_evicts_least_recently_used(monkeypatch):
    one = PageItem._pixmap_bytes(_pixmap(100, 100))
    monkeypatch.setattr(PageItem, "CACHE_BUDGET_BYTES", 3 * one)
    PageItem._PIXMAP_CACHE.clear()
    for i in range(3):
        PageItem._cache_put(("t", i), _pixmap(100, 100))
    assert PageItem._cache_get(("t", 0)) is not None  # 0 is now most recently used
    PageItem._cache_put(("t", 3), _pixmap(100, 100))
    assert list(PageItem._PIXMAP_CACHE) == [("t", 2), ("t", 0), ("t", 3)]
    assert PageItem.cache_bytes() <= 3 * one


def test_cache_keeps_an_entry_larger_than_the_budget(monkeypatch):
    monkeypatch.setattr(PageItem, "CACHE_BUDGET_BYTES", 10)
    PageItem._PIXMAP_CACHE.clear()
    PageItem._cache_put(("t", 0), _pixmap(50, 50))
    PageItem._cache_put(("t", 1), _pixmap(50, 50))
    assert list(PageItem._PIXMAP_CACHE) == [("t", 1)]


def test_purge_cache_only_drops_one_document():
    PageItem._PIXMAP_CACHE.clear()
    PageItem._cache_put((1, 0, 1.0, 1.0), _pixmap(4, 4))
    PageItem._cache_put((2, 0, 1.0, 1.0), _pixmap(4, 4))
    PageItem.purge_cache(1)
    assert list(PageItem._PIXMAP_CACHE) == [(2, 0, 1.0, 1.0)]


def test_render_factor_follows_device_pixel_ratio_and_pixel_cap():
    rect = QRectF(0, 0, 595, 842)
    assert PageItem.render_factor_for(rect, 1.0, 1.0) == pytest.approx(1.0)
    assert PageItem.render_factor_for(rect, 1.0, 2.0) == pytest.approx(2.0)
    # At a huge zoom the factor drops so one page stays within MAX_RENDER_PIXELS.
    f = PageItem.render_factor_for(rect, 8.0, 2.0)
    assert 595 * 842 * (8.0 * f) ** 2 <= PageItem.MAX_RENDER_PIXELS * 1.01


def test_band_clips_tile_the_page_exactly():
    rect = fitz.Rect(0, 0, 595, 842)
    clips = band_clips(rect, 2.0, 100_000)
    assert 1 < len(clips) <= render_scheduler.MAX_BANDS
    assert clips[0].y0 == rect.y0 and clips[-1].y1 == rect.y1
    for a, b in zip(clips, clips[1:]):
        assert a.y1 == pytest.approx(b.y0)
        assert a.x0 == rect.x0 and a.x1 == rect.x1
    assert band_clips(rect, 0.1, 10_000_000) == [rect]


@pytest.mark.parametrize(
    ("width", "height", "rotation", "zoom", "cropbox"),
    [
        (PAGE_W, PAGE_H, 0, 1.37, None),
        (PAGE_W, PAGE_H, 90, 1.37, None),
        (433.7, 611.3, 0, 0.913, None),
        (433.7, 611.3, 270, 2.21, None),
        # Cropbox not at the origin: the page's pixel rect does not start at (0, 0).
        (PAGE_W, PAGE_H, 0, 1.13, (31.3, 47.9, 377.1, 571.7)),
    ],
)
def test_banded_render_matches_single_pass_render(
    tmp_path, monkeypatch, width, height, rotation, zoom, cropbox
):
    pdf = tmp_path / "doc.pdf"
    doc = fitz.open()
    page = doc.new_page(width=width, height=height)
    for k in range(40):
        page.draw_circle((50 + (k * 37) % 300, 40 + k * 13), 9, color=(0, 0, 1), fill=(1, 0, 0))
        page.insert_text((30, 20 + k * 14), f"line {k} of text", fontsize=10)
    if cropbox is not None:
        page.set_cropbox(fitz.Rect(*cropbox))
    page.set_rotation(rotation)
    doc.save(str(pdf))
    doc.close()

    monkeypatch.setattr(render_scheduler, "BAND_TARGET_PIXELS", 20_000)
    doc = fitz.open(str(pdf))
    try:
        got: list[QImage] = []
        scheduler = RenderScheduler()
        scheduler.page_rendered.connect(lambda _i, _g, _z, _f, img: got.append(img))
        scheduler.schedule([RenderRequest(0, doc[0], zoom, 1.0)], generation=1)
        while scheduler.pending_count():
            scheduler._tick()
        assert len(got) == 1
        ref_pix = doc[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        ref = QImage(ref_pix.samples, ref_pix.width, ref_pix.height, ref_pix.stride,
                     QImage.Format.Format_RGB888).convertToFormat(QImage.Format.Format_RGB32)
        assert (got[0].width(), got[0].height()) == (ref.width(), ref.height())
        assert got[0] == ref
    finally:
        doc.close()


def test_scheduler_replaces_queue_and_keeps_matching_job(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, n_pages=4)
    doc = fitz.open(str(pdf))
    try:
        scheduler = RenderScheduler()
        reqs = [RenderRequest(i, doc[i], 2.0, 1.0) for i in range(4)]
        scheduler.schedule(reqs, generation=1)
        scheduler._tick()
        current = scheduler._job.request.page_index if scheduler._job else None
        # A new request set without the current page cancels it; with it, keeps it.
        scheduler.schedule([RenderRequest(3, doc[3], 2.0, 1.0)], generation=1)
        if current != 3:
            assert scheduler._job is None or scheduler._job.request.page_index == 3
        assert scheduler.pending_count() == 1
        scheduler.cancel_all()
        assert scheduler.pending_count() == 0
    finally:
        doc.close()


def test_page_hit_shape_excludes_painted_shadow(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, n_pages=1)
    doc = fitz.open(str(pdf))
    try:
        item = PageItem(doc[0], 1.0, 0)
        pm_rect = QRectF(item.pixmap().rect())
        assert item.boundingRect().contains(pm_rect)
        assert item.boundingRect() != pm_rect  # room for the shadow
        assert not item.contains(QPointF(pm_rect.right() + 1, pm_rect.center().y()))
        assert item.contains(pm_rect.center())
        # No QGraphicsEffect per page: they made every paint re-render the page offscreen.
        assert item.graphicsEffect() is None
    finally:
        doc.close()
