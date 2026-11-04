from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.models.page_organization import PageOrganization
from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import load_sidecar, save_sidecar
from neoview.ui.main_window import MainWindow
from neoview.ui.page_organizer import PageOrganizer


def make_pdf(path, labels=("A", "B", "C")):
    with fitz.open() as doc:
        for label in labels:
            page = doc.new_page()
            page.insert_text((72, 72), label)
        doc.set_toc([[1, label, idx + 1] for idx, label in enumerate(labels)])
        doc.save(str(path))


def labels(path):
    with fitz.open(path) as doc:
        return [page.get_text().strip() for page in doc]


def test_merge_reorder_delete_save_preserves_state_and_source(tmp_path):
    original = tmp_path / "original.pdf"
    incoming = tmp_path / "incoming.pdf"
    output = tmp_path / "organized.pdf"
    make_pdf(original)
    make_pdf(incoming, ("D", "E"))
    state = DocumentSidecarState(
        annotations=[AnnotationRecord("note", "note", 1, (20, 20, 10, 10))],
        bookmarks=[BookmarkRecord("bookmark", "C", 2, 0)],
    )
    save_sidecar(incoming, DocumentSidecarState(
        bookmarks=[BookmarkRecord("bookmark", "D", 0, 0)]
    ))
    before = original.read_bytes()
    with fitz.open(original) as source:
        session = PageOrganization(source, state)
        session.insert(str(incoming), 1)
        assert session.order == [0, 3, 4, 1, 2]
        session.reorder([2, 0, 3, 4, 1])
        session.delete([1, 3])
        assert original.read_bytes() == before
        assert source.page_count == 3
        session.save(str(output))
        assert not session.dirty
        session.close()
    assert original.read_bytes() == before
    assert labels(output) == ["C", "D", "B"]
    result = load_sidecar(output)
    assert result.annotations[0].page == 2
    assert [(b.title, b.page) for b in result.bookmarks] == [("C", 0), ("D", 1)]
    assert len({b.id for b in result.bookmarks}) == 2
    with fitz.open(output) as doc:
        assert doc.get_toc() == [[1, "B", 3], [1, "C", 1], [1, "D", 2]]


def test_invalid_edits_do_not_change_session(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    with fitz.open(source) as doc:
        session = PageOrganization(doc, DocumentSidecarState())
    with pytest.raises(ValueError):
        session.delete([0, 1, 2])
    with pytest.raises(ValueError):
        session.reorder([0, 0, 1])
    with pytest.raises(ValueError):
        session.delete([-1])
    assert session.order == [0, 1, 2]
    assert not session.dirty
    session.close()


def test_failed_save_rolls_back_pdf_and_sidecar(tmp_path, monkeypatch):
    import neoview.models.page_organization as module

    path = tmp_path / "source.pdf"
    make_pdf(path)
    state = DocumentSidecarState(bookmarks=[BookmarkRecord("b", "B", 1, 0)])
    save_sidecar(path, state)
    before_pdf = path.read_bytes()
    sidecar = Path(str(path) + ".neoview.json")
    before_sidecar = sidecar.read_bytes()
    with fitz.open(path) as doc:
        session = PageOrganization(doc, state)
    session.delete([0])
    real_replace = module.os.replace

    def fail_sidecar(source, destination):
        if Path(destination) == sidecar:
            raise OSError("simulated replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_sidecar)
    with pytest.raises(OSError, match="simulated"):
        session.save(str(path))
    assert path.read_bytes() == before_pdf
    assert sidecar.read_bytes() == before_sidecar
    assert session.dirty
    session.close()


def test_organizer_buttons_and_discard(tmp_path, qtbot, monkeypatch):
    path = tmp_path / "source.pdf"
    make_pdf(path)
    with fitz.open(path) as doc:
        session = PageOrganization(doc, DocumentSidecarState())
    dialog = PageOrganizer(session, str(path))
    qtbot.addWidget(dialog)
    dialog.pages.setCurrentRow(1)
    dialog._move(-1)
    assert session.order == [1, 0, 2]
    dialog._delete()
    assert session.order == [0, 2]
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Cancel)
    dialog.reject()
    assert dialog.result() == 0
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Discard)
    dialog.reject()
    assert labels(path) == ["A", "B", "C"]
    session.close()


