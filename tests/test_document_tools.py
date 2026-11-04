"""Window registration and shared safety checks for additional document tools."""
from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QMessageBox

from neoview.models.view_state import BookmarkRecord, DocumentSidecarState
from neoview.ui import document_tools
from neoview.ui.main_window import MainWindow
from neoview.ui.tool_support import apply_state, atomic_text, snapshot


def make_pdf(path):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "Tools")
        document.save(str(path))


def test_all_twenty_tools_registered_and_document_guarded(tmp_path, qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert len(window._extra_tool_actions) == 20
    assert not any(action.isEnabled() for action in window._extra_tool_actions.values())
    source = tmp_path / "test.pdf"
    make_pdf(source)
    window._open_file(str(source))
    for slug, action in window._extra_tool_actions.items():
        assert action.isEnabled() == (slug != "reopen_closed_tab")
    window._close_current_tab()
    assert window._extra_tool_actions["reopen_closed_tab"].isEnabled()
    assert all(not action.isEnabled() for slug, action in window._extra_tool_actions.items()
               if slug != "reopen_closed_tab")


def test_dispatch_opens_saved_pdf_and_reports_error(tmp_path, qtbot, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    output = tmp_path / "copy.pdf"
    make_pdf(output)

    class Module:
        @staticmethod
        def run(_):
            return str(output)

    monkeypatch.setattr(document_tools, "import_module", lambda _: Module)
    document_tools.invoke(window, "example")
    assert window.current_context().file_path == str(output)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: messages.append(args[2]))

    def fail(_):
        raise OSError("Cannot save")

    monkeypatch.setattr(Module, "run", fail)
    document_tools.invoke(window, "example")
    assert messages == ["Cannot save"]


def test_snapshot_survives_reload_and_has_independent_state(tmp_path, qtbot):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    state = window.current_context().sidecar_state
    state.bookmarks.append(BookmarkRecord("b", "Original", 0, 0))
    with snapshot(window) as (document, copied, path):
        state.bookmarks[0].title = "Changed"
        window.current_view().close_document()
        assert document[0].get_text().strip() == "Tools"
        assert copied.bookmarks[0].title == "Original"
        assert path == str(source)
    assert document.is_closed


def test_apply_state_updates_view_sidebar_and_timer(tmp_path, qtbot):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    state = DocumentSidecarState(bookmarks=[BookmarkRecord("imported", "Imported", 0, 0)])
    apply_state(window, state)
    assert window.current_context().sidecar_state is state
    assert window._bookmarks_list.count() == 1
    assert window._sidecar_timers[window.current_view()].isActive()


def test_atomic_report_protects_source_and_cleans_failure(tmp_path, monkeypatch):
    import neoview.ui.tool_support as support

    source = tmp_path / "source.pdf"
    make_pdf(source)
    before = source.read_bytes()
    with pytest.raises(ValueError):
        atomic_text(str(source), str(source), "bad")
    with pytest.raises(ValueError):
        atomic_text(str(source), str(source) + ".neoview.json", "bad")
    destination = tmp_path / "report.txt"
    destination.write_text("before")

    def fail(*_):
        raise OSError("replace failed")

    monkeypatch.setattr(support.os, "replace", fail)
    with pytest.raises(OSError):
        atomic_text(str(source), str(destination), "after")
    assert source.read_bytes() == before
    assert destination.read_text() == "before"
    assert not list(Path(tmp_path).glob(".neoview-export-*"))


def test_annotation_transfer_roundtrip_preserves_all_editable_fields():
    import json
    from dataclasses import asdict

    from neoview.models.view_state import AnnotationRecord
    from neoview.ui.tools.export_annotations_json import annotation_json
    from neoview.ui.tools.import_annotations_json import parse_annotations

    original = AnnotationRecord(
        "original", "freehand", 1, (10, 20, 30, 40), contents="Review, \u03bb\nnext line",
        color="#aabbcc", border_color="#112233", border_width=3.5, opacity=.6,
        font_size=15, points=[[10, 20], [30, 40]], extra={"reviewer": "Example"},
    )
    imported = parse_annotations(json.loads(annotation_json([original])), 2)
    assert len(imported) == 1
    assert imported[0].id != original.id
    actual = asdict(imported[0])
    actual["id"] = original.id
    assert actual == asdict(original)


def test_window_close_cancels_background_export_and_cleans_staging(tmp_path, qtbot, monkeypatch):
    from PySide6.QtCore import QProcess

    from neoview.ui.background_png_export import PngExportJob

    path = tmp_path / "source.pdf"
    make_pdf(path)
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(path))
    window.show()
    monkeypatch.setattr(PngExportJob, "worker_arguments", lambda *_: [
        "-c", "import time; time.sleep(10)",
    ])
    with snapshot(window) as (document, _, __):
        job = PngExportJob(window, document, "1", 72, str(tmp_path / "images")).start()
    work = job.work
    qtbot.waitUntil(lambda: job.process.state() == QProcess.ProcessState.Running)
    window.close()
    assert job.done and job.cancelled
    assert not window._document_export_jobs
    assert not work.exists()
    assert not (tmp_path / "images").exists()
