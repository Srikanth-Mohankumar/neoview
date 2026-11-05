"""Page-range selection refers to displayed organizer positions."""
import copy

import fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox, QPushButton

from neoview.models.page_organization import PageOrganization
from neoview.models.view_state import BookmarkRecord, DocumentSidecarState
from neoview.ui.page_organizer import PageOrganizer


def make_pdf(path, labels):
    with fitz.open() as document:
        for label in labels:
            document.new_page().insert_text((72, 72), label)
        document.save(path)


@pytest.fixture
def organizer(tmp_path, qtbot):
    path = tmp_path / "source.pdf"
    make_pdf(path, "ABCDE")
    source_bytes = path.read_bytes()
    state = DocumentSidecarState(bookmarks=[BookmarkRecord("mark", "A", 0, 0)])
    with fitz.open(path) as document:
        session = PageOrganization(document, state)
    dialog = PageOrganizer(session, str(path))
    qtbot.addWidget(dialog)
    yield dialog, session, path
    session.close()
    assert path.read_bytes() == source_bytes
    assert state.bookmarks[0].page == 0


def select(monkeypatch, dialog, text):
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: (text, True))
    button = next(button for button in dialog.findChildren(QPushButton)
                  if button.text() == "Select Pages...")
    button.click()


@pytest.mark.parametrize("edited", [False, True])
def test_selection_preserves_backend_and_anchors_first_entered_page(
    organizer, monkeypatch, edited, tmp_path,
):
    dialog, session, _ = organizer
    if edited:
        incoming = tmp_path / "incoming.pdf"
        make_pdf(incoming, "XY")
        session.reorder([4, 2, 0, 3, 1])
        session.delete([1, 3])
        session.insert(str(incoming), 1)
        assert session.order == [4, 5, 6, 0, 1]
        dialog._refresh()
    before = (session.order.copy(), copy.deepcopy(session.state), session.dirty,
              session.document.tobytes(no_new_id=True))
    select(monkeypatch, dialog, "4, 1-2")
    assert dialog._rows() == [0, 1, 3]
    assert len(dialog.pages.selectedItems()) == 3
    assert dialog.pages.currentRow() == 3
    assert [dialog.pages.item(row).data(Qt.ItemDataRole.UserRole)
            for row in dialog._rows()] == [session.order[row] for row in (0, 1, 3)]
    assert (session.order, session.state, session.dirty, session.document.tobytes(no_new_id=True)) == before


@pytest.mark.parametrize("text", ["", "0", "6", "3-1", "1, 1", "bad"])
def test_invalid_ranges_preserve_prior_selection(organizer, monkeypatch, text):
    dialog, session, _ = organizer
    dialog.pages.setCurrentRow(2)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    select(monkeypatch, dialog, text)
    assert dialog._rows() == [2]
    assert dialog.pages.currentRow() == 2
    assert not session.dirty
    assert len(warnings) == 1


def test_deleted_rows_limit_range_validation(organizer, monkeypatch):
    dialog, session, _ = organizer
    session.delete([0, 1, 2])
    dialog._refresh([0])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    select(monkeypatch, dialog, "3")
    assert dialog._rows() == [0]
    assert session.order == [3, 4]
    assert len(warnings) == 1


@pytest.mark.parametrize("fails", [False, True])
def test_cancel_or_dialog_failure_preserves_selection(organizer, monkeypatch, fails):
    dialog, session, _ = organizer
    dialog.pages.setCurrentRow(1)
    warnings = []

    def prompt(*args):
        if fails:
            raise RuntimeError("Dialog unavailable")
        return "1-3", False

    monkeypatch.setattr(QInputDialog, "getText", prompt)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    dialog._select_pages()
    assert dialog._rows() == [1]
    assert dialog.pages.currentRow() == 1
    assert not session.dirty
    assert len(warnings) == int(fails)


def test_selected_displayed_pages_can_move_and_delete(organizer, monkeypatch):
    dialog, session, _ = organizer
    session.reorder([4, 3, 2, 1, 0])
    dialog._refresh()
    select(monkeypatch, dialog, "2-3")
    dialog._move(-1)
    assert session.order == [3, 2, 4, 1, 0]
    assert dialog._rows() == [0, 1]
    dialog._delete()
    assert session.order == [4, 1, 0]
    assert session.dirty
