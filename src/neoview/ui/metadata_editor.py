"""Edit descriptive PDF metadata in a separate, explicitly saved copy."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
from pathlib import Path

import fitz
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from neoview.models.view_state import DocumentSidecarState
from neoview.persistence.sidecar_store import save_sidecar, sidecar_path_for

METADATA_FIELDS = ("title", "author", "subject", "keywords")


def _aliases(first: Path, second: Path) -> bool:
    if first.resolve() == second.resolve():
        return True
    try:
        return os.path.samefile(first, second)
    except FileNotFoundError:
        return False


def save_metadata_copy(
    document: fitz.Document,
    source_path: str,
    destination: str,
    values: dict[str, str],
    sidecar_state: DocumentSidecarState,
) -> str:
    """Write a metadata-only PDF copy and matching sidecar, restoring on failure."""
    if not document.is_pdf or document.page_count == 0:
        raise ValueError("Open a nonempty PDF first.")
    if (document.needs_pass or document.is_encrypted
            or (document.metadata or {}).get("encryption")):
        raise ValueError("Metadata editing is unavailable for password-protected PDFs.")
    if set(values) - set(METADATA_FIELDS) or any(not isinstance(v, str) for v in values.values()):
        raise ValueError("Only title, author, subject, and keywords text can be edited.")
    target = Path(destination).absolute()
    target_sidecar = Path(sidecar_path_for(str(target)))
    if _aliases(target, target_sidecar):
        raise ValueError("The output PDF and its sidecar must be separate files.")
    protected = [Path(source_path), Path(sidecar_path_for(source_path))]
    if any(_aliases(output, original) for output in (target, target_sidecar)
           for original in protected):
        raise ValueError("Choose a separate destination; the source PDF and sidecar must stay unchanged.")
    work = Path(tempfile.mkdtemp(prefix=".neoview-metadata-", dir=target.parent))
    retain_recovery = False
    try:
        staged = work / "copy.pdf"
        with fitz.open(stream=document.tobytes(), filetype="pdf") as output:
            metadata = dict(output.metadata or {})
            metadata.update(values)
            output.set_metadata(metadata)
            output.save(str(staged), garbage=4, deflate=True)
        save_sidecar(str(staged), sidecar_state)
        staged_sidecar = Path(sidecar_path_for(str(staged)))
        if not staged_sidecar.is_file():
            raise OSError("Could not stage annotations and bookmarks; no output was changed.")
        pairs = [(staged, target), (staged_sidecar, target_sidecar)]
        backups = {}
        for index, (_, destination_path) in enumerate(pairs):
            if destination_path.exists():
                backup = work / f"backup-{index}"
                shutil.copy2(destination_path, backup)
                backups[destination_path] = backup
        replaced = []
        try:
            for staged_path, destination_path in pairs:
                os.replace(staged_path, destination_path)
                replaced.append(destination_path)
        except OSError as save_error:
            try:
                for destination_path in reversed(replaced):
                    if destination_path in backups:
                        os.replace(backups[destination_path], destination_path)
                    else:
                        destination_path.unlink(missing_ok=True)
            except OSError as rollback_error:
                retain_recovery = True
                raise OSError(f"Save and restoration failed. Recovery files remain in {work}") from rollback_error
            raise save_error
    finally:
        if not retain_recovery:
            shutil.rmtree(work)
    return str(target)


class MetadataEditor(QDialog):
    def __init__(self, parent, document, source_path, sidecar_state):
        super().__init__(parent)
        self.document = document
        self.source_path = source_path
        self.sidecar_state = sidecar_state
        self.saved_path = None
        self.setWindowTitle("Edit PDF Metadata")
        self.resize(480, 240)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Edit document details and save a separate PDF copy."))
        form = QFormLayout()
        self.fields = {}
        metadata = document.metadata or {}
        for key in METADATA_FIELDS:
            field = QLineEdit(metadata.get(key) or "")
            field.setObjectName(f"metadata_{key}")
            self.fields[key] = field
            form.addRow(key.capitalize(), field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save Copy...")
        buttons.accepted.connect(self._save_copy)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save_copy(self):
        source = Path(self.source_path)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF with Metadata", str(source.with_stem(source.stem + "-metadata")),
            "PDF (*.pdf)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
            if Path(path).exists() and QMessageBox.question(
                self, "Replace PDF?", f"Replace {Path(path).name}?"
            ) != QMessageBox.StandardButton.Yes:
                return
        try:
            self.saved_path = save_metadata_copy(
                self.document, self.source_path, path,
                {key: field.text() for key, field in self.fields.items()}, self.sidecar_state,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Could Not Save Metadata", str(exc))
            return
        self.accept()


def edit_metadata(parent, document, source_path, sidecar_state) -> str | None:
    """Show the metadata editor and return the saved copy path, or None."""
    try:
        if not document.is_pdf or document.page_count == 0:
            raise ValueError("Open a nonempty PDF first.")
        if (document.needs_pass or document.is_encrypted
                or (document.metadata or {}).get("encryption")):
            raise ValueError("Metadata editing is unavailable for password-protected PDFs.")
        # A nested dialog event loop can run the viewer's auto-reload timers.
        # Own a snapshot rather than holding its mutable document reference.
        with fitz.open(stream=document.tobytes(), filetype="pdf") as snapshot:
            dialog = MetadataEditor(parent, snapshot, source_path, copy.deepcopy(sidecar_state))
            try:
                dialog.exec()
                return dialog.saved_path
            finally:
                dialog.deleteLater()
    except Exception as exc:
        QMessageBox.warning(parent, "Cannot Edit Metadata", str(exc))
        return None
