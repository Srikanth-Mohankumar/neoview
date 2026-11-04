import fitz

from neoview.models.view_state import BookmarkRecord
from neoview.persistence.sidecar_store import load_sidecar
from neoview.ui.main_window import MainWindow
from neoview.ui.tools.reopen_closed_tab import run


def pdf(path):
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), path.stem)
        doc.save(str(path))
    return str(path)


def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    return win


def action(win):
    return win._extra_tool_actions["reopen_closed_tab"]


def test_last_tab_reopens_and_restores_sidecar(tmp_path, qtbot):
    path = pdf(tmp_path / "last.pdf")
    win = window(qtbot)
    assert not action(win).isEnabled()
    assert action(win).shortcut().toString() == "Ctrl+Shift+W"
    win._open_file(path)
    win.current_context().sidecar_state.bookmarks.append(BookmarkRecord("b", "Saved", 0, 20))
    win._close_current_tab()
    assert win.current_context().file_path is None
    assert action(win).isEnabled()
    assert load_sidecar(path).bookmarks[0].title == "Saved"
    action(win).trigger()
    assert win.current_context().file_path == path
    assert win.current_context().sidecar_state.bookmarks[0].title == "Saved"
    assert win._tabs.count() == 1
    assert not action(win).isEnabled()
    assert win._closed_pdf_paths == []


def test_missing_entries_are_skipped_in_lifo_order(tmp_path, qtbot):
    first = pdf(tmp_path / "first.pdf")
    second = pdf(tmp_path / "second.pdf")
    win = window(qtbot)
    win._closed_pdf_paths = [first, second, str(tmp_path / "missing.pdf")]
    run(win)
    assert win.current_context().file_path == second
    assert win._closed_pdf_paths == [first]
    assert action(win).isEnabled()
    run(win)
    assert win.current_context().file_path == first
    assert win._tabs.count() == 2
    assert not action(win).isEnabled()


def test_existing_tab_selected_without_duplicate(tmp_path, qtbot):
    first = pdf(tmp_path / "first.pdf")
    second = pdf(tmp_path / "second.pdf")
    win = window(qtbot)
    win._open_file(first)
    win._open_file(second)
    win._closed_pdf_paths = [first]
    run(win)
    assert win.current_context().file_path == first
    assert win._tabs.count() == 2
    assert not action(win).isEnabled()


def test_no_history_or_all_missing_is_safe(tmp_path, qtbot):
    win = window(qtbot)
    run(win)
    assert "No closed PDF" in win._status.currentMessage()
    win._closed_pdf_paths = [str(tmp_path / "missing.pdf")]
    run(win)
    assert win._closed_pdf_paths == []
    assert not action(win).isEnabled()
    assert win.current_context().file_path is None


def test_bulk_close_records_every_document(tmp_path, qtbot):
    paths = [pdf(tmp_path / f"page-{i}.pdf") for i in range(4)]
    win = window(qtbot)
    for path in paths:
        win._open_file(path)
    win._tabs.setCurrentIndex(0)
    for index in range(win._tabs.count() - 1, 0, -1):
        win._close_tab_index(index)
    assert win.current_context().file_path == paths[0]
    assert win._closed_pdf_paths == list(reversed(paths[1:]))
    run(win)
    assert win.current_context().file_path == paths[1]
    assert win._tabs.count() == 2


def test_close_history_is_bounded(tmp_path, qtbot):
    path = pdf(tmp_path / "repeat.pdf")
    win = window(qtbot)
    for _ in range(23):
        win._open_file(path)
        win._close_current_tab()
    assert win._closed_pdf_paths == [path] * 20
    run(win)
    assert len(win._closed_pdf_paths) == 19
    assert action(win).isEnabled()


def test_open_failure_consumes_only_attempted_entry(tmp_path, qtbot, monkeypatch):
    path = pdf(tmp_path / "source.pdf")
    win = window(qtbot)
    win._closed_pdf_paths = [str(tmp_path / "older.pdf"), path]
    monkeypatch.setattr(win, "_open_file", lambda _: None)
    run(win)
    assert win._closed_pdf_paths == [str(tmp_path / "older.pdf")]
    assert "Could not reopen" in win._status.currentMessage()
    assert action(win).isEnabled()
