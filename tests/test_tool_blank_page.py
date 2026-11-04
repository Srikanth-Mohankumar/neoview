from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog

from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import load_sidecar
from neoview.ui.tools import blank_page


def make_pdf(path):
    with fitz.open() as doc:
        for text in ("First", "Second", "Third"):
            page = doc.new_page()
            page.insert_text((72, 72), text)
            page.add_text_annot((90, 90), text + " note")
        doc[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(10, 10, 50, 50), "page": 2})
        doc.set_metadata({"title": "Original", "producer": "Example"})
        doc.set_toc([[1, "First", 1], [1, "Second", 2], [2, "Third", 3]])
        doc.save(str(path))


def state():
    return DocumentSidecarState(
        annotations=[AnnotationRecord("note", "note", 1, (20, 20, 10, 10), contents="Editable")],
        bookmarks=[BookmarkRecord("mark", "Third", 2, 40)],
    )


def fake_window(document, source, sidecar_state):
    return SimpleNamespace(
        current_view=lambda: SimpleNamespace(document=document),
        current_context=lambda: SimpleNamespace(file_path=str(source), sidecar_state=sidecar_state),
    )


@pytest.mark.parametrize("position", [1, 2, 4])
def test_insert_preserves_source_and_remaps_document(tmp_path, position):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    original = source.read_bytes()
    original_state = state()
    with fitz.open(source) as doc:
        output, remapped = blank_page.insert_blank_page(doc, original_state, position)
        with output:
            assert output.page_count == 4
            assert output[position - 1].get_text() == ""
            assert output[position - 1].rect.width == 595
            assert output[position - 1].rect.height == 842
            assert output.metadata["title"] == "Original"
            expected = ["First", "Second", "Third"]
            expected.insert(position - 1, "")
            assert [p.get_text().strip() for p in output] == expected
            assert remapped.annotations[0].page == 1 + (position <= 2)
            assert remapped.bookmarks[0].page == 2 + (position <= 3)
            expected_toc = [[1, "First", 1 + (position <= 1)],
                            [1, "Second", 2 + (position <= 2)],
                            [2, "Third", 3 + (position <= 3)]]
            assert output.get_toc() == expected_toc
            first_index = 0 + (position <= 1)
            assert output[first_index].get_links()[0]["page"] == 2 + (position <= 3)
            original_index = 1 + (position <= 2)
            assert list(output[original_index].annots())[0].info["content"] == "Second note"
        assert doc.page_count == 3
    assert source.read_bytes() == original
    assert original_state.annotations[0].page == 1
    assert original_state.bookmarks[0].page == 2


@pytest.mark.parametrize("position", [0, -1, 5, 1.5, True])
def test_invalid_position_has_no_effect(tmp_path, position):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    with fitz.open(source) as doc, pytest.raises(ValueError, match="position"):
        blank_page.insert_blank_page(doc, state(), position)
        assert doc.page_count == 3


def test_run_saves_sidecar_and_pdf(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    target = tmp_path / "output.pdf"
    make_pdf(source)
    monkeypatch.setattr(QInputDialog, "getInt", lambda *_: (2, True))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    # The supplied parent is a lightweight controller; QFileDialog is mocked.
    with fitz.open(source) as doc:
        assert blank_page.run(fake_window(doc, source, state())) == str(target)
    with fitz.open(target) as output:
        assert output.page_count == 4
        assert output[1].get_text() == ""
    assert load_sidecar(target).annotations[0].page == 2
    assert load_sidecar(target).bookmarks[0].page == 3


@pytest.mark.parametrize("cancel_stage", ["position", "destination"])
def test_run_cancel_writes_nothing(tmp_path, monkeypatch, cancel_stage):
    source = tmp_path / "source.pdf"
    target = tmp_path / "output.pdf"
    make_pdf(source)
    monkeypatch.setattr(QInputDialog, "getInt", lambda *_: (2, cancel_stage != "position"))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    with fitz.open(source) as doc:
        assert blank_page.run(fake_window(doc, source, state())) is None
    assert not target.exists()
    assert [p for p in tmp_path.iterdir() if p.is_file()] == [source]


def test_run_rejects_source_alias(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    alias = tmp_path / "alias.pdf"
    alias.hardlink_to(source)
    original = source.read_bytes()
    monkeypatch.setattr(QInputDialog, "getInt", lambda *_: (2, True))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(alias), ""))
    with fitz.open(source) as doc, pytest.raises(ValueError, match="separate"):
        blank_page.run(fake_window(doc, source, state()))
    assert source.read_bytes() == original


def test_protected_document_is_rejected(tmp_path):
    source = tmp_path / "protected.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(source), encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="owner", user_pw="reader")
    with fitz.open(source) as doc:
        doc.authenticate("reader")
        with pytest.raises(ValueError, match="password-protected"):
            blank_page.insert_blank_page(doc, state(), 1)
