"""PdfView back/forward history: which navigation records, and restoring entries."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from neoview.ui.pdf_view import PdfView

PAGE_W, PAGE_H = 400.0, 500.0


def _make_pdf(path: Path, n_pages: int = 8) -> Path:
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        page.insert_text((40, 60), f"page {i + 1} target")
    # A GoTo link on page 1 to page 6 (or the last page of a short document).
    doc[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(40, 100, 200, 130),
                        "page": min(5, n_pages - 1), "to": fitz.Point(0, 0)})
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def view(qtbot, tmp_path):
    v = PdfView()
    qtbot.addWidget(v)
    v.resize(500, 400)
    v.show()
    assert v.open_document(str(_make_pdf(tmp_path / "doc.pdf")))
    v.set_zoom(1.0, immediate=True)
    QApplication.processEvents()
    yield v
    v.close_document()


def _top_page(view: PdfView) -> int:
    loc = view._current_location()
    return loc.page_index


def test_fresh_document_has_no_history(view):
    assert not view.can_go_back()
    assert not view.can_go_forward()
    assert view.go_back() is False
    assert view.go_forward() is False


def test_go_to_page_records_and_back_forward_restore(qtbot, view):
    seen = []
    view.history_changed.connect(lambda b, f: seen.append((b, f)))
    view.go_to_page(4)
    assert _top_page(view) == 4
    assert view.can_go_back() and not view.can_go_forward()
    assert seen[-1] == (True, False)

    assert view.go_back() is True
    assert _top_page(view) == 0
    assert view.can_go_forward()
    assert seen[-1] == (False, True)

    assert view.go_forward() is True
    assert _top_page(view) == 4
    assert seen[-1] == (True, False)


def test_next_and_previous_page_do_not_record(view):
    view.next_page()
    view.next_page()
    view.prev_page()
    assert not view.can_go_back()


def test_first_last_page_record(view):
    view.last_page()
    assert view.can_go_back()
    view.first_page()
    view.go_back()
    assert _top_page(view) == view.page_count - 1 or view.verticalScrollBar().value() == (
        view.verticalScrollBar().maximum()
    )


def test_restore_never_pushes(view):
    view.go_to_page(3)
    view.go_to_page(6)
    entries_before = view._history.entries()
    view.go_back()
    view.go_back()
    view.go_forward()
    # Same number of entries: restoring only moves the cursor.
    assert len(view._history.entries()) == len(entries_before)


def test_jump_to_same_place_records_nothing(view):
    view.go_to_page(3)
    count = len(view._history)
    view.go_to_page(3)
    assert len(view._history) == count


def test_back_returns_to_where_the_user_scrolled(view):
    view.go_to_page(2)
    bar = view.verticalScrollBar()
    bar.setValue(bar.value() + 120)  # user scrolls within page 3
    scrolled = bar.value()
    view.go_to_page(6)
    view.go_back()
    assert bar.value() == pytest.approx(scrolled, abs=1)


def test_back_restores_zoom(view):
    view.go_to_page(2)
    view.set_zoom(2.0, immediate=True)
    before_jump = view._current_location()
    view.go_to_page(5)
    view.set_zoom(1.0, immediate=True)
    left_from = view._current_location()
    view.go_back()  # the location the page-6 jump started from, at 200%
    assert view.zoom == pytest.approx(2.0)
    assert view._current_location().same_place(before_jump)
    view.go_forward()  # where the user left from, at 100%
    assert view.zoom == pytest.approx(1.0)
    assert view._current_location().same_place(left_from)


def test_link_click_records(view):
    links = view._links_for_page(0)
    assert links, "test PDF should have a link on page 1"
    rect, link = links[0]
    view._activate_link({"link": link, "page": 0, "rect": rect})
    assert view.current_page == 5  # destinations land a little above the target
    assert view.can_go_back()
    view.go_back()
    assert _top_page(view) == 0


def test_search_and_bookmark_jumps_record(view):
    view.scroll_to_rect(4, fitz.Rect(40, 200, 100, 220))
    assert view.can_go_back()
    view.scroll_to_page_y(7, 0.0)
    view.go_back()
    loc = view._current_location()
    assert loc.page_index in (3, 4)  # rect is placed 40px below the viewport top
    view.go_back()
    assert _top_page(view) == 0


def test_new_push_after_back_drops_forward(view):
    view.go_to_page(3)
    view.go_back()
    assert view.can_go_forward()
    view.go_to_page(6)
    assert not view.can_go_forward()


def test_open_document_clears_history(view, tmp_path):
    view.go_to_page(4)
    assert view.can_go_back()
    assert view.open_document(str(_make_pdf(tmp_path / "other.pdf", 3)))
    assert not view.can_go_back()


def test_reload_keeps_history_and_clamps(view, tmp_path):
    view.go_to_page(7)
    path = view.doc_path
    _make_pdf(Path(path), 3)
    assert view.reload_document()
    QApplication.processEvents()
    assert view.can_go_back()
    view.go_back()  # back to page 1: still exists
    assert _top_page(view) == 0
    view.go_forward()  # page 8 no longer exists: clamped to the last page
    assert _top_page(view) <= 2
