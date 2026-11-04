import copy
import csv
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.models.view_state import AnnotationRecord
from neoview.ui.annotation_csv import export_annotations_csv, write_annotations_csv


def record(**changes):
    return replace(AnnotationRecord("id", "note", 0, (10, 20, 30, 40)), **changes)


def read_report(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_report_preserves_unicode_quotes_newlines_and_sources(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source bytes")
    sidecar = tmp_path / "source.pdf.neoview.json"
    sidecar.write_text("sidecar bytes")
    local = [record(contents='Review "quoted", line\n\u03b1', page=2)]
    native = [record(id="native", type="highlight", opacity=0.5)]
    snapshot = copy.deepcopy((local, native))
    out = tmp_path / "report.csv"
    write_annotations_csv(str(source), str(out), local, native)
    rows = read_report(out)
    assert rows[0] == {
        "source": "neoview", "id": "id", "page": "3", "type": "note",
        "contents": 'Review "quoted", line\n\u03b1', "color": "#f7c948", "opacity": "0.25",
        "x_pt": "10.0", "y_pt": "20.0", "width_pt": "30.0", "height_pt": "40.0",
    }
    assert rows[1]["source"] == "native"
    assert rows[1]["page"] == "1"
    assert (local, native) == snapshot
    assert source.read_bytes() == b"source bytes"
    assert sidecar.read_text() == "sidecar bytes"


@pytest.mark.parametrize("text", ["=SUM(A1)", "+cmd", "-cmd", "@cmd", " \t=cmd", "\n@cmd",
                                  "\ufeff\t +cmd"])
def test_formula_like_free_text_is_inert(tmp_path, text):
    out = tmp_path / "report.csv"
    write_annotations_csv(str(tmp_path / "source.pdf"), str(out), [record(
        id=text, type=text, contents=text, color=text,
    )], [])
    row = read_report(out)[0]
    for key in ("id", "type", "contents", "color"):
        assert row[key] == "'" + text


@pytest.mark.parametrize("which", ["pdf", "sidecar", "symlink", "hardlink"])
def test_source_and_sidecar_aliases_rejected(tmp_path, which):
    source = tmp_path / "source.pdf"
    source.write_text("original")
    sidecar = tmp_path / "source.pdf.neoview.json"
    sidecar.write_text("sidecar")
    out = source if which == "pdf" else sidecar
    if which in ("symlink", "hardlink"):
        out = tmp_path / "alias.csv"
        if which == "symlink":
            out.symlink_to(source)
        else:
            out.hardlink_to(sidecar)
    with pytest.raises(ValueError, match="different"):
        write_annotations_csv(str(source), str(out), [record()], [])
    assert source.read_text() == "original"
    assert sidecar.read_text() == "sidecar"


def test_failed_replace_keeps_existing_report_and_cleans_temporary(tmp_path, monkeypatch):
    import neoview.ui.annotation_csv as module

    out = tmp_path / "report.csv"
    out.write_text("existing")

    def fail(*_):
        raise OSError("cannot replace")

    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError, match="cannot replace"):
        write_annotations_csv(str(tmp_path / "source.pdf"), str(out), [record()], [])
    assert out.read_text() == "existing"
    assert not list(tmp_path.glob(".neoview-report-*"))


def test_invalid_record_preserves_existing_report(tmp_path):
    out = tmp_path / "report.csv"
    out.write_text("existing")
    with pytest.raises(ValueError, match="finite"):
        write_annotations_csv(str(tmp_path / "source.pdf"), str(out), [record(opacity=float("nan"))], [])
    assert out.read_text() == "existing"
    assert not list(tmp_path.glob(".neoview-report-*"))


def test_empty_ui_does_not_open_file_dialog(tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("unexpected dialog"))
    assert export_annotations_csv(None, str(tmp_path / "source.pdf"), [], []) is None
    assert messages == ["No annotations to export."]


def test_ui_cancel_then_export_native_only(tmp_path, monkeypatch):
    source = str(tmp_path / "source.pdf")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    assert export_annotations_csv(None, source, [], [record()]) is None
    path = tmp_path / "report"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(path), ""))
    result = export_annotations_csv(None, source, [], [record()])
    assert result == str(tmp_path / "report.csv")
    assert read_report(tmp_path / "report.csv")[0]["source"] == "native"


def test_ui_error_reports_failure_without_success(tmp_path, monkeypatch):
    warnings = []
    source = tmp_path / "source.pdf"
    source.write_text("original")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(source), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    assert export_annotations_csv(None, str(source), [record()], []) is None
    assert warnings and "different" in warnings[0]
    assert source.read_text() == "original"


def test_ui_normalized_extension_does_not_overwrite_without_confirmation(tmp_path, monkeypatch):
    out = tmp_path / "report.csv"
    out.write_text("existing")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(tmp_path / "report"), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.No)
    assert export_annotations_csv(None, str(tmp_path / "source.pdf"), [record()], []) is None
    assert out.read_text() == "existing"
