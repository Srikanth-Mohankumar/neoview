"""Opening and using a book-sized (650-page) PDF.

Regression tests for "opening a 600+ page book hung the viewer". The PDF is generated
once per module; each test opens it in a fresh MainWindow.
"""

from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from neoview.ui.main_window import MainWindow

PAGES = 650
NEEDLE = "zebracrossing"
NEEDLE_PAGE = 600  # 0-based
ANNOTATED_PAGES = list(range(5, PAGES, 65))  # 10 pages, one highlight each
LINK_PAGES = list(range(0, PAGES, 50))  # link annotations also live in /Annots
CHAPTER_EVERY = 5  # 130 chapters plus 65 sections -> 195 outline entries
LATE_CHAPTER = 128  # "Chapter 128" starts at page index 127 * 5 = 635

# Opening this PDF and getting the event loop back takes ~0.5 s on the machine the
# budget was set on (Intel Core Ultra 5 225U, offscreen). 10 s leaves ~20x headroom
# for slow CI runners while still catching a synchronous all-pages pass or a hang.
OPEN_BUDGET_S = 10.0


@pytest.fixture(scope="module")
def book_pdf(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("book") / "book650.pdf"
    doc = fitz.open()
    for i in range(PAGES):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"Chapter {i // CHAPTER_EVERY + 1} page {i + 1}", fontsize=14)
        body = f"{NEEDLE} appears here" if i == NEEDLE_PAGE else "Body text of the book"
        page.insert_text((72, 110), body, fontsize=11)
    toc = []
    for ch in range(PAGES // CHAPTER_EVERY):
        first = ch * CHAPTER_EVERY + 1  # 1-based for set_toc
        toc.append([1, f"Chapter {ch + 1}", first])
        if ch % 2 == 0:
            toc.append([2, f"Section {ch + 1}.1", first + 2])
    doc.set_toc(toc)
    for i in ANNOTATED_PAGES:
        doc[i].add_highlight_annot(fitz.Rect(72, 60, 300, 80))
    for i in LINK_PAGES:
        doc[i].insert_link(
            {"kind": fitz.LINK_GOTO, "from": fitz.Rect(72, 100, 200, 115), "page": PAGES - 1}
        )
    doc.save(str(path))
    doc.close()
    return path


def _window(qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1200, 850)
    win.show()
    QApplication.processEvents()
    return win


def _pump(n: int = 5) -> None:
    for _ in range(n):
        QApplication.processEvents()


def test_open_returns_to_event_loop_within_budget(book_pdf, qtbot):
    win = _window(qtbot)
    probe: list[float] = []

    start = time.perf_counter()
    win._open_file(str(book_pdf))
    QTimer.singleShot(0, lambda: probe.append(time.perf_counter()))
    qtbot.waitUntil(lambda: bool(probe), timeout=int(OPEN_BUDGET_S * 1000))

    assert win.current_view().page_count == PAGES
    assert probe[0] - start < OPEN_BUDGET_S


def test_open_only_loads_annotated_pages_for_native_annotations(book_pdf, qtbot, monkeypatch):
    calls: list[int] = []
    real_annots = fitz.Page.annots

    def counting_annots(page, *args, **kwargs):
        calls.append(page.number)
        return real_annots(page, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "annots", counting_annots)
    win = _window(qtbot)
    win._open_file(str(book_pdf))
    _pump()

    native = win.current_context().native_annotations
    assert sorted({a.page for a in native}) == ANNOTATED_PAGES
    assert all(a.type == "highlight" for a in native)
    # Pages without an /Annots entry must not be loaded and walked on the GUI thread.
    assert set(calls) <= set(ANNOTATED_PAGES) | set(LINK_PAGES)


def test_open_refreshes_outline_once(book_pdf, qtbot, monkeypatch):
    win = _window(qtbot)
    calls: list[int] = []
    real_populate = win._populate_outline

    def counting_populate():
        calls.append(1)
        real_populate()

    monkeypatch.setattr(win, "_populate_outline", counting_populate)
    win._open_file(str(book_pdf))
    _pump()

    assert len(calls) == 1
    root = win._outline_tree.topLevelItem(0)
    assert root.childCount() == len(win.current_view().document.get_toc())


def test_hidden_thumbnail_panel_builds_nothing_until_shown(book_pdf, qtbot):
    win = _window(qtbot)
    assert not win._thumbs_dock.isVisible()
    win._open_file(str(book_pdf))
    _pump()
    win.current_view().go_to_page(300)
    _pump()

    assert win._thumbs_list.count() == 0
    assert not win._thumb_icon_cache

    win._thumbs_dock.show()
    _pump()
    assert win._thumbs_list.count() == PAGES
    qtbot.waitUntil(lambda: len(win._thumb_icon_cache) > 0, timeout=5000)


def test_last_page_and_late_outline_jump(book_pdf, qtbot):
    win = _window(qtbot)
    win._open_file(str(book_pdf))
    _pump()
    view = win.current_view()

    view.last_page()
    _pump()
    assert view.current_page == PAGES - 1

    root = win._outline_tree.topLevelItem(0)
    target = next(
        root.child(i)
        for i in range(root.childCount())
        if root.child(i).text(0).strip() == f"Chapter {LATE_CHAPTER}"
    )
    view.first_page()
    _pump()
    win._jump_to_outline_item(target)
    _pump()
    assert view.current_page == (LATE_CHAPTER - 1) * CHAPTER_EVERY


def test_outline_sync_selects_last_entry_at_or_before_page(book_pdf, qtbot):
    win = _window(qtbot)
    win._open_file(str(book_pdf))
    _pump()

    # Chapter 127 starts at 630, its section 127.1 at 632, chapter 128 at 635.
    win._sync_outline_current_page(634)
    assert win._outline_tree.currentItem().text(0).strip() == "Section 127.1"
    win._sync_outline_current_page(635)
    assert win._outline_tree.currentItem().text(0).strip() == f"Chapter {LATE_CHAPTER}"
    win._sync_outline_current_page(PAGES - 1)
    assert win._outline_tree.currentItem().text(0).strip() == "Chapter 130"


def test_search_finds_term_on_late_page(book_pdf, qtbot):
    win = _window(qtbot)
    win._open_file(str(book_pdf))
    _pump()

    win._search_input.setText(NEEDLE)
    win._execute_search_current()
    qtbot.waitUntil(lambda: win._search_operation is None, timeout=15000)

    pages = [m.page_idx for m in win.current_context().search_results]
    assert pages == [NEEDLE_PAGE]


def test_close_while_background_work_pending(book_pdf, qtbot):
    win = _window(qtbot)
    win._thumbs_dock.show()
    win._open_file(str(book_pdf))
    win._search_input.setText(NEEDLE)
    win._execute_search_current()
    assert win._thumb_timer.isActive() or win._thumb_queue
    assert win._search_operation is not None

    win.close()
    _pump(20)

    assert win._search_operation is None
    assert not win._thumb_timer.isActive()
    assert win.current_view().document is None