def test_main_window_organizer_save_reloads_remapped_sidecar(tmp_path, qtbot, monkeypatch):
    path = tmp_path / "source.pdf"
    make_pdf(path)
    save_sidecar(path, DocumentSidecarState(bookmarks=[BookmarkRecord("b", "B", 1, 0)]))
    win = MainWindow()
    qtbot.addWidget(win)
    assert not win._organize_pages_action.isEnabled()
    win._open_file(str(path))
    assert win._organize_pages_action.isEnabled()

    def edit_and_save(dialog):
        dialog.session.delete([0])
        monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
        dialog._save(False)
        return dialog.result()

    monkeypatch.setattr(PageOrganizer, "exec", edit_and_save)
    win._organize_pages_action.trigger()
    assert labels(path) == ["B", "C"]
    assert win.current_view().page_count == 2
    assert win.current_context().sidecar_state.bookmarks[0].page == 0
    win._save_sidecar_for_view(win.current_view())
    assert load_sidecar(path).bookmarks[0].page == 0


def test_save_as_cancel_and_success(tmp_path, qtbot, monkeypatch):
    path = tmp_path / "source.pdf"
    output = tmp_path / "copy.pdf"
    make_pdf(path)
    with fitz.open(path) as doc:
        session = PageOrganization(doc, DocumentSidecarState())
    dialog = PageOrganizer(session, str(path))
    qtbot.addWidget(dialog)
    session.reorder([2, 1, 0])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    dialog._save(True)
    assert dialog.saved_path is None
    assert session.dirty
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(output), ""))
    dialog._save(True)
    assert labels(output) == ["C", "B", "A"]
    assert labels(path) == ["A", "B", "C"]
    session.close()


def test_drag_reorder_updates_session(tmp_path, qtbot):
    path = tmp_path / "source.pdf"
    make_pdf(path)
    with fitz.open(path) as doc:
        session = PageOrganization(doc, DocumentSidecarState())
    dialog = PageOrganizer(session, str(path))
    qtbot.addWidget(dialog)
    assert dialog.pages.model().moveRow(dialog.pages.rootIndex(), 0,
                                        dialog.pages.rootIndex(), 3)
    assert session.order == [1, 2, 0]
    assert dialog.pages.item(0).data(Qt.ItemDataRole.UserRole) == 1
    session.close()


def test_native_annotations_and_links_follow_pages(tmp_path):
    path = tmp_path / "source.pdf"
    make_pdf(path)
    with fitz.open(path) as doc:
        doc[1].add_text_annot((40, 40), "native note")
        doc[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(10, 10, 80, 80),
                            "page": 1})
        session = PageOrganization(doc, DocumentSidecarState())
    session.reorder([1, 0, 2])
    output = tmp_path / "output.pdf"
    session.save(str(output))
    session.close()
    with fitz.open(output) as doc:
        assert list(doc[0].annots())[0].info["content"] == "native note"
        assert doc[1].get_links()[0]["page"] == 0


def test_encrypted_pdf_is_not_silently_decrypted(tmp_path):
    path = tmp_path / "encrypted.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="owner", user_pw="reader")
    with fitz.open(path) as doc:
        doc.authenticate("reader")
        with pytest.raises(ValueError, match="password-protected"):
            PageOrganization(doc, DocumentSidecarState())


def test_external_change_blocks_overwrite(tmp_path, qtbot, monkeypatch):
    path = tmp_path / "source.pdf"
    make_pdf(path)
    with fitz.open(path) as doc:
        session = PageOrganization(doc, DocumentSidecarState())
    dialog = PageOrganizer(session, str(path))
    qtbot.addWidget(dialog)
    session.delete([0])
    make_pdf(path, ("replacement",))
    warnings = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    dialog._save(False)
    assert warnings and "changed" in warnings[0]
    assert labels(path) == ["replacement"]
    assert session.dirty
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Discard)
    dialog.reject()
    session.close()
