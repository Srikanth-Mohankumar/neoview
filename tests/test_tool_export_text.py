from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog

from neoview.models.view_state import DocumentSidecarState
from neoview.ui.tools.export_text import render_text, run


def make_pdf(path):
    with fitz.open() as document:
        document.new_page().insert_text((72, 72), "First caf\u00e9")
        document.new_page()
        document.new_page().insert_text((72, 72), "Last page")
        document.save(str(path))


def window_for(document, source):
    return SimpleNamespace(
        current_view=lambda: SimpleNamespace(document=document),
        current_context=lambda: SimpleNamespace(
            file_path=str(source), sidecar_state=DocumentSidecarState(),
        ),
    )


def test_render_text_preserves_order_unicode_and_blank_pages(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    with fitz.open(source) as document:
        text = render_text(document)
    assert text == ("--- Page 1 ---\nFirst caf\u00e9\n\n"
                    "--- Page 2 ---\n\n\n--- Page 3 ---\nLast page\n")


def test_render_text_rejects_empty_document():
    with fitz.open() as document, pytest.raises(ValueError, match="nonempty"):
        render_text(document)


def test_run_writes_utf8_without_mutating_source(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    target = tmp_path / "document.txt"
    make_pdf(source)
    sidecar = Path(str(source) + ".neoview.json")
    sidecar.write_text('{"existing":true}', encoding="utf-8")
    original_pdf, original_sidecar = source.read_bytes(), sidecar.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    with fitz.open(source) as document:
        assert run(window_for(document, source)) is None
    assert "caf\u00e9" in target.read_text(encoding="utf-8")
    assert source.read_bytes() == original_pdf
    assert sidecar.read_bytes() == original_sidecar


def test_run_cancel_does_not_write(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    with fitz.open(source) as document:
        run(window_for(document, source))
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["source.pdf"]


@pytest.mark.parametrize("kind", ["pdf", "sidecar", "hardlink"])
def test_run_rejects_source_and_sidecar_aliases(tmp_path, monkeypatch, kind):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    sidecar = Path(str(source) + ".neoview.json")
    sidecar.write_text("{}", encoding="utf-8")
    target = source if kind == "pdf" else sidecar
    if kind == "hardlink":
        target = tmp_path / "alias.txt"
        try:
            target.hardlink_to(source)
        except OSError:
            pytest.skip("Hard links unavailable")
    before_pdf, before_sidecar = source.read_bytes(), sidecar.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    with fitz.open(source) as document, pytest.raises(ValueError, match="separate"):
        run(window_for(document, source))
    assert source.read_bytes() == before_pdf
    assert sidecar.read_bytes() == before_sidecar


def test_run_snapshot_survives_source_reload(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    target = tmp_path / "document.txt"
    make_pdf(source)
    document = fitz.open(source)

    def choose(*_):
        document.close()
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    run(window_for(document, source))
    assert "First caf\u00e9" in target.read_text(encoding="utf-8")


def test_write_failure_preserves_existing_target_and_cleans_staging(tmp_path, monkeypatch):
    import neoview.ui.tool_support as support

    source = tmp_path / "source.pdf"
    target = tmp_path / "document.txt"
    make_pdf(source)
    target.write_text("Existing", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))

    def fail_replace(*_):
        raise OSError("Cannot replace")

    monkeypatch.setattr(support.os, "replace", fail_replace)
    with fitz.open(source) as document, pytest.raises(OSError, match="Cannot replace"):
        run(window_for(document, source))
    assert target.read_text(encoding="utf-8") == "Existing"
    assert not list(tmp_path.glob(".neoview-export-*"))
