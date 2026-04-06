import os
from pathlib import Path

import fitz
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from neoview.persistence.sidecar_store import load_sidecar
from neoview.ui.main_window import MainWindow


def _create_pdf(path: Path, pages: int = 1, text_prefix: str = "Page"):
    doc = fitz.open()
    for idx in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 120), f"{text_prefix} {idx + 1} sample text search-target")
    doc.save(str(path))
    doc.close()


def _rewrite_pdf_for_reload(win: MainWindow, path: Path, pages: int, text_prefix: str) -> None:
    # Windows does not allow overwriting the same PDF while PyMuPDF still has it open.
    if os.name == "nt":
        view = win.current_view()
        if view._doc is not None:
            view._doc.close()
            view._doc = None
    _create_pdf(path, pages=pages, text_prefix=text_prefix)


def test_open_file_reuses_existing_tab(tmp_path: Path):
    pdf = tmp_path / "sample.pdf"
    _create_pdf(pdf, pages=2)

    win = MainWindow()
    win._open_file(str(pdf))
    QApplication.processEvents()
    assert win._tabs.count() == 1

    win._open_file(str(pdf))
    QApplication.processEvents()
    assert win._tabs.count() == 1
    assert win.current_context().file_path == str(pdf)
    win.close()


def test_add_bookmark_saves_to_sidecar(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "bookmarks.pdf"
    _create_pdf(pdf, pages=2)

    win = MainWindow()
    win._open_file(str(pdf))
    QApplication.processEvents()

    monkeypatch.setattr(
        "neoview.ui.main_window.QInputDialog.getText",
        lambda *_args, **_kwargs: ("MyMark", True),
    )

    win._add_bookmark()
    win._save_sidecar_for_view(win.current_view())

    state = load_sidecar(str(pdf))
    assert len(state.bookmarks) == 1
    assert state.bookmarks[0].title == "MyMark"
    win.close()


def test_search_panel_builds_snippet_results(tmp_path: Path):
    pdf = tmp_path / "search.pdf"
    _create_pdf(pdf, pages=2, text_prefix="Findable")

    win = MainWindow()
    win._open_file(str(pdf))
    QApplication.processEvents()

    win._search_input.setText("search-target")
    win._execute_search_current()
    QApplication.processEvents()

    assert len(win.current_context().search_results) >= 2
    assert win._search_results_list.count() >= 2
    first = win._search_results_list.item(0).text().lower()
    assert "search-target" in first
    win.close()


def test_live_search_waits_for_two_chars_but_explicit_single_char_search_still_works(tmp_path: Path):
    pdf = tmp_path / "single_char_search.pdf"
    _create_pdf(pdf, pages=2, text_prefix="Alpha")

    win = MainWindow()
    win._open_file(str(pdf))
    win._show_find()
    QApplication.processEvents()

    win._search_input.setText("a")
    win._execute_live_search_current()
    QApplication.processEvents()

    ctx = win.current_context()
    assert ctx.search_query == "a"
    assert ctx.search_results == []
    assert win._search_count_lbl.text() == "Type 2+ chars"

    win._find_next()
    QApplication.processEvents()

    assert len(ctx.search_results) >= 2
    assert win._search_count_lbl.text() == f"{ctx.search_index + 1}/{len(ctx.search_results)}"
    win.close()


def test_add_highlight_annotation_updates_state(tmp_path: Path):
    pdf = tmp_path / "annot.pdf"
    _create_pdf(pdf, pages=1)

    win = MainWindow()
    win._open_file(str(pdf))
    QApplication.processEvents()

    view = win.current_view()
    view._create_selection_on_page(0, QRectF(40, 50, 100, 40))
    win._add_highlight()

    ctx = win.current_context()
    assert len(ctx.sidecar_state.annotations) == 1
    assert ctx.sidecar_state.annotations[0].type == "highlight"
    assert len(view._annotations) == 1
    win.close()


def test_force_reload_refreshes_active_search_results(tmp_path: Path):
    pdf = tmp_path / "reload_search.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Reloadable")

    win = MainWindow()
    win._open_file(str(pdf))
    win._show_find()
    QApplication.processEvents()

    win._search_input.setText("search-target")
    win._execute_search_current()
    QApplication.processEvents()

    assert win.current_view().page_count == 1
    assert len(win.current_context().search_results) == 1

    _rewrite_pdf_for_reload(win, pdf, pages=3, text_prefix="Reloadable")
    win._force_reload()
    QApplication.processEvents()

    assert win.current_view().page_count == 3
    assert len(win.current_context().search_results) == 3
    assert win._search_count_lbl.text() == "1/3"
    win.close()


def test_force_reload_invalidates_page_pixmap_cache_for_same_path(tmp_path: Path):
    pdf = tmp_path / "same_path_reload.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Before")

    win = MainWindow()
    win._open_file(str(pdf))
    QApplication.processEvents()

    before_text = win.current_view().document.load_page(0).get_text("text")
    before_key = win.current_view()._pages[0].pixmap().cacheKey()

    _rewrite_pdf_for_reload(win, pdf, pages=1, text_prefix="After")
    win._force_reload()
    QApplication.processEvents()

    after_text = win.current_view().document.load_page(0).get_text("text")
    after_key = win.current_view()._pages[0].pixmap().cacheKey()

    assert "Before" in before_text
    assert "After" in after_text
    assert before_key != after_key
    win.close()


def test_restore_last_active_document_only(tmp_path: Path):
    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    _create_pdf(pdf_a, pages=1, text_prefix="A")
    _create_pdf(pdf_b, pages=1, text_prefix="B")

    win1 = MainWindow()
    win1._open_file(str(pdf_a))
    win1._open_file(str(pdf_b))
    win1._tabs.setCurrentWidget(win1._find_open_view(str(pdf_b)))
    QApplication.processEvents()
    win1.close()

    win2 = MainWindow()
    QApplication.processEvents()
    assert win2._tabs.count() == 1
    assert os.path.abspath(win2.current_context().file_path or "") == os.path.abspath(str(pdf_b))
    win2.close()


def test_tab_switch_wraparound_actions(tmp_path: Path):
    pdf_a = tmp_path / "tab_a.pdf"
    pdf_b = tmp_path / "tab_b.pdf"
    _create_pdf(pdf_a, pages=1, text_prefix="A")
    _create_pdf(pdf_b, pages=1, text_prefix="B")

    win = MainWindow()
    win._open_file(str(pdf_a))
    win._open_file(str(pdf_b))
    QApplication.processEvents()

    assert win._tabs.count() == 2
    assert os.path.abspath(win.current_context().file_path or "") == os.path.abspath(str(pdf_b))

    win._switch_to_next_tab()
    QApplication.processEvents()
    assert os.path.abspath(win.current_context().file_path or "") == os.path.abspath(str(pdf_a))

    win._switch_to_previous_tab()
    QApplication.processEvents()
    assert os.path.abspath(win.current_context().file_path or "") == os.path.abspath(str(pdf_b))
    win.close()
