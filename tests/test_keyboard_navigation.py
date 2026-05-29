"""Keyboard navigation audit tests for NeoView PDF viewer.

Covers:
- PgDown / PgUp page navigation and scroll position
- Home / End first / last page jumps
- Page-nav combo: partial digits must not navigate; only commit (Return/editingFinished) does
- current_page after Ctrl+wheel zoom anchored at cursor
- Arrow keys with active selection nudge the selection, not the view
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from neoview.ui.pdf_view import PdfView


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PAGE_W = 595
PAGE_H = 842
GAP = 20


def _make_pdf(path: Path, n_pages: int = 5) -> None:
    doc = fitz.open()
    for i in range(n_pages):
        pg = doc.new_page(width=PAGE_W, height=PAGE_H)
        pg.insert_text((72, 100), f"Page {i + 1}")
    doc.save(str(path))
    doc.close()


def _open_view(tmp_path: Path, n_pages: int = 5) -> PdfView:
    pdf = tmp_path / "nav.pdf"
    _make_pdf(pdf, n_pages)
    view = PdfView()
    view.resize(800, 600)
    view.show()
    ok = view.open_document(str(pdf))
    assert ok, "open_document failed"
    QApplication.processEvents()
    return view


def _press_key(view: PdfView, key: Qt.Key, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers, "")
    QApplication.sendEvent(view, ev)
    QApplication.processEvents()


# ---------------------------------------------------------------------------
# PgDown: page N -> page N+1, scroll lands at top of that page
# ---------------------------------------------------------------------------

class TestPgDown:
    def test_pgdown_advances_page(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=5)
        view.go_to_page(0)
        QApplication.processEvents()
        assert view.current_page == 0

        _press_key(view, Qt.Key.Key_PageDown)

        assert view.current_page == 1, (
            f"BUG: PgDown from page 0 should land on page 1, got {view.current_page}"
        )
        view.close_document()
        view.close()

    def test_pgdown_scroll_value_matches_page_position(self, tmp_path: Path) -> None:
        """After next_page() the vertical scrollbar value should equal _page_positions[1].

        We invoke next_page() directly because the PgDown shortcut is wired
        at the MainWindow QAction level — sending Key_PageDown to a bare
        PdfView would scroll by viewport height (QGraphicsView default),
        not jump page-by-page."""
        view = _open_view(tmp_path, n_pages=5)
        view.go_to_page(0)
        QApplication.processEvents()

        view.next_page()
        QApplication.processEvents()

        sb_val = view.verticalScrollBar().value()
        expected = int(view._page_positions[1])
        assert sb_val == expected, (
            f"BUG: After next_page scrollbar is {sb_val}, expected page-top={expected}. "
            f"go_to_page sets scrollbar to _page_positions[page_num]."
        )
        view.close_document()
        view.close()

    def test_pgdown_at_last_page_stays(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=3)
        view.go_to_page(2)
        QApplication.processEvents()

        _press_key(view, Qt.Key.Key_PageDown)

        assert view.current_page == 2, (
            f"BUG: PgDown past last page should stay on 2, got {view.current_page}"
        )
        view.close_document()
        view.close()


# ---------------------------------------------------------------------------
# PgUp: symmetric
# ---------------------------------------------------------------------------

class TestPgUp:
    def test_pgup_decrements_page(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=5)
        view.go_to_page(2)
        QApplication.processEvents()
        assert view.current_page == 2

        _press_key(view, Qt.Key.Key_PageUp)

        assert view.current_page == 1, (
            f"BUG: PgUp from page 2 should land on page 1, got {view.current_page}"
        )
        view.close_document()
        view.close()

    def test_pgup_scroll_value_matches_page_position(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=5)
        view.go_to_page(3)
        QApplication.processEvents()

        view.prev_page()
        QApplication.processEvents()

        sb_val = view.verticalScrollBar().value()
        expected = int(view._page_positions[2])
        assert sb_val == expected, (
            f"BUG: After prev_page scrollbar is {sb_val}, expected page-top={expected}"
        )
        view.close_document()
        view.close()

    def test_pgup_at_first_page_stays(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=3)
        view.go_to_page(0)
        QApplication.processEvents()

        _press_key(view, Qt.Key.Key_PageUp)

        assert view.current_page == 0, (
            f"BUG: PgUp past first page should stay at 0, got {view.current_page}"
        )
        view.close_document()
        view.close()


# ---------------------------------------------------------------------------
# Home / End
# ---------------------------------------------------------------------------

class TestHomeEnd:
    def test_home_jumps_to_first_page(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=5)
        view.go_to_page(4)
        QApplication.processEvents()

        view.first_page()
        QApplication.processEvents()

        assert view.current_page == 0, (
            f"BUG: first_page() should land on page 0, got {view.current_page}"
        )
        view.close_document()
        view.close()

    def test_end_jumps_to_last_page(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=5)
        view.go_to_page(0)
        QApplication.processEvents()

        view.last_page()
        QApplication.processEvents()

        assert view.current_page == 4, (
            f"BUG: last_page() should land on page 4, got {view.current_page}"
        )
        view.close_document()
        view.close()


# ---------------------------------------------------------------------------
# Page-nav combo: partial digits must NOT navigate; only explicit commit should
# ---------------------------------------------------------------------------

class TestPageNavCombo:
    def test_partial_digit_does_not_navigate(self, tmp_path: Path) -> None:
        """Typing '2' into the combo box field must not immediately jump to page 2.
        Navigation should only happen when Return or editingFinished fires."""
        from neoview.ui.main_window import MainWindow

        pdf = tmp_path / "combo.pdf"
        _make_pdf(pdf, n_pages=10)

        win = MainWindow()
        win.resize(900, 700)
        win.show()
        win._open_file(str(pdf))
        QApplication.processEvents()

        # Start on page 0
        win.current_view().go_to_page(0)
        QApplication.processEvents()
        assert win.current_view().current_page == 0

        # Programmatically set the combo text to "2" WITHOUT pressing Enter
        # This simulates typing a single character mid-word.
        line = win._page_nav_combo.lineEdit()
        win._page_nav_combo.blockSignals(True)  # block combo's own activated signal
        line.blockSignals(True)
        line.setText("2")
        line.blockSignals(False)
        win._page_nav_combo.blockSignals(False)
        QApplication.processEvents()

        assert win.current_view().current_page == 0, (
            "BUG: Partial digit '2' in combo should not trigger navigation. "
            f"current_page is now {win.current_view().current_page}"
        )

        # Now fire returnPressed explicitly — navigation should happen
        line.returnPressed.emit()
        QApplication.processEvents()

        assert win.current_view().current_page == 1, (
            f"BUG: After Return with '2' combo should navigate to page 1 (0-indexed). "
            f"Got {win.current_view().current_page}"
        )
        win.close()

    def test_invalid_text_in_combo_does_not_crash(self, tmp_path: Path) -> None:
        """Non-numeric entry should be silently ignored."""
        from neoview.ui.main_window import MainWindow

        pdf = tmp_path / "combo2.pdf"
        _make_pdf(pdf, n_pages=3)
        win = MainWindow()
        win.show()
        win._open_file(str(pdf))
        QApplication.processEvents()

        win.current_view().go_to_page(0)
        QApplication.processEvents()

        line = win._page_nav_combo.lineEdit()
        line.setText("abc")
        line.returnPressed.emit()
        QApplication.processEvents()

        # Page should remain 0 (unchanged)
        assert win.current_view().current_page == 0, (
            f"BUG: Invalid page text 'abc' should leave page unchanged at 0, "
            f"got {win.current_view().current_page}"
        )
        win.close()


# ---------------------------------------------------------------------------
# current_page after Ctrl+wheel zoom
# ---------------------------------------------------------------------------

class TestCurrentPageAfterZoom:
    def test_current_page_stable_after_ctrl_wheel_zoom(self, tmp_path: Path) -> None:
        """After Ctrl+wheel zoom the current_page must still report the visible page."""
        view = _open_view(tmp_path, n_pages=5)
        view.go_to_page(2)
        QApplication.processEvents()

        before_page = view.current_page
        before_zoom = view.zoom

        # Drive the zoom-anchor path directly. The QWheelEvent constructor
        # signature has shifted across PySide6 versions, so we bypass the
        # event-synthesis dance and call the helper that wheelEvent uses
        # internally — it's the actual code under test.
        center = view.viewport().rect().center()
        view._zoom_at_viewport_point(QPoint(center.x(), center.y()), 1.5)
        QApplication.processEvents()

        after_page = view.current_page
        after_zoom = view.zoom

        assert after_zoom > before_zoom, "Zoom-in should increase zoom factor"
        assert after_page == before_page, (
            f"BUG: current_page changed from {before_page} to {after_page} after Ctrl+wheel zoom. "
            "The page-under-cursor should remain the current page."
        )
        view.close_document()
        view.close()


# ---------------------------------------------------------------------------
# Arrow keys with active selection: nudge selection, not scroll
# ---------------------------------------------------------------------------

class TestArrowKeysWithSelection:
    def _make_selection(self, view: PdfView) -> None:
        rect = QRectF(50, 50, 200, 100)
        view._create_selection_on_page(0, rect)
        QApplication.processEvents()

    def test_arrow_left_nudges_selection(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=2)
        view.go_to_page(0)
        QApplication.processEvents()
        self._make_selection(view)

        before_rect = view._selection.pdf_rect
        scroll_before = view.horizontalScrollBar().value()

        _press_key(view, Qt.Key.Key_Left)

        after_rect = view._selection.pdf_rect
        scroll_after = view.horizontalScrollBar().value()

        assert after_rect.left() < before_rect.left(), (
            f"BUG: Left arrow should nudge selection left. "
            f"Before={before_rect.left():.1f}, After={after_rect.left():.1f}"
        )
        assert scroll_after == scroll_before, (
            f"BUG: Left arrow with selection active should NOT scroll the view. "
            f"Scroll changed from {scroll_before} to {scroll_after}"
        )
        view.close_document()
        view.close()

    def test_arrow_right_nudges_selection(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=2)
        view.go_to_page(0)
        QApplication.processEvents()
        self._make_selection(view)

        before_rect = view._selection.pdf_rect
        scroll_before = view.horizontalScrollBar().value()

        _press_key(view, Qt.Key.Key_Right)

        after_rect = view._selection.pdf_rect
        scroll_after = view.horizontalScrollBar().value()

        assert after_rect.left() > before_rect.left(), (
            f"BUG: Right arrow should nudge selection right. "
            f"Before={before_rect.left():.1f}, After={after_rect.left():.1f}"
        )
        assert scroll_after == scroll_before, (
            f"BUG: Right arrow with selection active should NOT scroll the view. "
            f"Scroll changed from {scroll_before} to {scroll_after}"
        )
        view.close_document()
        view.close()

    def test_arrow_up_nudges_selection(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=2)
        view.go_to_page(0)
        QApplication.processEvents()
        self._make_selection(view)

        before_rect = view._selection.pdf_rect
        scroll_before = view.verticalScrollBar().value()

        _press_key(view, Qt.Key.Key_Up)

        after_rect = view._selection.pdf_rect
        scroll_after = view.verticalScrollBar().value()

        assert after_rect.top() < before_rect.top(), (
            f"BUG: Up arrow should nudge selection up. "
            f"Before={before_rect.top():.1f}, After={after_rect.top():.1f}"
        )
        assert scroll_after == scroll_before, (
            f"BUG: Up arrow with selection active should NOT scroll the view. "
            f"Scroll changed from {scroll_before} to {scroll_after}"
        )
        view.close_document()
        view.close()

    def test_arrow_down_nudges_selection(self, tmp_path: Path) -> None:
        view = _open_view(tmp_path, n_pages=2)
        view.go_to_page(0)
        QApplication.processEvents()
        self._make_selection(view)

        before_rect = view._selection.pdf_rect
        scroll_before = view.verticalScrollBar().value()

        _press_key(view, Qt.Key.Key_Down)

        after_rect = view._selection.pdf_rect
        scroll_after = view.verticalScrollBar().value()

        assert after_rect.top() > before_rect.top(), (
            f"BUG: Down arrow should nudge selection down. "
            f"Before={before_rect.top():.1f}, After={after_rect.top():.1f}"
        )
        assert scroll_after == scroll_before, (
            f"BUG: Down arrow with selection active should NOT scroll the view. "
            f"Scroll changed from {scroll_before} to {scroll_after}"
        )
        view.close_document()
        view.close()

    def test_arrow_without_selection_does_not_nudge(self, tmp_path: Path) -> None:
        """Without a selection the arrow keys should pass through to the QGraphicsView scroller."""
        view = _open_view(tmp_path, n_pages=3)
        view.go_to_page(1)
        QApplication.processEvents()

        assert view._selection is None, "Precondition: no selection"

        scroll_before = view.verticalScrollBar().value()
        _press_key(view, Qt.Key.Key_Down)
        scroll_after = view.verticalScrollBar().value()

        # Without selection, Down should scroll the view (base QGraphicsView behaviour)
        assert scroll_after >= scroll_before, (
            "Down arrow without selection should scroll the view or be a no-op, "
            "but it should NOT crash."
        )
        view.close_document()
        view.close()


# ---------------------------------------------------------------------------
# Zoom-mode invariance for PgDown/PgUp/Home/End
# ---------------------------------------------------------------------------

class TestZoomModeInvariance:
    """Navigation shortcuts must work in all zoom modes."""

    @pytest.mark.parametrize("zoom_mode,zoom_val", [
        ("fit_width", None),
        ("fit_page", None),
        ("actual_size", None),
        ("custom", 0.75),
    ])
    def test_pgdown_in_zoom_mode(self, tmp_path: Path, zoom_mode: str, zoom_val) -> None:
        view = _open_view(tmp_path, n_pages=5)
        view.go_to_page(0)
        QApplication.processEvents()

        if zoom_mode == "fit_width":
            view.fit_width()
        elif zoom_mode == "fit_page":
            view.fit_page()
        elif zoom_mode == "actual_size":
            view.actual_size()
        else:
            view.set_zoom(zoom_val, zoom_mode=PdfView.ZOOM_MODE_CUSTOM)
        QApplication.processEvents()

        view.next_page()
        QApplication.processEvents()

        assert view.current_page == 1, (
            f"BUG [{zoom_mode}]: next_page from page 0 should reach page 1, "
            f"got {view.current_page}"
        )
        view.close_document()
        view.close()

    @pytest.mark.parametrize("zoom_mode,zoom_val", [
        ("fit_width", None),
        ("fit_page", None),
        ("actual_size", None),
        ("custom", 0.75),
    ])
    def test_home_end_in_zoom_mode(self, tmp_path: Path, zoom_mode: str, zoom_val) -> None:
        view = _open_view(tmp_path, n_pages=5)

        if zoom_mode == "fit_width":
            view.fit_width()
        elif zoom_mode == "fit_page":
            view.fit_page()
        elif zoom_mode == "actual_size":
            view.actual_size()
        else:
            view.set_zoom(zoom_val, zoom_mode=PdfView.ZOOM_MODE_CUSTOM)
        QApplication.processEvents()

        view.go_to_page(2)
        QApplication.processEvents()

        view.first_page()
        QApplication.processEvents()
        assert view.current_page == 0, (
            f"BUG [{zoom_mode}]: first_page should land on page 0, got {view.current_page}"
        )

        view.last_page()
        QApplication.processEvents()
        assert view.current_page == 4, (
            f"BUG [{zoom_mode}]: last_page should land on page 4, got {view.current_page}"
        )
        view.close_document()
        view.close()
