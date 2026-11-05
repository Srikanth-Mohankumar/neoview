import fitz
import pytest
from PySide6.QtWidgets import QDialog, QMessageBox

from neoview.models.tagged_pdf import inspect_tagged_pdf
from neoview.models.view_state import DocumentSidecarState
from neoview.ui.tagged_pdf_editor import TaggedPdfEditorDialog


def tagged_source(path):
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), 'First second')
        root, first, second = [doc.get_new_xref() for _ in range(3)]
        doc.update_object(root, f'<< /Type /StructTreeRoot /K [{first} 0 R {second} 0 R] >>')
        for xref in (first, second):
            doc.update_object(xref, f'<< /Type /StructElem /S /P /P {root} 0 R '
                              f'/Pg {doc.page_xref(0)} 0 R >>')
        doc.xref_set_key(doc.pdf_catalog(), 'StructTreeRoot', f'{root} 0 R')
        doc.xref_set_key(doc.pdf_catalog(), 'MarkInfo', '<< /Marked true >>')
        doc.save(str(path))
    return first, second


def test_editor_edits_moves_undo_redo_and_saves_separate_copy(tmp_path, qtbot, monkeypatch):
    source = tmp_path / 'source.pdf'
    target = tmp_path / 'copy.pdf'
    first, second = tagged_source(source)
    original = source.read_bytes()
    with fitz.open(source) as doc:
        dialog = TaggedPdfEditorDialog(doc, DocumentSidecarState(), str(source))
        qtbot.addWidget(dialog)
        assert not dialog.document.name
        dialog.fields['role'].setText('Figure')
        dialog.fields['alt_text'].setText('Meaningful image description')
        assert dialog._apply_tag()
        assert inspect_tagged_pdf(doc).reading_order[0].role == 'P'
        assert dialog.report.reading_order[0].alt_text == 'Meaningful image description'
        dialog._move(1)
        assert [n.xref for n in dialog.report.nodes] == [second, first]
        dialog._undo_change()
        assert [n.xref for n in dialog.report.nodes] == [first, second]
        dialog._redo_change()
        assert [n.xref for n in dialog.report.nodes] == [second, first]
        monkeypatch.setattr('neoview.ui.tagged_pdf_editor.choose_file', lambda *_: str(target))
        dialog._save()
        assert dialog.saved_path == str(target)
        assert dialog.document.is_closed
    assert source.read_bytes() == original
    with fitz.open(target) as result:
        report = inspect_tagged_pdf(result)
        assert [n.xref for n in report.nodes] == [second, first]
        assert report.nodes[1].alt_text == 'Meaningful image description'


def test_editor_rolls_back_failed_edits_and_source_alias_save(tmp_path, qtbot, monkeypatch):
    source = tmp_path / 'source.pdf'
    tagged_source(source)
    original = source.read_bytes()
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *args: warnings.append(args[-1]))
    with fitz.open(source) as doc:
        dialog = TaggedPdfEditorDialog(doc, DocumentSidecarState(), str(source))
        qtbot.addWidget(dialog)
        dialog.fields['role'].setText('Invalid role!')
        assert not dialog._apply_tag()
        assert not dialog._undo
        assert inspect_tagged_pdf(dialog.document).nodes[0].role == 'P'
        monkeypatch.setattr('neoview.ui.tagged_pdf_editor.choose_file', lambda *_: str(source))
        dialog._fields_dirty = False
        dialog._save()
        assert dialog.saved_path is None
        assert warnings
        dialog.done(QDialog.DialogCode.Rejected)
    assert source.read_bytes() == original


def test_editor_mark_artifact_undo_and_confirm_discard(tmp_path, qtbot, monkeypatch):
    source = tmp_path / 'plain.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), 'Decorative content')
        doc.save(str(source))
    original = source.read_bytes()
    monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.Yes)
    with fitz.open(source) as doc:
        dialog = TaggedPdfEditorDialog(doc, DocumentSidecarState(), str(source))
        qtbot.addWidget(dialog)
        dialog._mark_artifact()
        assert inspect_tagged_pdf(dialog.document).artifacts[0].count == 1
        dialog._unmark_artifact()
        assert inspect_tagged_pdf(dialog.document).artifacts[0].count == 0
        dialog._undo_change()
        assert inspect_tagged_pdf(dialog.document).artifacts[0].count == 1
        dialog.reject()
        assert dialog.document.is_closed
    assert source.read_bytes() == original


def test_editor_refuses_signature_fields_before_snapshot(tmp_path):
    source = tmp_path / 'signed.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        widget = fitz.Widget()
        widget.field_name = 'Signature1'
        widget.field_type = fitz.PDF_WIDGET_TYPE_SIGNATURE
        widget.rect = fitz.Rect(10, 10, 50, 30)
        page.add_widget(widget)
        doc.save(str(source))
    with fitz.open(source) as doc:
        with pytest.raises(ValueError, match='signature'):
            TaggedPdfEditorDialog(doc, DocumentSidecarState(), str(source))


def test_pending_fields_can_cancel_artifact_and_history_operations(tmp_path, qtbot, monkeypatch):
    source = tmp_path / 'source.pdf'
    tagged_source(source)
    with fitz.open(source) as doc:
        dialog = TaggedPdfEditorDialog(doc, DocumentSidecarState(), str(source))
        qtbot.addWidget(dialog)
        dialog.fields['title'].setText('Pending title')
        dialog._fields_dirty = True
        monkeypatch.setattr(QMessageBox, 'question', lambda *_: QMessageBox.StandardButton.Cancel)
        for operation in (dialog._mark_artifact, dialog._unmark_artifact,
                          dialog._undo_change, dialog._redo_change):
            operation()
            assert dialog._fields_dirty
            assert dialog.fields['title'].text() == 'Pending title'
            assert not dialog._undo
        dialog.done(QDialog.DialogCode.Rejected)
        # Teardown must never prompt again after the working document is closed.
        monkeypatch.setattr(QMessageBox, 'question', lambda *_: pytest.fail('closed dialog prompted'))
        dialog.reject()


def test_unchanged_custom_role_can_edit_alternate_text(tmp_path, qtbot):
    source = tmp_path / 'source.pdf'
    first, _ = tagged_source(source)
    with fitz.open(source) as doc:
        doc.xref_set_key(first, 'S', '/Custom')
        dialog = TaggedPdfEditorDialog(doc, DocumentSidecarState(), str(source))
        qtbot.addWidget(dialog)
        dialog.fields['alt_text'].setText('Text for custom tag')
        assert dialog._apply_tag()
        node = next(n for n in dialog.report.nodes if n.xref == first)
        assert node.role == 'Custom'
        assert node.alt_text == 'Text for custom tag'
        dialog.done(QDialog.DialogCode.Rejected)
