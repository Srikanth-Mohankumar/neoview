import fitz
import pytest

from neoview.models.view_state import AnnotationRecord, BookmarkRecord
from neoview.persistence.sidecar_store import load_sidecar
from neoview.ui.main_window import MainWindow
from neoview.ui.tools.close_tabs_right import run
from neoview.ui.tools.reopen_closed_tab import run as reopen


def pdf(path):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), path.stem)
        document.save(str(path))
    return str(path)


def window(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.mark.parametrize("active", [0, 1, 3])
def test_closes_only_right_preserving_active_and_left(tmp_path, qtbot, active):
    paths = [pdf(tmp_path / f"document-{i}.pdf") for i in range(4)]
    win = window(qtbot)
    for path in paths:
        win._open_file(path)
    win._tabs.setCurrentIndex(active)
    retained_view = win.current_view()
    retained_context = win.current_context()
    run(win)
    assert win._tabs.count() == active + 1
    assert win.current_view() is retained_view
    assert win.current_context() is retained_context
    assert win.current_context().file_path == paths[active]
    assert [win._context_for_view(win._tabs.widget(i)).file_path
            for i in range(win._tabs.count())] == paths[:active + 1]
    assert win._closed_pdf_paths == list(reversed(paths[active + 1:]))
    assert win._extra_tool_actions["reopen_closed_tab"].isEnabled() == (active < 3)


def test_closure_persists_pending_annotations_and_bookmarks(tmp_path, qtbot):
    paths = [pdf(tmp_path / f"document-{i}.pdf") for i in range(3)]
    win = window(qtbot)
    for i, path in enumerate(paths):
        win._open_file(path)
        state = win.current_context().sidecar_state
        state.bookmarks.append(BookmarkRecord(f"b{i}", f"Bookmark {i}", 0, 20))
        state.annotations.append(AnnotationRecord(f"a{i}", "note", 0, (20, 20, 10, 10)))
        win._mark_sidecar_dirty(win.current_view())
    win._tabs.setCurrentIndex(0)
    active_state = win.current_context().sidecar_state
    run(win)
    assert win.current_context().sidecar_state is active_state
    for i in (1, 2):
        state = load_sidecar(paths[i])
        assert state.bookmarks[0].title == f"Bookmark {i}"
        assert state.annotations[0].id == f"a{i}"
    reopen(win)
    assert win.current_context().file_path == paths[1]
    assert win.current_context().sidecar_state.bookmarks[0].title == "Bookmark 1"
    assert win.current_context().sidecar_state.annotations[0].id == "a1"
    assert win._closed_pdf_paths == [paths[2]]


def test_no_document_or_single_document_is_safe(tmp_path, qtbot):
    win = window(qtbot)
    assert run(win) is None
    assert win._tabs.count() == 1
    assert not win._closed_pdf_paths
    assert "No tabs to the right" in win._status.currentMessage()
    path = pdf(tmp_path / "single.pdf")
    win._open_file(path)
    win._extra_tool_actions["close_tabs_right"].trigger()
    assert win.current_context().file_path == path
    assert win._tabs.count() == 1
    assert not win._closed_pdf_paths
