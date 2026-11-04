"""Editable annotation transfer preserves full records without mutating source files."""
import json
from dataclasses import asdict

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.models.view_state import AnnotationRecord
from neoview.ui.main_window import MainWindow
from neoview.ui.tools import export_annotations_json as tool


def record():
    return AnnotationRecord(
        id="original-id", type="freehand", page=0, rect=(1, 2, 3, 4),
        contents="Line one\nUnicode \u03bb, quoted \"text\"", color="#abcdef", opacity=0.7,
        created_at="2026-11-04", updated_at="2026-11-05", border_color="#123456",
        border_width=3.25, font_size=14, points=[[1.2, 3.4], [5.6, 7.8]],
        extra={"nested": {"label": "\u00e9"}},
    )


@pytest.fixture
def opened(tmp_path, qtbot):
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(source))
    sidecar = tmp_path / "source.pdf.neoview.json"
    sidecar.write_text('{"version":1,"annotations":[],"bookmarks":[]}', encoding="utf-8")
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    window.current_context().sidecar_state.annotations = [record()]
    return window, source, sidecar


def test_schema_preserves_every_field_and_zero_based_page():
    original = record()
    result = json.loads(tool.annotation_json([original]))
    expected = json.loads(json.dumps(asdict(original)))
    assert result == {"version": 1, "annotations": [expected]}
    assert "\u03bb" in tool.annotation_json([original])
    assert original.rect == (1, 2, 3, 4)


def test_nonfinite_values_are_rejected():
    original = record()
    original.points[0][0] = float("nan")
    with pytest.raises(ValueError):
        tool.annotation_json([original])


def test_run_exports_editable_only_and_preserves_sources(opened, tmp_path, monkeypatch):
    window, source, sidecar = opened
    original_pdf, original_sidecar = source.read_bytes(), sidecar.read_bytes()
    window.current_context().native_annotations = [record()]
    target = tmp_path / "annotations.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    tool.run(window)
    result = json.loads(target.read_text(encoding="utf-8"))
    assert len(result["annotations"]) == 1
    assert result["annotations"][0]["id"] == "original-id"
    assert result["annotations"][0]["extra"] == {"nested": {"label": "\u00e9"}}
    assert source.read_bytes() == original_pdf
    assert sidecar.read_bytes() == original_sidecar


def test_snapshot_survives_dialog_record_mutation(opened, tmp_path, monkeypatch):
    window, _, _ = opened
    target = tmp_path / "snapshot.json"

    def destination(*_):
        window.current_context().sidecar_state.annotations[0].extra["nested"]["label"] = "changed"
        window.current_context().sidecar_state.annotations.clear()
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", destination)
    tool.run(window)
    assert json.loads(target.read_text())["annotations"][0]["extra"]["nested"]["label"] == "\u00e9"


def test_cancel_creates_no_file(opened, tmp_path, monkeypatch):
    window, _, _ = opened
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    before = set(tmp_path.iterdir())
    tool.run(window)
    assert set(tmp_path.iterdir()) == before


def test_empty_editable_list_does_not_export_native(opened, monkeypatch):
    window, _, _ = opened
    window.current_context().sidecar_state.annotations.clear()
    window.current_context().native_annotations = [record()]
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("Unexpected save dialog"))
    tool.run(window)
    assert messages == ["No editable annotations to export."]


@pytest.mark.parametrize("which", ["pdf", "sidecar"])
def test_source_aliases_are_rejected(opened, monkeypatch, which):
    window, source, sidecar = opened
    target = source if which == "pdf" else sidecar
    before = target.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    with pytest.raises(ValueError, match="separate"):
        tool.run(window)
    assert target.read_bytes() == before


def test_atomic_write_failure_preserves_existing_report(opened, tmp_path, monkeypatch):
    import neoview.ui.tool_support as support

    window, _, _ = opened
    target = tmp_path / "report.json"
    target.write_text("existing report")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))

    def fail(*_):
        raise OSError("write failed")

    monkeypatch.setattr(support.os, "replace", fail)
    with pytest.raises(OSError, match="write failed"):
        tool.run(window)
    assert target.read_text() == "existing report"
    assert not list(tmp_path.glob(".neoview-export-*"))
