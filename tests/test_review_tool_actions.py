"""Integration between window actions, feature dialogs, and saved PDF tabs."""
from pathlib import Path

import fitz
import pytest

from neoview.models.view_state import BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import save_sidecar
from neoview.ui.main_window import MainWindow


def make_pdf(path: Path, text="Original"):
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), text)
        doc.save(str(path))


def test_review_actions_require_document(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)
    for name in ("_extract_pages_action", "_metadata_action", "_export_csv_action"):
        assert not getattr(win, name).isEnabled()


@pytest.mark.parametrize(("module", "entry", "action"), [
    ("page_extraction", "extract_pages", "_extract_pages_action"),
    ("metadata_editor", "edit_metadata", "_metadata_action"),
])
def test_saved_copy_action_opens_output(tmp_path, qtbot, monkeypatch, module, entry, action):
    import importlib

    source = tmp_path / "source.pdf"
    output = tmp_path / "copy.pdf"
    make_pdf(source)
    make_pdf(output, "Copy")
    win = MainWindow()
    qtbot.addWidget(win)
    win._open_file(str(source))
    calls = []

    def save_copy(parent, document, path, state):
        calls.append((parent, document.page_count, path, state))
        return str(output)

    monkeypatch.setattr(importlib.import_module("neoview.ui." + module), entry, save_copy)
    assert getattr(win, action).isEnabled()
    getattr(win, action).trigger()
    assert len(calls) == 1
    assert calls[0][0] is win and calls[0][2] == str(source)
    assert win.current_context().file_path == str(output)
    assert win._tabs.count() == 2
    assert win.current_view().document[0].get_text().strip() == "Copy"


def test_saved_copy_refreshes_existing_tab_and_sidecar(tmp_path, qtbot):
    path = tmp_path / "copy.pdf"
    make_pdf(path)
    win = MainWindow()
    qtbot.addWidget(win)
    win._open_file(str(path))
    # Replacing a file externally is not permitted while an open reader holds it on Windows.
    win.current_view()._doc.close()
    win.current_view()._doc = None
    make_pdf(path, "Replaced")
    save_sidecar(path, DocumentSidecarState(bookmarks=[BookmarkRecord("new", "New", 0, 0)]))
    win._open_saved_pdf_copy(str(path))
    assert win.current_context().sidecar_state.bookmarks[0].id == "new"
    assert win.current_view().document[0].get_text().strip() == "Replaced"
    assert win._tabs.count() == 1


def test_csv_action_uses_both_annotation_sources(tmp_path, qtbot, monkeypatch):
    from neoview.ui import annotation_csv

    path = tmp_path / "source.pdf"
    make_pdf(path)
    win = MainWindow()
    qtbot.addWidget(win)
    win._open_file(str(path))
    ctx = win.current_context()
    calls = []

    def export(parent, source, annotations, native_annotations):
        calls.append((source, annotations, native_annotations))
        return str(tmp_path / "report.csv")

    monkeypatch.setattr(annotation_csv, "export_annotations_csv", export)
    win._export_csv_action.trigger()
    assert calls == [(str(path), ctx.sidecar_state.annotations, ctx.native_annotations)]
    assert win.current_context().file_path == str(path)
    assert "report.csv" in win._status.currentMessage()
