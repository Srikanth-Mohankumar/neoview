import fitz
import pytest

from neoview.models.view_state import AnnotationRecord, BookmarkRecord
from neoview.persistence.sidecar_store import load_sidecar
from neoview.ui.main_window import MainWindow
from neoview.ui.tools.close_other_tabs import run
from neoview.ui.tools.reopen_closed_tab import run as reopen


def pdf(path):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), path.stem)
        document.save(str(path))
    return str(path)


@pytest.mark.parametrize("active_index", [0, 1, 2])
def test_closes_others_preserves_active_and_persists_closed_state(tmp_path, qtbot, active_index):
    paths = [pdf(tmp_path / f"document-{index}.pdf") for index in range(3)]
    window = MainWindow()
    qtbot.addWidget(window)
    for index, path in enumerate(paths):
        window._open_file(path)
        context = window.current_context()
        context.sidecar_state.annotations.append(
            AnnotationRecord(f"a{index}", "note", 0, (10, 10, 20, 20), contents=f"Note {index}")
        )
        context.sidecar_state.bookmarks.append(BookmarkRecord(f"b{index}", f"Mark {index}", 0, 5))
        window._mark_sidecar_dirty(window.current_view())
    window._tabs.setCurrentIndex(active_index)
    active = window.current_view()
    active_context = window.current_context()
    active.set_zoom(1.5, immediate=True)
    run(window)
    assert window._tabs.count() == 1
    assert window.current_view() is active
    assert window.current_context() is active_context
    assert window.current_context().file_path == paths[active_index]
    assert active.document[0].get_text().strip() == f"document-{active_index}"
    assert active.zoom == 1.5
    expected_closed = [path for index, path in reversed(list(enumerate(paths)))
                       if index != active_index]
    assert window._closed_pdf_paths == expected_closed
    for index, path in enumerate(paths):
        if index == active_index:
            continue
        state = load_sidecar(path)
        assert state.annotations[0].contents == f"Note {index}"
        assert state.bookmarks[0].title == f"Mark {index}"
    assert window._extra_tool_actions["reopen_closed_tab"].isEnabled()
    reopen(window)
    assert window.current_context().file_path == expected_closed[-1]
    assert window._tabs.count() == 2


def test_single_tab_is_noop(tmp_path, qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    path = pdf(tmp_path / "single.pdf")
    window._open_file(path)
    active = window.current_view()
    run(window)
    assert window._tabs.count() == 1
    assert window.current_view() is active
    assert window._closed_pdf_paths == []
    assert "Closed 0" in window._status.currentMessage()


def test_no_document_is_noop(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    run(window)
    assert window._tabs.count() == 1
    assert window.current_context().file_path is None
    assert window._closed_pdf_paths == []
    assert "Open a PDF" in window._status.currentMessage()
