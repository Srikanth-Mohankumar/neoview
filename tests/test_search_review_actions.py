import csv

import fitz
from PySide6.QtWidgets import QApplication, QFileDialog

from neoview.ui.main_window import MainWindow


def make_pdf(path):
    with fitz.open() as document:
        for text in ("Match first page", "Match second page"):
            document.new_page().insert_text((72, 72), text)
        document.save(str(path))


def test_new_document_actions_and_annotation_filter_follow_active_document(tmp_path, qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window._copy_page_text_action.isEnabled()
    assert not window._search_export_action.isEnabled()
    assert not window._annotation_text_filter.isEnabled()
    path = tmp_path / "source.pdf"
    make_pdf(path)
    window._open_file(str(path))
    assert window._copy_page_text_action.isEnabled()
    assert window._search_export_action.isEnabled()
    assert window._annotation_text_filter.isEnabled()
    window.current_view().go_to_page(1)
    window._copy_page_text_action.trigger()
    assert QApplication.clipboard().text() == window.current_view().document[1].get_text("text")
    window._close_current_tab()
    assert not window._copy_page_text_action.isEnabled()
    assert not window._search_export_action.isEnabled()
    assert not window._annotation_text_filter.isEnabled()
    assert window._clear_recent_files_action.isEnabled()


def test_search_export_action_exports_real_completed_search(tmp_path, qtbot, monkeypatch):
    path = tmp_path / "search.pdf"
    destination = tmp_path / "matches.csv"
    make_pdf(path)
    original = path.read_bytes()
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(path))
    window._search_input.setText("Match")
    qtbot.waitUntil(lambda: not window._search_timer.isActive()
                   and window._search_operation is None
                   and len(window.current_context().search_results) == 2, timeout=5000)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(destination), ""))
    window._search_export_action.trigger()
    with destination.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [int(row["page"]) for row in rows] == [1, 2]
    assert all(row["query"] == "Match" for row in rows)
    assert "first page" in rows[0]["snippet"]
    assert "second page" in rows[1]["snippet"]
    assert path.read_bytes() == original


def test_export_rejects_query_changed_before_tab_switch_debounce(tmp_path, qtbot, monkeypatch):
    import pytest
    from PySide6.QtWidgets import QMessageBox

    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    make_pdf(first)
    make_pdf(second)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(first))
    original_view = window.current_view()
    window._search_input.setText("Match")
    window._execute_search_current()
    assert window._search_results_are_current()
    window._search_input.setText("Different")
    assert window.current_context().search_results
    window._open_file(str(second))
    qtbot.waitUntil(lambda: not window._search_timer.isActive())
    window._tabs.setCurrentWidget(original_view)
    assert window._active_search_text() == window.current_context().search_query == "Different"
    assert not window._search_results_are_current()
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("Stale results exported"))
    window._search_export_action.trigger()
    assert messages and "search" in messages[0].lower()


def test_export_rejects_case_option_changed_in_another_tab(tmp_path, qtbot, monkeypatch):
    import pytest
    from PySide6.QtWidgets import QMessageBox

    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    make_pdf(first)
    make_pdf(second)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(first))
    original_view = window.current_view()
    window._search_input.setText("Match")
    window._execute_search_current()
    assert window._search_results_are_current()
    window._open_file(str(second))
    window._search_case_chk.setChecked(True)
    qtbot.waitUntil(lambda: not window._search_timer.isActive())
    window._tabs.setCurrentWidget(original_view)
    assert window.current_context().search_results
    assert not window._search_results_are_current()
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("Wrong search options exported"))
    window._search_export_action.trigger()
    assert messages
    window._execute_search_current()
    assert window._search_results_are_current()
