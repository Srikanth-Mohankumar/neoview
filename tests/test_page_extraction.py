from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from neoview.models.page_extraction import extract_pdf_pages, parse_page_ranges
from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import load_sidecar, save_sidecar, sidecar_path_for
from neoview.ui.page_extraction import extract_pages


def make_pdf(path):
    with fitz.open() as doc:
        for label in ("One", "Two", "Three", "Four"):
            doc.new_page().insert_text((72, 72), label)
        doc[2].add_text_annot((30, 30), "Native note")
        doc[2].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(10, 10, 40, 40),
                            "page": 0})
        doc.set_toc([[1, "One", 1], [2, "Two", 2], [1, "Three", 3], [1, "Four", 4]])
        doc.save(str(path))


def test_extract_keeps_requested_order_and_remaps_state(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "selection.pdf"
    make_pdf(source)
    state = DocumentSidecarState(
        annotations=[AnnotationRecord("a", "note", 2, (30, 30, 10, 10)),
                     AnnotationRecord("b", "note", 1, (30, 30, 10, 10))],
        bookmarks=[BookmarkRecord("c", "One", 0, 0), BookmarkRecord("d", "Two", 1, 0)],
    )
    save_sidecar(str(source), state)
    originals = {p: p.read_bytes() for p in (source, Path(sidecar_path_for(str(source))))}
    with fitz.open(source) as doc:
        assert extract_pdf_pages(doc, str(source), state, "3, 1", str(output)) == str(output)
        assert doc.page_count == 4
    with fitz.open(output) as doc:
        assert [p.get_text().strip() for p in doc] == ["Three", "One"]
        assert list(doc[0].annots())[0].info["content"] == "Native note"
        assert doc[0].get_links()[0]["page"] == 1
        assert doc.get_toc() == [[1, "One", 2], [1, "Three", 1]]
    result = load_sidecar(str(output))
    assert [(a.id, a.page) for a in result.annotations] == [("a", 0)]
    assert [(b.id, b.page) for b in result.bookmarks] == [("c", 1)]
    for path, content in originals.items():
        assert path.read_bytes() == content
    assert state.annotations[0].page == 2


@pytest.mark.parametrize("ranges", ["", "0", "5", "2-1", "1,,2", "1-", "1,1", "1-3,2", "a", "1;2"])
def test_invalid_ranges(ranges):
    with pytest.raises(ValueError):
        parse_page_ranges(ranges, 4)


def test_range_parser_preserves_order():
    assert parse_page_ranges(" 4, 1 - 2 ", 4) == [3, 0, 1]


@pytest.mark.parametrize("alias", ["same", "symlink", "hardlink", "sidecar"])
def test_rejects_source_aliases(tmp_path, alias):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    destination = tmp_path / "alias.pdf"
    if alias == "same":
        destination = source
    elif alias == "symlink":
        destination.symlink_to(source)
    elif alias == "hardlink":
        destination.hardlink_to(source)
    else:
        destination = Path(sidecar_path_for(str(source)))
        destination.write_text("source sidecar")
    before = source.read_bytes()
    with fitz.open(source) as doc:
        with pytest.raises(ValueError, match="separately"):
            extract_pdf_pages(doc, str(source), DocumentSidecarState(), "1", str(destination))
    assert source.read_bytes() == before


def test_write_failure_restores_existing_output(tmp_path, monkeypatch):
    import neoview.models.page_organization as module

    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    make_pdf(source)
    output.write_bytes(b"existing output")
    sidecar = Path(sidecar_path_for(str(output)))
    sidecar.write_text("existing sidecar")
    original_replace = module.os.replace

    def fail(source, dest):
        if Path(dest) == sidecar:
            raise OSError("output sidecar cannot be replaced")
        return original_replace(source, dest)

    monkeypatch.setattr(module.os, "replace", fail)
    with fitz.open(source) as doc:
        with pytest.raises(OSError, match="cannot be replaced"):
            extract_pdf_pages(doc, str(source), DocumentSidecarState(), "1", str(output))
    assert output.read_bytes() == b"existing output"
    assert sidecar.read_text() == "existing sidecar"
    assert not list(tmp_path.glob(".neoview-pages-*"))


def test_protected_pdf_rejected(tmp_path):
    source = tmp_path / "protected.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(source), encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader")
    with fitz.open(source) as doc:
        doc.authenticate("reader")
        with pytest.raises(ValueError, match="password-protected"):
            extract_pdf_pages(doc, str(source), DocumentSidecarState(), "1", str(tmp_path / "out.pdf"))


def test_dialog_saves_pdf_and_handles_cancel(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    output = tmp_path / "extracted.pdf"
    make_pdf(source)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("4,1-2", True))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(output), ""))
    with fitz.open(source) as doc:
        assert extract_pages(None, doc, str(source), DocumentSidecarState()) == str(output)
        with fitz.open(output) as saved:
            assert [p.get_text().strip() for p in saved] == ["Four", "One", "Two"]
        monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("1", False))
        assert extract_pages(None, doc, str(source), DocumentSidecarState()) is None
        monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("1", True))
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
        assert extract_pages(None, doc, str(source), DocumentSidecarState()) is None


def test_dialog_reports_invalid_range_before_save_dialog(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("10", True))
    errors = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: errors.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("Invalid ranges reached Save"))
    with fitz.open(source) as doc:
        assert extract_pages(None, doc, str(source), DocumentSidecarState()) is None
    assert "between 1 and 4" in errors[0]


def test_dialog_uses_snapshot_when_viewer_document_closes(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    output = tmp_path / "snapshot.pdf"
    make_pdf(source)
    state = DocumentSidecarState(bookmarks=[BookmarkRecord("b", "Original bookmark", 2, 0)])
    doc = fitz.open(source)

    def choose_ranges(*_):
        # A reload can run during the modal dialog and close the viewer's source.
        doc.close()
        state.bookmarks.clear()
        return "3", True

    monkeypatch.setattr(QInputDialog, "getText", choose_ranges)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(output), ""))
    assert extract_pages(None, doc, str(source), state) == str(output)
    with fitz.open(output) as saved:
        assert saved[0].get_text().strip() == "Three"
    assert [(b.title, b.page) for b in load_sidecar(str(output)).bookmarks] == [("Original bookmark", 0)]
