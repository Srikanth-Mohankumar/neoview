import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.models.view_state import DocumentSidecarState
from neoview.ui.tools.outline_json import outline_payload, run


def make_pdf(path, outline=True):
    with fitz.open() as document:
        document.new_page()
        document.new_page()
        if outline:
            document.set_toc([[1, "Caf\u00e9", 1], [2, "Details", 2], [1, "Website", -1]])
            document.set_toc_item(2, kind=fitz.LINK_URI, uri="https://example.com/reference")
        document.save(str(path))


def window_for(document, source):
    return SimpleNamespace(
        current_view=lambda: SimpleNamespace(document=document),
        current_context=lambda: SimpleNamespace(file_path=str(source),
                                               sidecar_state=DocumentSidecarState()),
    )


def test_nested_outline_and_nonlocal_destinations(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    with fitz.open(source) as document:
        payload = outline_payload(document)
    assert payload["version"] == 1
    first, website = payload["outline"]
    assert first["title"] == "Caf\u00e9"
    assert first["page"] == 1
    assert first["destination"]["page"] == 1
    assert first["children"][0]["title"] == "Details"
    assert first["children"][0]["page"] == 2
    assert first["children"][0]["level"] == 2
    assert website["page"] is None
    assert website["destination"]["uri"] == "https://example.com/reference"
    json.dumps(payload, allow_nan=False)


def test_run_preserves_source_and_writes_unicode(tmp_path, monkeypatch):
    source, target = tmp_path / "source.pdf", tmp_path / "outline.json"
    make_pdf(source)
    original = source.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    with fitz.open(source) as document:
        assert run(window_for(document, source)) is None
    assert "Caf\u00e9" in target.read_text(encoding="utf-8")
    assert json.loads(target.read_text(encoding="utf-8"))["outline"][0]["page"] == 1
    assert source.read_bytes() == original


def test_no_outline_does_not_prompt_destination(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source, outline=False)
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("Unexpected dialog"))
    with fitz.open(source) as document:
        run(window_for(document, source))
    assert messages == ["This document has no outline."]


def test_cancel_does_not_write(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    with fitz.open(source) as document:
        run(window_for(document, source))
    assert [path for path in tmp_path.iterdir() if path.is_file()] == [source]


@pytest.mark.parametrize("target_kind", ["pdf", "sidecar", "hardlink"])
def test_source_aliases_rejected(tmp_path, monkeypatch, target_kind):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    sidecar = Path(str(source) + ".neoview.json")
    sidecar.write_text("{}")
    target = source if target_kind == "pdf" else sidecar
    if target_kind == "hardlink":
        target = tmp_path / "alias.json"
        try:
            target.hardlink_to(source)
        except OSError:
            pytest.skip("Hard links unavailable")
    original, original_sidecar = source.read_bytes(), sidecar.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    with fitz.open(source) as document, pytest.raises(ValueError, match="separate"):
        run(window_for(document, source))
    assert source.read_bytes() == original and sidecar.read_bytes() == original_sidecar


def test_atomic_failure_preserves_existing_report(tmp_path, monkeypatch):
    from neoview.ui import tool_support

    source, target = tmp_path / "source.pdf", tmp_path / "outline.json"
    make_pdf(source)
    target.write_text("Existing")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))

    def fail_replace(*_):
        raise OSError("simulated failure")

    monkeypatch.setattr(tool_support.os, "replace", fail_replace)
    with fitz.open(source) as document, pytest.raises(OSError, match="simulated"):
        run(window_for(document, source))
    assert target.read_text() == "Existing"
    assert not list(tmp_path.glob(".neoview-export-*"))


def test_snapshot_survives_source_close(tmp_path, monkeypatch):
    source, target = tmp_path / "source.pdf", tmp_path / "outline.json"
    make_pdf(source)
    document = fitz.open(source)

    def choose(*_):
        document.close()
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    run(window_for(document, source))
    assert json.loads(target.read_text())["outline"][0]["title"] == "Caf\u00e9"
