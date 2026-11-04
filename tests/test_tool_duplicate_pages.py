from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QWidget

from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import load_sidecar, save_sidecar, sidecar_path_for
from neoview.ui.tools.duplicate_pages import duplicate_pdf, run


def make_pdf(path):
    with fitz.open() as doc:
        for label in ("One", "Two", "Three", "Four"):
            doc.new_page().insert_text((72, 72), label)
        doc[1].add_text_annot((30, 30), "native")
        doc[1].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(10, 10, 40, 40),
                            "page": 0})
        doc.set_toc([[1, "One", 1], [2, "Two", 2], [1, "Four", 4]])
        doc.save(str(path))


def state():
    return DocumentSidecarState(
        annotations=[AnnotationRecord("a", "note", 1, (10, 10, 20, 20))],
        bookmarks=[BookmarkRecord("b", "Two", 1, 0), BookmarkRecord("c", "Four", 3, 0)],
    )


def test_duplicate_preserves_entered_order_and_remaps_records(tmp_path):
    source, target = tmp_path / "source.pdf", tmp_path / "copy.pdf"
    make_pdf(source)
    records = state()
    save_sidecar(source, records)
    before = source.read_bytes(), Path(sidecar_path_for(source)).read_bytes()
    with fitz.open(source) as doc:
        assert duplicate_pdf(doc, str(source), records, "2, 1", str(target)) == str(target)
        assert doc.page_count == 4
    with fitz.open(target) as doc:
        assert [page.get_text().strip() for page in doc] == [
            "One", "Two", "Two", "One", "Three", "Four",
        ]
        assert list(doc[1].annots())[0].info["content"] == "native"
        assert list(doc[2].annots())[0].info["content"] == "native"
        assert doc[1].get_links()[0]["page"] == 0
        assert doc[2].get_links()[0]["page"] == 3
        assert doc.get_toc() == [
            [1, "One", 1], [2, "Two", 2], [1, "Four", 6],
            [1, "One (copy)", 4], [2, "Two (copy)", 3],
        ]
    remapped = load_sidecar(target)
    assert [a.page for a in remapped.annotations] == [1, 2]
    assert remapped.annotations[0].id == "a"
    assert remapped.annotations[1].id != "a"
    assert [(b.title, b.page) for b in remapped.bookmarks] == [("Two", 1), ("Four", 5), ("Two", 2)]
    assert len({b.id for b in remapped.bookmarks}) == 3
    assert records.bookmarks[1].page == 3
    assert (source.read_bytes(), Path(sidecar_path_for(source)).read_bytes()) == before


@pytest.mark.parametrize("ranges", ["", "1,1", "5", "0", "3-2"])
def test_invalid_ranges_leave_output_untouched(tmp_path, ranges):
    source, target = tmp_path / "source.pdf", tmp_path / "copy.pdf"
    make_pdf(source)
    target.write_bytes(b"existing")
    with fitz.open(source) as doc, pytest.raises(ValueError):
        duplicate_pdf(doc, str(source), state(), ranges, str(target))
    assert target.read_bytes() == b"existing"


def test_source_alias_rejected(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    before = source.read_bytes()
    with fitz.open(source) as doc, pytest.raises(ValueError, match="separate"):
        duplicate_pdf(doc, str(source), state(), "1", str(source))
    assert source.read_bytes() == before


def test_protected_pdf_rejected_before_copy(tmp_path):
    source = tmp_path / "protected.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(source), encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="owner", user_pw="reader")
    with fitz.open(source) as doc:
        doc.authenticate("reader")
        with pytest.raises(ValueError, match="password"):
            duplicate_pdf(doc, str(source), DocumentSidecarState(), "1", str(tmp_path / "out.pdf"))


class Window(QWidget):
    def __init__(self, document, source, records):
        super().__init__()
        self.view = SimpleNamespace(document=document)
        self.context = SimpleNamespace(file_path=str(source), sidecar_state=records)

    def current_view(self):
        return self.view

    def current_context(self):
        return self.context


def test_dialog_success_uses_snapshot(tmp_path, qtbot, monkeypatch):
    source, target = tmp_path / "source.pdf", tmp_path / "copy.pdf"
    make_pdf(source)
    document = fitz.open(source)
    window = Window(document, source, state())
    qtbot.addWidget(window)

    def choose_ranges(*_):
        document.close()
        window.context.sidecar_state.annotations.clear()
        return "2", True

    monkeypatch.setattr(QInputDialog, "getText", choose_ranges)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    assert run(window) == str(target)
    with fitz.open(target) as output:
        assert output.page_count == 5
    assert len(load_sidecar(target).annotations) == 2


@pytest.mark.parametrize("cancel_at", ["ranges", "destination"])
def test_dialog_cancellation_does_not_write(tmp_path, qtbot, monkeypatch, cancel_at):
    source, target = tmp_path / "source.pdf", tmp_path / "copy.pdf"
    make_pdf(source)
    with fitz.open(source) as document:
        window = Window(document, source, state())
        qtbot.addWidget(window)
        monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("1", cancel_at != "ranges"))
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
        assert run(window) is None
    assert not target.exists()
