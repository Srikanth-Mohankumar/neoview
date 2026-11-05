from copy import deepcopy
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QMessageBox

from neoview.models.view_state import AnnotationRecord
from neoview.ui.main_window import MainWindow
from neoview.ui.tools.clear_recent_files import run


def make_pdf(path):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), path.stem)
        document.save(str(path))
    return str(path)


@pytest.mark.parametrize("tab_count", [1, 2])
def test_clear_preserves_open_documents_and_pending_state(tmp_path, qtbot, monkeypatch, tab_count):
    window = MainWindow()
    qtbot.addWidget(window)
    paths = [make_pdf(tmp_path / f"document-{index}.pdf") for index in range(tab_count)]
    for index, path in enumerate(paths):
        window._open_file(path)
        window.current_context().sidecar_state.annotations.append(
            AnnotationRecord(str(index), "note", 0, (10, 10, 20, 20), contents="Pending")
        )
        window._mark_sidecar_dirty(window.current_view())
    views = [window._tabs.widget(index) for index in range(window._tabs.count())]
    contexts = [window._tab_contexts[view] for view in views]
    states = [deepcopy(context.sidecar_state) for context in contexts]
    timers = [window._sidecar_timers[view].isActive() for view in views]
    sessions = deepcopy(window._document_sessions)
    window._closed_pdf_paths = ["previously-closed.pdf"]
    assert window._settings.value("session/last_active_file") == paths[-1]
    questions = []

    def confirm(*args):
        questions.append(args)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    run(window)
    assert questions[0][2] == "Clear the recent files list? Open documents stay open."
    assert questions[0][4] == QMessageBox.StandardButton.No
    assert window._recent_files == []
    assert window._settings.value("recent_files", type=list) == []
    assert window._welcome.recent_buttons == []
    assert all(action.text() not in paths for action in window._recent_menu.actions())
    assert [window._tabs.widget(index) for index in range(window._tabs.count())] == views
    assert [window._tab_contexts[view] for view in views] == contexts
    assert [context.sidecar_state for context in contexts] == states
    assert [window._sidecar_timers[view].isActive() for view in views] == timers
    assert window._document_sessions == sessions
    assert window._closed_pdf_paths == ["previously-closed.pdf"]
    assert window._settings.value("session/last_active_file") == paths[-1]
    for view, path in zip(views, paths):
        assert not view.document.is_closed
        assert view.document[0].get_text().strip() == Path(path).stem
    extra = make_pdf(tmp_path / "new.pdf")
    window._open_file(extra)
    assert window._recent_files == [extra]
    assert window._welcome.recent_buttons[0].toolTip() == extra


def test_cancel_preserves_list_and_settings(tmp_path, qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    path = make_pdf(tmp_path / "recent.pdf")
    window._add_recent_file(path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    run(window)
    assert window._recent_files == [path]
    assert window._settings.value("recent_files", type=list) == [path]
    assert window._welcome.recent_buttons[0].toolTip() == path


def test_empty_list_does_not_prompt(qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)

    def unexpected(*args):
        pytest.fail("An empty recent-files list must not prompt")

    monkeypatch.setattr(QMessageBox, "question", unexpected)
    run(window)
    assert "already empty" in window._status.currentMessage()


def test_clear_action_works_without_open_document(tmp_path, qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    path = make_pdf(tmp_path / "recent.pdf")
    window._add_recent_file(path)
    assert window.current_view().document is None
    assert window._clear_recent_files_action.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window._clear_recent_files_action.trigger()
    assert window._recent_files == []
    assert not window._clear_recent_files_action.isEnabled()
    assert window._welcome.recent_buttons == []


def test_settings_failure_retains_recent_files(tmp_path, qtbot, monkeypatch):
    from PySide6.QtCore import QSettings

    window = MainWindow()
    qtbot.addWidget(window)
    path = make_pdf(tmp_path / "recent.pdf")
    window._add_recent_file(path)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(window._settings, "status", lambda: QSettings.Status.AccessError)
    run(window)
    assert window._recent_files == [path]
    assert window._settings.value("recent_files", type=list) == [path]
    assert window._welcome.recent_buttons[0].toolTip() == path
    assert window._clear_recent_files_action.isEnabled()
    assert "Could not save" in window._status.currentMessage()
