from types import SimpleNamespace
from unittest.mock import Mock

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from neoview.ui.main_window import MainWindow
from neoview.ui.tools.copy_page_text import run


def make_pdf(path, texts):
    with fitz.open() as document:
        for text in texts:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        document.save(str(path))


def test_copies_current_page_from_active_tab_without_mutation(tmp_path, qtbot):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    make_pdf(first, ["First page", "Caf\u00e9\nSecond line"])
    make_pdf(second, ["Other tab"])
    original = first.read_bytes(), second.read_bytes()
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(first))
    first_view = window.current_view()
    window._open_file(str(second))
    run(window)
    assert QApplication.clipboard().text() == "Other tab\n"
    window._tabs.setCurrentWidget(first_view)
    first_view.go_to_page(1)
    before_page = first_view.current_page
    before_state = repr(window.current_context())
    run(window)
    assert QApplication.clipboard().text() == "Caf\u00e9\nSecond line\n"
    assert first_view.current_page == before_page
    assert repr(window.current_context()) == before_state
    assert "Copied current page text" == window._status.currentMessage()
    assert (first.read_bytes(), second.read_bytes()) == original
    assert not list(tmp_path.glob("*.neoview.json"))


def test_blank_page_keeps_clipboard(tmp_path, qtbot):
    source = tmp_path / "blank.pdf"
    make_pdf(source, [""])
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    QApplication.clipboard().setText("existing clipboard")
    run(window)
    assert QApplication.clipboard().text() == "existing clipboard"
    assert window._status.currentMessage() == "No selectable text on current page"


def test_no_document_keeps_clipboard(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    QApplication.clipboard().setText("existing clipboard")
    with pytest.raises(ValueError, match="Open a PDF"):
        run(window)
    assert QApplication.clipboard().text() == "existing clipboard"


@pytest.mark.parametrize("page_index", [-1, 1])
def test_invalid_page_keeps_clipboard(page_index):
    document = Mock(page_count=1)
    window = SimpleNamespace(
        current_view=lambda: SimpleNamespace(document=document, current_page=page_index),
    )
    QApplication.clipboard().setText("existing clipboard")
    with pytest.raises(ValueError, match="page range"):
        run(window)
    assert QApplication.clipboard().text() == "existing clipboard"


@pytest.mark.parametrize("result", [" \n\t", RuntimeError("extraction failed")])
def test_reads_only_current_page_and_preserves_clipboard_on_failure(result):
    page = Mock()
    if isinstance(result, Exception):
        page.get_text.side_effect = result
    else:
        page.get_text.return_value = result
    document = Mock(page_count=5)
    document.__getitem__ = Mock(return_value=page)
    window = SimpleNamespace(
        current_view=lambda: SimpleNamespace(document=document, current_page=3),
        _status=Mock(),
    )
    QApplication.clipboard().setText("existing clipboard")
    if isinstance(result, Exception):
        with pytest.raises(RuntimeError, match="extraction failed"):
            run(window)
    else:
        run(window)
        window._status.showMessage.assert_called_once_with(
            "No selectable text on current page", 3000,
        )
    document.__getitem__.assert_called_once_with(3)
    page.get_text.assert_called_once_with("text")
    assert QApplication.clipboard().text() == "existing clipboard"
