from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import load_sidecar
from neoview.ui.metadata_editor import MetadataEditor, edit_metadata, save_metadata_copy


def make_pdf(path):
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 40), "Original content")
        page.add_text_annot((70, 70), "Native note")
        doc.set_metadata({"title": "Old title", "author": "Original author",
                          "producer": "Original producer", "creationDate": "D:20260101000000"})
        doc.set_toc([[1, "Section", 1]])
        doc.save(str(path))


def state():
    return DocumentSidecarState(
        annotations=[AnnotationRecord("note", "note", 0, (10, 10, 20, 20), contents="Sidecar note",
                                      created_at="2026-01-01T00:00:00+00:00",
                                      updated_at="2026-01-01T00:00:00+00:00")],
        bookmarks=[BookmarkRecord("bookmark", "Marked page", 0, 10,
                                  created_at="2026-01-01T00:00:00+00:00")],
    )


def test_metadata_copy_preserves_content_and_original(tmp_path):
    source = tmp_path / "source.pdf"
    output = tmp_path / "copy.pdf"
    make_pdf(source)
    before = source.read_bytes()
    with fitz.open(source) as doc:
        result = save_metadata_copy(doc, str(source), str(output), {
            "title": "New title", "author": "New author", "subject": "", "keywords": "PDF, review",
        }, state())
        assert doc.metadata["title"] == "Old title"
    assert result == str(output)
    assert source.read_bytes() == before
    with fitz.open(output) as doc:
        assert doc.metadata["title"] == "New title"
        assert doc.metadata["producer"] == "Original producer"
        assert doc.metadata["creationDate"] == "D:20260101000000"
        assert doc.metadata["subject"] == ""
        assert doc.metadata["keywords"] == "PDF, review"
        assert "Original content" in doc[0].get_text()
        assert list(doc[0].annots())[0].info["content"] == "Native note"
        assert doc.get_toc() == [[1, "Section", 1]]
    assert load_sidecar(str(output)) == state()


@pytest.mark.parametrize("kind", ["same", "symlink", "hardlink", "sidecar", "sidecar-hardlink"])
def test_source_and_sidecar_aliases_are_rejected(tmp_path, kind):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    sidecar = Path(str(source) + ".neoview.json")
    sidecar.write_text("original sidecar")
    destination = tmp_path / "alias.pdf"
    if kind == "same":
        destination = source
    elif kind == "symlink":
        destination.symlink_to(source)
    elif kind == "hardlink":
        destination.hardlink_to(source)
    elif kind == "sidecar":
        destination = sidecar
    else:
        destination.hardlink_to(sidecar)
    with fitz.open(source) as doc, pytest.raises(ValueError, match="separate destination"):
        save_metadata_copy(doc, str(source), str(destination), {"title": "new"}, state())
    assert sidecar.read_text() == "original sidecar"
    with fitz.open(source) as doc:
        assert doc.metadata["title"] == "Old title"


def test_failed_sidecar_commit_restores_existing_output(tmp_path, monkeypatch):
    import neoview.ui.metadata_editor as module

    source = tmp_path / "source.pdf"
    make_pdf(source)
    output = tmp_path / "copy.pdf"
    output.write_bytes(b"existing PDF output")
    sidecar = Path(str(output) + ".neoview.json")
    sidecar.write_bytes(b"existing sidecar output")
    real_replace = module.os.replace

    def fail_commit(first, second):
        if Path(second) == sidecar:
            raise OSError("commit failed")
        return real_replace(first, second)

    monkeypatch.setattr(module.os, "replace", fail_commit)
    with fitz.open(source) as doc, pytest.raises(OSError, match="commit failed"):
        save_metadata_copy(doc, str(source), str(output), {"title": "new"}, state())
    assert output.read_bytes() == b"existing PDF output"
    assert sidecar.read_bytes() == b"existing sidecar output"
    assert not list(tmp_path.glob(".neoview-metadata-*"))


