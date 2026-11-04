import fitz
import pytest
from PySide6.QtGui import QDesktopServices

from neoview.ui.main_window import MainWindow
from neoview.ui.tools.reveal_folder import run


def make_pdf(path):
    with fitz.open() as document:
        document.new_page()
        document.save(str(path))


def test_opens_active_document_folder_as_local_url(tmp_path, qtbot, monkeypatch):
    first_dir = tmp_path / "first folder"
    second_dir = tmp_path / "second-\u00e9"
    first_dir.mkdir()
    second_dir.mkdir()
    first, second = first_dir / "a.pdf", second_dir / "b.pdf"
    make_pdf(first)
    make_pdf(second)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(first))
    first_view = window.current_view()
    window._open_file(str(second))
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url) or True)
    run(window)
    assert urls[-1].isLocalFile()
    assert urls[-1].toLocalFile() == str(second_dir)
    assert "Opened PDF containing folder" in window._status.currentMessage()
    window._tabs.setCurrentWidget(first_view)
    run(window)
    assert urls[-1].toLocalFile() == str(first_dir)


def test_failed_desktop_open_is_reported(tmp_path, qtbot, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda _: False)
    with pytest.raises(OSError, match="desktop could not"):
        run(window)


def test_no_document_does_not_launch_desktop(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    calls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: calls.append(url) or True)
    with pytest.raises(ValueError, match="Open a PDF"):
        run(window)
    assert calls == []


def test_missing_folder_does_not_launch_desktop(tmp_path, qtbot, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    context = window.current_context()
    context.file_path = str(tmp_path / "missing" / "source.pdf")
    calls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: calls.append(url) or True)
    with pytest.raises(ValueError, match="no longer exists"):
        run(window)
    assert calls == []
    context.file_path = str(source)


def test_relative_context_uses_absolute_folder(tmp_path, qtbot, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    monkeypatch.chdir(tmp_path)
    window.current_context().file_path = source.name
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url) or True)
    run(window)
    assert urls[-1].toLocalFile() == str(tmp_path)
    window.current_context().file_path = str(source)
