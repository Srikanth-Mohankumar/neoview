from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog

from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import load_sidecar, save_sidecar
from neoview.ui.tools.reverse_pages import reverse_pdf, run


def make_pdf(path):
    with fitz.open() as doc:
        for label in ("First", "Second", "Third"):
            doc.new_page().insert_text((72, 72), label)
        doc.set_toc([[1, "First", 1], [2, "Second", 2], [1, "Third", 3]])
        page = doc[0]
        page.add_text_annot((40, 40), "Native note")
        doc.save(str(path))


def state():
    return DocumentSidecarState(
        annotations=[AnnotationRecord("annotation", "note", 0, (10, 20, 30, 40))],
        bookmarks=[BookmarkRecord("bookmark", "Third", 2, 0)],
    )


def test_reverse_keeps_native_content_outlines_and_remaps_sidecar(tmp_path):
    source = tmp_path / "source.pdf"
    target = tmp_path / "reverse.pdf"
    make_pdf(source)
    original_state = state()
    save_sidecar(source, original_state)
    source_bytes = source.read_bytes()
    source_sidecar = Path(str(source) + ".neoview.json").read_bytes()
    with fitz.open(source) as doc:
        assert reverse_pdf(doc, original_state, str(source), str(target)) == str(target)
        assert doc[0].get_text().strip() == "First"
    with fitz.open(target) as doc:
        assert [p.get_text().strip() for p in doc] == ["Third", "Second", "First"]
        assert doc.get_toc() == [[1, "First", 3], [2, "Second", 2], [1, "Third", 1]]
        assert list(doc[2].annots())[0].info["content"] == "Native note"
    result = load_sidecar(target)
    assert result.annotations[0].page == 2
    assert result.bookmarks[0].page == 0
    assert original_state.annotations[0].page == 0
    assert original_state.bookmarks[0].page == 2
    assert source.read_bytes() == source_bytes
    assert Path(str(source) + ".neoview.json").read_bytes() == source_sidecar


@pytest.mark.parametrize("destination", ["pdf", "sidecar", "hardlink"])
def test_reverse_rejects_source_aliases(tmp_path, destination):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    save_sidecar(source, state())
    target = source if destination == "pdf" else Path(str(source) + ".neoview.json")
    if destination == "hardlink":
        target = tmp_path / "hardlink.pdf"
        try:
            target.hardlink_to(source)
        except OSError:
            pytest.skip("Hard links unavailable")
    before = source.read_bytes()
    with fitz.open(source) as doc, pytest.raises(ValueError, match="separately"):
        reverse_pdf(doc, state(), str(source), str(target))
    assert source.read_bytes() == before


def test_reverse_refuses_encrypted_documents(tmp_path):
    source = tmp_path / "encrypted.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(source), encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="owner", user_pw="reader")
    with fitz.open(source) as doc:
        doc.authenticate("reader")
        with pytest.raises(ValueError, match="password-protected"):
            reverse_pdf(doc, state(), str(source), str(tmp_path / "target.pdf"))


def test_run_cancellation_leaves_source_unchanged(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    with fitz.open(source) as doc:
        context = SimpleNamespace(file_path=str(source), sidecar_state=state())
        window = SimpleNamespace(current_view=lambda: SimpleNamespace(document=doc),
                                 current_context=lambda: context)
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
        assert run(window) is None
        assert doc.page_count == 3
    assert list(tmp_path.glob("*.pdf")) == [source]
    assert not list(tmp_path.glob("*.neoview.json"))


def test_run_snapshot_survives_viewer_reload(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    target = tmp_path / "target.pdf"
    make_pdf(source)
    doc = fitz.open(source)
    original_state = state()
    context = SimpleNamespace(file_path=str(source), sidecar_state=original_state)
    window = SimpleNamespace(current_view=lambda: SimpleNamespace(document=doc),
                             current_context=lambda: context)

    def choose(*_):
        doc.close()
        original_state.annotations.clear()
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    assert run(window) == str(target)
    with fitz.open(target) as output:
        assert output[0].get_text().strip() == "Third"
    assert load_sidecar(target).annotations[0].page == 2


def test_save_failure_restores_existing_output(tmp_path, monkeypatch):
    import neoview.models.page_organization as organization

    source = tmp_path / "source.pdf"
    target = tmp_path / "target.pdf"
    make_pdf(source)
    make_pdf(target)
    save_sidecar(target, state())
    sidecar = Path(str(target) + ".neoview.json")
    before_pdf, before_state = target.read_bytes(), sidecar.read_bytes()
    original_replace = organization.os.replace

    def failing_replace(first, second):
        if Path(second) == sidecar:
            raise OSError("simulated sidecar failure")
        return original_replace(first, second)

    monkeypatch.setattr(organization.os, "replace", failing_replace)
    with fitz.open(source) as doc, pytest.raises(OSError, match="simulated"):
        reverse_pdf(doc, state(), str(source), str(target))
    assert target.read_bytes() == before_pdf
    assert sidecar.read_bytes() == before_state
    assert not list(tmp_path.glob(".neoview-pages-*"))
