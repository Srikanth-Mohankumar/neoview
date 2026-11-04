"""Shared snapshots and safe destinations for optional document tools."""
from __future__ import annotations

import copy
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import fitz
from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.persistence.sidecar_store import sidecar_path_for
from neoview.ui.metadata_editor import save_metadata_copy


def aliases(first, second):
    if Path(first).resolve() == Path(second).resolve():
        return True
    try:
        return os.path.samefile(first, second)
    except FileNotFoundError:
        return False


def protect_source(source, target):
    if any(aliases(target, protected) for protected in (source, sidecar_path_for(source))):
        raise ValueError("Choose a destination separate from the source PDF and its sidecar.")


@contextmanager
def snapshot(window, *, unprotected=False):
    original = window.current_view().document
    context = window.current_context()
    if original is None or not context.file_path:
        raise ValueError("Open a PDF first.")
    if unprotected and (original.needs_pass or original.is_encrypted
                        or (original.metadata or {}).get("encryption")):
        raise ValueError("This operation does not support password-protected PDFs.")
    state = copy.deepcopy(context.sidecar_state)
    source = context.file_path
    with fitz.open(stream=original.tobytes(), filetype="pdf") as document:
        yield document, state, source


def choose_file(window, source, stem_suffix, extension, title):
    default = str(Path(source).with_name(Path(source).stem + stem_suffix + extension))
    path, _ = QFileDialog.getSaveFileName(window, title, default,
                                         f"{extension[1:].upper()} (*{extension})")
    if not path:
        return None
    protect_source(source, path)
    if not path.lower().endswith(extension):
        path += extension
        protect_source(source, path)
        if Path(path).exists() and QMessageBox.question(
            window, "Replace File?", f"Replace {Path(path).name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return None
    return str(Path(path).absolute())


def atomic_text(source, target, text):
    protect_source(source, target)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                          dir=Path(target).absolute().parent,
                                          prefix=".neoview-export-", delete=False) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def save_copy(document, state, source, target):
    return save_metadata_copy(document, source, target, {}, state)


def apply_state(window, state):
    view = window.current_view()
    window.current_context().sidecar_state = state
    view.set_annotations(state.annotations + window.current_context().native_annotations)
    window._populate_annotation_list()
    window._populate_bookmarks()
    window._mark_sidecar_dirty(view)
