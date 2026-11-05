import fitz
from PySide6.QtWidgets import QDialog

from neoview.ui.main_window import MainWindow


def test_tagged_pdf_action_guards_and_navigation(tmp_path, qtbot, monkeypatch):
    from neoview.ui.tagged_pdf import TaggedPdfDialog

    window = MainWindow()
    qtbot.addWidget(window)
    assert not window._tagged_pdf_action.isEnabled()
    path = tmp_path / 'tagged.pdf'
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        doc.save(str(path))
    original = path.read_bytes()
    window._open_file(str(path))
    assert window._tagged_pdf_action.isEnabled()
    view = window.current_view()
    visited = []
    monkeypatch.setattr(view, 'go_to_page', visited.append)

    def execute(dialog):
        assert isinstance(dialog, TaggedPdfDialog)
        dialog.page_requested.emit(1)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TaggedPdfDialog, 'exec', execute)
    window._tagged_pdf_action.trigger()
    assert window._sidebar.current_key() == 'tags'
    window._inspect_tagged_pdf()
    assert visited == [1]
    assert path.read_bytes() == original
    window._close_current_tab()
    assert not window._tagged_pdf_action.isEnabled()


def test_editor_action_saves_and_opens_copy(tmp_path, qtbot, monkeypatch):
    from neoview.models.view_state import DocumentSidecarState
    from neoview.ui.tagged_pdf_editor import TaggedPdfEditorDialog
    from neoview.ui.tool_support import save_copy

    source, target = tmp_path / 'source.pdf', tmp_path / 'copy.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), 'Decorative page')
        doc.save(str(source))
    original = source.read_bytes()
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window._tagged_pdf_edit_action.isEnabled()
    window._open_file(str(source))
    assert window._tagged_pdf_edit_action.isEnabled()

    def execute(dialog):
        from neoview.models.tagged_pdf_content import mark_page_as_artifact
        mark_page_as_artifact(dialog.document, 0)
        dialog.saved_path = save_copy(dialog.document, DocumentSidecarState(),
                                      str(source), str(target))
        dialog.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TaggedPdfEditorDialog, 'exec', execute)
    window._tagged_pdf_edit_action.trigger()
    assert window.current_context().file_path == str(target)
    assert source.read_bytes() == original
    assert b'/Artifact BMC' in window.current_view().document[0].read_contents()