def test_failed_staging_does_not_create_output(tmp_path, monkeypatch):
    import neoview.ui.metadata_editor as module

    source = tmp_path / "source.pdf"
    output = tmp_path / "copy.pdf"
    make_pdf(source)
    monkeypatch.setattr(module, "save_sidecar", lambda *_: None)
    with fitz.open(source) as doc, pytest.raises(OSError, match="stage annotations"):
        save_metadata_copy(doc, str(source), str(output), {"title": "new"}, state())
    assert not output.exists()
    assert not list(tmp_path.glob(".neoview-metadata-*"))


def test_protected_pdf_is_rejected(tmp_path):
    source = tmp_path / "protected.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(source), encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="owner", user_pw="reader")
    with fitz.open(source) as doc:
        doc.authenticate("reader")
        with pytest.raises(ValueError, match="password-protected"):
            save_metadata_copy(doc, str(source), str(tmp_path / "output.pdf"), {}, state())


def test_dialog_initial_values_cancel_and_save(tmp_path, qtbot, monkeypatch):
    source = tmp_path / "source.pdf"
    output = tmp_path / "copy.pdf"
    make_pdf(source)
    with fitz.open(source) as doc:
        dialog = MetadataEditor(None, doc, str(source), state())
        qtbot.addWidget(dialog)
        assert dialog.fields["title"].text() == "Old title"
        assert dialog.fields["author"].text() == "Original author"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
        dialog._save_copy()
        assert dialog.saved_path is None
        dialog.fields["title"].setText("Edited title")
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(output), ""))
        dialog._save_copy()
        assert dialog.saved_path == str(output)
        assert dialog.result() == QDialog.DialogCode.Accepted
    with fitz.open(output) as doc:
        assert doc.metadata["title"] == "Edited title"


def test_dialog_save_error_keeps_editor_open(tmp_path, qtbot, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    warnings = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(source), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    with fitz.open(source) as doc:
        dialog = MetadataEditor(None, doc, str(source), state())
        qtbot.addWidget(dialog)
        dialog._save_copy()
        assert warnings and "separate destination" in warnings[0]
        assert dialog.saved_path is None
        assert dialog.result() != QDialog.DialogCode.Accepted


def test_entrypoint_snapshot_survives_viewer_reload(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    output = tmp_path / "copy.pdf"
    make_pdf(source)
    doc = fitz.open(source)
    original_state = state()

    def edit(dialog):
        doc.close()  # Simulate the viewer reloading while the modal event loop runs.
        original_state.annotations.clear()
        dialog.fields["title"].setText("Snapshot title")
        dialog._save_copy()
        return dialog.result()

    monkeypatch.setattr(MetadataEditor, "exec", edit)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(output), ""))
    assert edit_metadata(None, doc, str(source), original_state) == str(output)
    assert load_sidecar(str(output)).annotations[0].contents == "Sidecar note"
    with fitz.open(output) as copied:
        assert copied.metadata["title"] == "Snapshot title"


@pytest.mark.parametrize("kind", ["hardlink", "symlink"])
def test_output_pdf_and_sidecar_aliases_are_rejected(tmp_path, kind):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    output = tmp_path / "output.pdf"
    output.write_bytes(b"existing output")
    sidecar = Path(str(output) + ".neoview.json")
    if kind == "hardlink":
        sidecar.hardlink_to(output)
    else:
        sidecar.symlink_to(output)
    with fitz.open(source) as doc, pytest.raises(ValueError, match="separate files"):
        save_metadata_copy(doc, str(source), str(output), {"title": "new"}, state())
    assert output.read_bytes() == b"existing output"
    assert sidecar.read_bytes() == b"existing output"


def test_snapshot_failure_is_reported_without_escaping_qt_slot(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    with fitz.open(source) as document:
        def fail_snapshot(*_args, **_kwargs):
            raise OSError("Snapshot failed")

        monkeypatch.setattr(fitz.Document, "tobytes", fail_snapshot)
        assert edit_metadata(None, document, str(source), state()) is None
    assert warnings == ["Snapshot failed"]


def test_non_pdf_entrypoint_is_reported(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    with fitz.open() as document:
        assert edit_metadata(None, document, str(tmp_path / "empty.pdf"), state()) is None
    assert warnings == ["Open a nonempty PDF first."]
