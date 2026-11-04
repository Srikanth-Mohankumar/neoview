"""Split a PDF into separately annotated one-page documents in a new directory."""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import fitz
from PySide6.QtWidgets import QFileDialog

from neoview.models.view_state import DocumentSidecarState
from neoview.persistence.sidecar_store import save_sidecar, sidecar_path_for
from neoview.ui.tool_support import snapshot


def split_pdf(document, state: DocumentSidecarState, source: str, parent: str) -> str:
    """Write each source page once; publish only into an exclusively owned folder.

    A sibling staging directory holds complete PDFs and sidecars before the final
    directory is reserved. Reservation uses mkdir rather than replacement rename,
    so a concurrently created destination can never be overwritten.
    """
    if not document.is_pdf or document.page_count < 1:
        raise ValueError("Open a nonempty PDF first.")
    if (document.needs_pass or document.is_encrypted
            or (document.metadata or {}).get("encryption")):
        raise ValueError("Splitting does not support password-protected PDFs.")
    parent_path = Path(parent).absolute()
    if not parent_path.is_dir():
        raise ValueError("Choose an existing parent directory.")
    destination = parent_path / (Path(source).stem + "-split")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"The destination already exists: {destination.name}")
    toc = document.get_toc()
    annotations = {}
    bookmarks = {}
    for record in state.annotations:
        annotations.setdefault(record.page, []).append(record)
    for record in state.bookmarks:
        bookmarks.setdefault(record.page, []).append(record)
    outlines = {}
    for level, title, page in toc:
        outlines.setdefault(page - 1, []).append((level, title))
    reserved = False
    with tempfile.TemporaryDirectory(prefix=".neoview-split-", dir=parent_path) as work:
        stage = Path(work)
        try:
            digits = max(3, len(str(document.page_count)))
            for index in range(document.page_count):
                path = stage / f"page-{index + 1:0{digits}d}.pdf"
                with fitz.open() as output:
                    output.insert_pdf(document, from_page=index, to_page=index,
                                      links=True, annots=True)
                    output.set_metadata(dict(document.metadata or {}))
                    page_toc = []
                    previous_level = 0
                    for level, title in outlines.get(index, []):
                        level = min(level, previous_level + 1)
                        page_toc.append([level, title, 1])
                        previous_level = level
                    output.set_toc(page_toc)
                    output.save(str(path), garbage=4, deflate=True)
                page_state = DocumentSidecarState(
                    version=state.version,
                    annotations=[replace(record, page=0)
                                 for record in annotations.get(index, [])],
                    bookmarks=[replace(record, page=0)
                               for record in bookmarks.get(index, [])],
                )
                save_sidecar(str(path), page_state)
                if not Path(sidecar_path_for(str(path))).is_file():
                    raise OSError("Could not stage the split PDF annotations and bookmarks.")
            destination.mkdir()
            reserved = True
            for path in stage.iterdir():
                path.rename(destination / path.name)
        except Exception:
            if reserved:
                shutil.rmtree(destination)
            raise
    return str(destination)


def run(window) -> None:
    with snapshot(window, unprotected=True) as (document, state, source):
        parent = QFileDialog.getExistingDirectory(window, "Choose Parent Folder for Split PDFs")
        if not parent:
            return None
        split_pdf(document, state, source, parent)
    return None
