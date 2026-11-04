from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from neoview.ui.main_window import MainWindow
from neoview.ui.tools.copy_path import run


def make_pdf(path):
    with fitz.open() as document:
        document.new_page()
        document.save(str(path))


def test_copies_active_absolute_path_without_changing_files(tmp_path, qtbot):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    make_pdf(first)
    make_pdf(second)
    original_first, original_second = first.read_bytes(), second.read_bytes()
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(first))
    first_view = window.current_view()
    window._open_file(str(second))
    run(window)
    assert QApplication.clipboard().text() == str(second.absolute())
    assert "Copied PDF file path" in window._status.currentMessage()
    window._tabs.setCurrentWidget(first_view)
    run(window)
    assert QApplication.clipboard().text() == str(first.absolute())
    assert first.read_bytes() == original_first
    assert second.read_bytes() == original_second


def test_unicode_path_is_copied_verbatim(tmp_path, qtbot):
    source = tmp_path / "review-\u00e9\u6d4b.pdf"
    make_pdf(source)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    run(window)
    assert QApplication.clipboard().text() == str(source.absolute())


def test_no_document_leaves_clipboard_unchanged(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    QApplication.clipboard().setText("existing clipboard")
    with pytest.raises(ValueError, match="Open a PDF"):
        run(window)
    assert QApplication.clipboard().text() == "existing clipboard"


def test_copies_absolute_path_for_relative_context(tmp_path, qtbot, monkeypatch):
    source = tmp_path / "relative.pdf"
    make_pdf(source)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    monkeypatch.chdir(tmp_path)
    window.current_context().file_path = source.name
    run(window)
    assert QApplication.clipboard().text() == str(Path.cwd() / source.name)
    # Restore the context for ordinary persistence during widget cleanup.
    window.current_context().file_path = str(source)
