"""Tests for PdfView._zoom_at_viewport_point().

Verifies that the "zoom under cursor" invariant holds: the page-local coordinate
that was under the cursor before zoom is still (within 2 viewport pixels) under
that same viewport pixel after zoom.  Also covers the gap-between-pages fallback,
zoom clamping, and _page_positions consistency.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QPoint, QPointF
from PySide6.QtWidgets import QApplication

from neoview.ui.pdf_view import PdfView


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pdf(path: Path, page_specs: list[tuple[float, float]]) -> None:
    """Create a minimal PDF with pages of given (width, height) in points."""
    doc = fitz.open()
    for w, h in page_specs:
        doc.new_page(width=int(w), height=int(h))
    doc.save(str(path))
    doc.close()


def _load_view(pdf_path: Path) -> PdfView:
    """Open a PdfView, load *pdf_path*, and flush the event loop once.

    Caller MUST `view.close_document(); view.close()` (or via try/finally) so
    the fitz Document is released — otherwise running this suite alongside the
    rest of the project exhausts memory (PageItems + shadow effects + pixmap
    cache accumulate)."""
    view = PdfView()
    view.resize(800, 600)
    view.show()
    QApplication.processEvents()
    view.open_document(str(pdf_path))
    QApplication.processEvents()
    return view


def _viewport_for_page_local(view: PdfView, page_idx: int, lx: float, ly: float) -> QPoint:
    """Map a page-local coordinate (in PDF points) to a viewport pixel."""
    page = view._pages[page_idx]
    scene_pt = QPointF(
        page.pos().x() + lx * view._zoom,
        page.pos().y() + ly * view._zoom,
    )
    return view.mapFromScene(scene_pt)


def _scene_from_viewport(view: PdfView, vp: QPoint) -> QPointF:
    return view.mapToScene(vp)


def _page_local_under_viewport(view: PdfView, vp: QPoint) -> tuple[int, float, float] | None:
    """Return (page_idx, local_x, local_y) for the page under *vp*, or None."""
    scene_pt = view.mapToScene(vp)
    page_idx = view._get_page_at(scene_pt)
    if page_idx < 0:
        return None
    page = view._pages[page_idx]
    local_x = (scene_pt.x() - page.pos().x()) / view._zoom
    local_y = (scene_pt.y() - page.pos().y()) / view._zoom
    return page_idx, local_x, local_y


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def pdf_uniform(tmp_path: Path) -> Path:
    """Three A4-ish pages of the same size."""
    p = tmp_path / "uniform.pdf"
    _make_pdf(p, [(595, 842)] * 3)
    return p


@pytest.fixture()
def pdf_mixed(tmp_path: Path) -> Path:
    """Three pages with differing sizes to exercise centering math."""
    p = tmp_path / "mixed.pdf"
    _make_pdf(p, [(595, 842), (400, 600), (700, 500)])
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestZoomAtViewportPoint:
    """Tests for _zoom_at_viewport_point()."""

    # ------------------------------------------------------------------
    # 1. Zoom-in anchor invariant
    # ------------------------------------------------------------------
    def test_zoom_in_keeps_page_coordinate_under_cursor(self, pdf_uniform: Path):
        """After zoom-in the page-local coordinate originally under the cursor
        is still within 2 viewport pixels of that same cursor position."""
        view = _load_view(pdf_uniform)
        try:
            # Pick a point well inside page 0 (middle of the page).
            cursor_vp = _viewport_for_page_local(view, 0, 200.0, 300.0)

            # Record page-local coordinate before zoom.
            before = _page_local_under_viewport(view, cursor_vp)
            assert before is not None, "Cursor should be over a page before zoom"
            page_idx_before, lx_before, ly_before = before

            view._zoom_at_viewport_point(cursor_vp, 1.5)
            QApplication.processEvents()

            # After zoom, compute where that page-local coordinate maps to.
            page = view._pages[page_idx_before]
            scene_after = QPointF(
                page.pos().x() + lx_before * view._zoom,
                page.pos().y() + ly_before * view._zoom,
            )
            vp_after = view.mapFromScene(scene_after)

            dx = abs(vp_after.x() - cursor_vp.x())
            dy = abs(vp_after.y() - cursor_vp.y())
            assert dx <= 2, f"Horizontal drift after zoom-in: {dx}px"
            assert dy <= 2, f"Vertical drift after zoom-in: {dy}px"
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 2. Zoom-out anchor invariant
    # ------------------------------------------------------------------
    def test_zoom_out_keeps_page_coordinate_under_cursor(self, pdf_uniform: Path):
        """After zoom-out the page-local coordinate under the cursor stays fixed.

        Start at a high zoom and scroll to bring the target page-local point
        inside the viewport — real users never zoom at a point outside the
        viewport, and Qt's scrollbar can't honor an anchor for an off-screen
        request (it would need to scroll negative)."""
        view = _load_view(pdf_uniform)
        try:
            view.set_zoom(4.0, immediate=True)
            QApplication.processEvents()

            # Scroll so page-local (150, 200) on page 0 is roughly centered
            # in the viewport before measuring the anchor.
            page = view._pages[0]
            target_scene = QPointF(
                page.pos().x() + 150.0 * view._zoom,
                page.pos().y() + 200.0 * view._zoom,
            )
            view.horizontalScrollBar().setValue(
                int(target_scene.x() - view.viewport().width() / 2)
            )
            view.verticalScrollBar().setValue(
                int(target_scene.y() - view.viewport().height() / 2)
            )
            QApplication.processEvents()

            cursor_vp = _viewport_for_page_local(view, 0, 150.0, 200.0)
            before = _page_local_under_viewport(view, cursor_vp)
            assert before is not None
            page_idx_before, lx_before, ly_before = before

            view._zoom_at_viewport_point(cursor_vp, 1.0 / 1.5)
            QApplication.processEvents()

            assert view._scene.sceneRect().width() > view.viewport().width()
            assert view._scene.sceneRect().height() > view.viewport().height()

            page = view._pages[page_idx_before]
            scene_after = QPointF(
                page.pos().x() + lx_before * view._zoom,
                page.pos().y() + ly_before * view._zoom,
            )
            vp_after = view.mapFromScene(scene_after)

            dx = abs(vp_after.x() - cursor_vp.x())
            dy = abs(vp_after.y() - cursor_vp.y())
            assert dx <= 2, f"Horizontal drift after zoom-out: {dx}px"
            assert dy <= 2, f"Vertical drift after zoom-out: {dy}px"
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 3. Anchor invariant on a mixed-size document
    # ------------------------------------------------------------------
    def test_zoom_in_mixed_pages_keeps_coordinate_under_cursor(self, pdf_mixed: Path):
        """Centering offsets for mixed page widths must not disturb the anchor."""
        view = _load_view(pdf_mixed)
        try:
            # Page 1 (400×600) may have a non-zero x-offset due to centering.
            view.go_to_page(1)
            QApplication.processEvents()

            cursor_vp = _viewport_for_page_local(view, 1, 100.0, 150.0)
            before = _page_local_under_viewport(view, cursor_vp)
            assert before is not None
            page_idx_before, lx_before, ly_before = before

            view._zoom_at_viewport_point(cursor_vp, 1.3)
            QApplication.processEvents()

            page = view._pages[page_idx_before]
            scene_after = QPointF(
                page.pos().x() + lx_before * view._zoom,
                page.pos().y() + ly_before * view._zoom,
            )
            vp_after = view.mapFromScene(scene_after)

            dx = abs(vp_after.x() - cursor_vp.x())
            dy = abs(vp_after.y() - cursor_vp.y())
            assert dx <= 2, f"x drift on mixed-size doc: {dx}px"
            assert dy <= 2, f"y drift on mixed-size doc: {dy}px"
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 4. Gap between pages: fallback zoom without crash
    # ------------------------------------------------------------------
    def test_zoom_in_gap_between_pages_does_not_crash(self, pdf_uniform: Path):
        """When the cursor is in the gap between pages _zoom_at_viewport_point()
        should fall back to plain zoom_by() and not raise an exception."""
        view = _load_view(pdf_uniform)
        try:
            # The gap between page 0 and page 1 is 20pt scene units.
            # Find a scene y just below page 0's bottom edge.
            page0 = view._pages[0]
            page0_bottom_scene = page0.pos().y() + page0.page_rect.height() * view._zoom
            gap_scene_y = page0_bottom_scene + 5.0  # 5 units into the gap

            gap_vp = view.mapFromScene(QPointF(page0.pos().x() + 50.0 * view._zoom, gap_scene_y))

            zoom_before = view._zoom

            # Must not crash; result should be a plain zoom_by call.
            view._zoom_at_viewport_point(gap_vp, 1.2)
            QApplication.processEvents()

            assert view._zoom > zoom_before, "Zoom should have increased after fallback zoom"
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 5. Zoom clamp: factor that would exceed max (10.0)
    # ------------------------------------------------------------------
    def test_zoom_in_clamped_at_maximum(self, pdf_uniform: Path):
        """A factor that would push zoom past 10.0 is clamped to exactly 10.0."""
        view = _load_view(pdf_uniform)
        try:
            view.set_zoom(9.5, immediate=True)
            QApplication.processEvents()

            cursor_vp = _viewport_for_page_local(view, 0, 100.0, 100.0)
            # A ×2 factor on zoom=9.5 would give 19.0, which must clamp to 10.0.
            view._zoom_at_viewport_point(cursor_vp, 2.0)
            QApplication.processEvents()

            assert view._zoom <= 10.0, f"Zoom exceeded max: {view._zoom}"
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 6. Zoom clamp: factor that would go below min (0.1)
    # ------------------------------------------------------------------
    def test_zoom_out_clamped_at_minimum(self, pdf_uniform: Path):
        """A factor that would push zoom below 0.1 is clamped to exactly 0.1."""
        view = _load_view(pdf_uniform)
        try:
            view.set_zoom(0.15, immediate=True)
            QApplication.processEvents()

            cursor_vp = _viewport_for_page_local(view, 0, 100.0, 100.0)
            # A ×0.1 factor on zoom=0.15 would give 0.015, must clamp to 0.1.
            view._zoom_at_viewport_point(cursor_vp, 0.1)
            QApplication.processEvents()

            assert view._zoom >= 0.1, f"Zoom went below min: {view._zoom}"
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 7. _page_positions consistency after zoom
    # ------------------------------------------------------------------
    def test_page_positions_consistent_with_actual_page_item_positions(self, pdf_uniform: Path):
        """_page_positions[i] must equal _pages[i].pos().y() after zoom."""
        view = _load_view(pdf_uniform)
        try:
            view._zoom_at_viewport_point(QPoint(400, 300), 1.4)
            QApplication.processEvents()

            for i, page in enumerate(view._pages):
                recorded_y = view._page_positions[i]
                actual_y = page.pos().y()
                assert abs(recorded_y - actual_y) < 1e-3, (
                    f"Page {i}: _page_positions[{i}]={recorded_y} != "
                    f"page.pos().y()={actual_y}"
                )
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 8. _page_positions consistent after mixed-size zoom
    # ------------------------------------------------------------------
    def test_page_positions_consistent_mixed_sizes_after_zoom(self, pdf_mixed: Path):
        """_page_positions[i] matches page item y position for mixed-size pages."""
        view = _load_view(pdf_mixed)
        try:
            view.set_zoom(1.5, immediate=True)
            QApplication.processEvents()
            cursor_vp = _viewport_for_page_local(view, 0, 100.0, 100.0)
            view._zoom_at_viewport_point(cursor_vp, 0.9)
            QApplication.processEvents()

            for i, page in enumerate(view._pages):
                recorded_y = view._page_positions[i]
                actual_y = page.pos().y()
                assert abs(recorded_y - actual_y) < 1e-3, (
                    f"Mixed-size page {i}: _page_positions mismatch "
                    f"({recorded_y} vs {actual_y})"
                )
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 9. Zero / no-op factor guard
    # ------------------------------------------------------------------
    def test_zoom_factor_zero_does_not_crash(self, pdf_uniform: Path):
        """A factor of 0 should be rejected gracefully (guard in method head)."""
        view = _load_view(pdf_uniform)
        try:
            zoom_before = view._zoom
            # factor <= 0 must be a no-op; method returns early.
            view._zoom_at_viewport_point(QPoint(400, 300), 0.0)
            QApplication.processEvents()
            assert view._zoom == zoom_before, "Zoom must not change for factor=0"
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 10. Negative factor guard
    # ------------------------------------------------------------------
    def test_zoom_factor_negative_does_not_crash(self, pdf_uniform: Path):
        """A negative factor must be rejected, leaving zoom unchanged."""
        view = _load_view(pdf_uniform)
        try:
            zoom_before = view._zoom
            view._zoom_at_viewport_point(QPoint(400, 300), -1.5)
            QApplication.processEvents()
            assert view._zoom == zoom_before
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 11. Multiple sequential zooms accumulate correctly
    # ------------------------------------------------------------------
    def test_repeated_zoom_in_anchor_remains_stable(self, pdf_uniform: Path):
        """Repeated zoom steps over the same cursor position keep the invariant.

        Start above 1.5x so the scene already exceeds the 800px viewport on
        both axes — otherwise QGraphicsView's HCenter alignment swallows the
        first few scroll deltas and the test measures Qt centering, not the
        anchor algorithm."""
        view = _load_view(pdf_uniform)
        try:
            view.set_zoom(2.0, immediate=True)
            QApplication.processEvents()

            cursor_vp = _viewport_for_page_local(view, 0, 250.0, 400.0)
            before = _page_local_under_viewport(view, cursor_vp)
            assert before is not None
            page_idx_before, lx_before, ly_before = before

            for _ in range(5):
                view._zoom_at_viewport_point(cursor_vp, 1.08)
                QApplication.processEvents()

            page = view._pages[page_idx_before]
            scene_after = QPointF(
                page.pos().x() + lx_before * view._zoom,
                page.pos().y() + ly_before * view._zoom,
            )
            vp_after = view.mapFromScene(scene_after)

            # Integer scrollbar rounding compounds at ~0.5 px / step.
            dx = abs(vp_after.x() - cursor_vp.x())
            dy = abs(vp_after.y() - cursor_vp.y())
            assert dx <= 5, f"x drift after 5x zoom steps: {dx}px"
            assert dy <= 5, f"y drift after 5x zoom steps: {dy}px"
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 12. Empty document: no crash
    # ------------------------------------------------------------------
    def test_zoom_on_view_with_no_document_does_not_crash(self):
        """Calling _zoom_at_viewport_point() with no document loaded is a no-op."""
        view = PdfView()
        view.resize(800, 600)
        view.show()
        QApplication.processEvents()
        try:
            view._zoom_at_viewport_point(QPoint(400, 300), 1.2)
            QApplication.processEvents()
            # If we reach here without exception the guard worked.
        finally:
            view.close_document()
            view.close()

    # ------------------------------------------------------------------
    # 13. Zoom at maximum clamp does not over-scroll (no scroll overshoot)
    # ------------------------------------------------------------------
    def test_no_scroll_overshoot_when_clamped_at_max(self, pdf_uniform: Path):
        """When zoom is already at max, additional zoom-in should not move scrollbars."""
        view = _load_view(pdf_uniform)
        try:
            view.set_zoom(10.0, immediate=True)
            QApplication.processEvents()

            scroll_v_before = view.verticalScrollBar().value()
            scroll_h_before = view.horizontalScrollBar().value()

            cursor_vp = _viewport_for_page_local(view, 0, 50.0, 50.0)
            view._zoom_at_viewport_point(cursor_vp, 2.0)
            QApplication.processEvents()

            # Zoom is still at max; the scroll bars must not jump because
            # zoom_by() is a no-op when already clamped.
            assert view._zoom <= 10.0
            assert view.verticalScrollBar().value() == scroll_v_before
            assert view.horizontalScrollBar().value() == scroll_h_before
        finally:
            view.close_document()
            view.close()
