import csv
import io
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog

from neoview.models.view_state import AnnotationRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import save_sidecar
from neoview.ui.tools.page_report import export_page_report, geometry_csv, run


def make_pdf(path):
    with fitz.open() as document:
        first = document.new_page(width=72, height=144)
        first.add_text_annot((10, 10), "Native annotation")
        second = document.new_page(width=216, height=288)
        second.set_rotation(90)
        document.save(str(path))


def make_state():
    return DocumentSidecarState(annotations=[
        AnnotationRecord("one", "note", 1, (1, 1, 10, 10)),
        AnnotationRecord("two", "rectangle", 1, (20, 20, 10, 10)),
    ])


def window_for(document, source, state):
    return SimpleNamespace(
        current_view=lambda: SimpleNamespace(document=document),
        current_context=lambda: SimpleNamespace(file_path=str(source), sidecar_state=state),
    )


def test_report_records_rotated_geometry_conversions_and_annotation_counts(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    with fitz.open(source) as document:
        rows = list(csv.DictReader(io.StringIO(geometry_csv(document, make_state()))))
    assert [row["page"] for row in rows] == ["1", "2"]
    assert float(rows[0]["width_pt"]) == 72
    assert float(rows[0]["height_pt"]) == 144
    assert float(rows[0]["width_mm"]) == pytest.approx(25.4)
    assert float(rows[0]["height_mm"]) == pytest.approx(50.8)
    assert rows[0]["rotation_degrees"] == "0"
    assert rows[0]["native_annotation_count"] == "1"
    assert rows[0]["editable_annotation_count"] == "0"
    assert float(rows[1]["width_pt"]) == 288
    assert float(rows[1]["height_pt"]) == 216
    assert rows[1]["rotation_degrees"] == "90"
    assert rows[1]["native_annotation_count"] == "0"
    assert rows[1]["editable_annotation_count"] == "2"


def test_export_keeps_source_and_sidecar_unchanged(tmp_path):
    source = tmp_path / "source.pdf"
    target = tmp_path / "report.csv"
    make_pdf(source)
    state = make_state()
    save_sidecar(source, state)
    sidecar = Path(str(source) + ".neoview.json")
    before = source.read_bytes(), sidecar.read_bytes()
    with fitz.open(source) as document:
        export_page_report(document, state, str(source), str(target))
    assert len(list(csv.DictReader(io.StringIO(target.read_text())))) == 2
    assert (source.read_bytes(), sidecar.read_bytes()) == before


@pytest.mark.parametrize("kind", ["source", "sidecar", "hardlink"])
def test_export_rejects_source_aliases(tmp_path, kind):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    state = make_state()
    save_sidecar(source, state)
    target = source if kind == "source" else Path(str(source) + ".neoview.json")
    if kind == "hardlink":
        target = tmp_path / "linked.csv"
        try:
            target.hardlink_to(source)
        except OSError:
            pytest.skip("Hard links unavailable")
    before = source.read_bytes()
    with fitz.open(source) as document, pytest.raises(ValueError, match="separate"):
        export_page_report(document, state, str(source), str(target))
    assert source.read_bytes() == before


def test_failed_replace_keeps_existing_report(tmp_path, monkeypatch):
    from neoview.ui import tool_support

    source = tmp_path / "source.pdf"
    target = tmp_path / "report.csv"
    make_pdf(source)
    target.write_text("old report")

    def fail_replace(*_):
        raise OSError("Cannot replace")

    monkeypatch.setattr(tool_support.os, "replace", fail_replace)
    with fitz.open(source) as document, pytest.raises(OSError, match="Cannot replace"):
        export_page_report(document, make_state(), str(source), str(target))
    assert target.read_text() == "old report"
    assert not list(tmp_path.glob(".neoview-export-*"))


def test_run_cancel_leaves_no_report(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    with fitz.open(source) as document:
        assert run(window_for(document, source, make_state())) is None
    assert not list(tmp_path.glob("*.csv"))


def test_run_uses_snapshot_even_if_original_closes_during_dialog(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    target = tmp_path / "report.csv"
    make_pdf(source)
    document = fitz.open(source)

    def select(*_):
        document.close()
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", select)
    assert run(window_for(document, source, make_state())) is None
    rows = list(csv.DictReader(io.StringIO(target.read_text())))
    assert [row["page"] for row in rows] == ["1", "2"]
