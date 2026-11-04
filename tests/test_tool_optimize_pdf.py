from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog

from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import load_sidecar, save_sidecar
from neoview.ui.tools import optimize_pdf


def make_pdf(path):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 40), "Lossless source text")
        xref = page.get_contents()[0]
        # Legal, deliberately uncompressed whitespace gives compression useful work.
        doc.update_stream(xref, doc.xref_stream(xref) + b"\n" * 20000, compress=False)
        image = fitz.Pixmap(fitz.csRGB, (0, 0, 4, 4), False)
        image.clear_with(255)
        page.insert_image(fitz.Rect(40, 80, 80, 120), stream=image.tobytes("png"))
        page.add_text_annot((100, 100), "Native note")
        doc.set_metadata({"title": "Original title", "author": "Original author"})
        doc.set_toc([[1, "Section", 1]])
        doc.save(str(path), deflate=False)


def make_state():
    return DocumentSidecarState(
        annotations=[AnnotationRecord("note", "note", 0, (10, 10, 15, 20),
                                      contents="Editable note", created_at="2026-01-01",
                                      updated_at="2026-01-01")],
        bookmarks=[BookmarkRecord("bookmark", "Mark", 0, 20, created_at="2026-01-01")],
    )


def window_for(doc, path, state):
    return SimpleNamespace(
        current_view=lambda: SimpleNamespace(document=doc),
        current_context=lambda: SimpleNamespace(file_path=str(path), sidecar_state=state),
    )


def test_optimization_preserves_pdf_and_editable_records(tmp_path):
    source = tmp_path / "source.pdf"
    target = tmp_path / "optimized.pdf"
    make_pdf(source)
    state = make_state()
    save_sidecar(source, state)
    original_bytes = source.read_bytes()
    original_sidecar = Path(str(source) + ".neoview.json").read_bytes()
    with fitz.open(source) as doc:
        before = doc[0].get_pixmap().samples
        result = optimize_pdf.optimize_pdf(doc, state, str(source), str(target))
        assert doc.metadata["title"] == "Original title"
        assert doc.page_count == 1
    assert result == str(target)
    assert target.stat().st_size < source.stat().st_size
    assert source.read_bytes() == original_bytes
    assert Path(str(source) + ".neoview.json").read_bytes() == original_sidecar
    assert load_sidecar(target) == state
    with fitz.open(target) as output:
        assert output[0].get_text().strip() == "Lossless source text"
        assert output[0].get_pixmap().samples == before
        assert output.metadata["author"] == "Original author"
        assert output.get_toc() == [[1, "Section", 1]]
        assert len(output[0].get_images()) == 1
        assert list(output[0].annots())[0].info["content"] == "Native note"


def test_run_cancel_does_not_write(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    with fitz.open(source) as doc:
        assert optimize_pdf.run(window_for(doc, source, make_state())) is None
    assert [path for path in tmp_path.iterdir() if path.is_file()] == [source]


def test_run_uses_snapshot_and_normalizes_extension(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    target = tmp_path / "result"
    make_pdf(source)
    doc = fitz.open(source)
    try:
        def choose(*_):
            doc.close()
            return str(target), ""
        monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
        assert optimize_pdf.run(window_for(doc, source, make_state())) == str(target) + ".pdf"
    finally:
        if not doc.is_closed:
            doc.close()
    with fitz.open(str(target) + ".pdf") as output:
        assert output.metadata["title"] == "Original title"
        assert "Lossless source text" in output[0].get_text()


@pytest.mark.parametrize("alias", ["same", "hardlink", "sidecar"])
def test_destination_cannot_overwrite_source_or_sidecar(tmp_path, alias):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    sidecar = Path(str(source) + ".neoview.json")
    save_sidecar(source, make_state())
    destination = tmp_path / "output.pdf"
    if alias == "same":
        destination = source
    elif alias == "hardlink":
        destination.hardlink_to(source)
    else:
        destination = sidecar
    before = source.read_bytes(), sidecar.read_bytes()
    with fitz.open(source) as doc, pytest.raises(ValueError, match="separate destination"):
        optimize_pdf.optimize_pdf(doc, make_state(), str(source), str(destination))
    assert (source.read_bytes(), sidecar.read_bytes()) == before


def test_failed_commit_preserves_existing_output(tmp_path, monkeypatch):
    import neoview.ui.metadata_editor as writer

    source = tmp_path / "source.pdf"
    target = tmp_path / "output.pdf"
    make_pdf(source)
    target.write_bytes(b"existing output")
    original = source.read_bytes()
    real_replace = writer.os.replace

    def fail_destination(first, second):
        if Path(second) == target:
            raise OSError("write denied")
        return real_replace(first, second)

    monkeypatch.setattr(writer.os, "replace", fail_destination)
    with fitz.open(source) as doc, pytest.raises(OSError, match="write denied"):
        optimize_pdf.optimize_pdf(doc, make_state(), str(source), str(target))
    assert source.read_bytes() == original
    assert target.read_bytes() == b"existing output"
    assert not Path(str(target) + ".neoview.json").exists()
    assert not list(tmp_path.glob(".neoview-metadata-*"))


def test_protected_pdf_is_rejected_before_dialog(tmp_path, monkeypatch):
    source = tmp_path / "protected.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(source), encryption=fitz.PDF_ENCRYPT_AES_256,
                 user_pw="reader", owner_pw="owner")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("dialog opened"))
    with fitz.open(source) as doc:
        doc.authenticate("reader")
        with pytest.raises(ValueError, match="password-protected"):
            optimize_pdf.run(window_for(doc, source, make_state()))
