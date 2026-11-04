"""Insert a blank A4 page into an explicitly saved PDF copy."""
from __future__ import annotations

import copy
from dataclasses import replace

import fitz
from PySide6.QtWidgets import QInputDialog

from neoview.models.view_state import DocumentSidecarState
from neoview.ui.tool_support import choose_file, save_copy, snapshot


def insert_blank_page(document, state: DocumentSidecarState, position: int):
    """Return an owned document and remapped state, leaving both inputs unchanged.

    ``position`` is one-based and may be page_count + 1 to append. The caller
    must close the returned document.
    """
    if not document.is_pdf or not document.page_count:
        raise ValueError("Open a nonempty PDF first.")
    if (document.needs_pass or document.is_encrypted
            or (document.metadata or {}).get("encryption")):
        raise ValueError("Blank-page insertion does not support password-protected PDFs.")
    if isinstance(position, bool) or not isinstance(position, int) or not (
        1 <= position <= document.page_count + 1
    ):
        raise ValueError(f"Choose an insertion position from 1 to {document.page_count + 1}.")
    index = position - 1
    output = fitz.open(stream=document.tobytes(), filetype="pdf")
    try:
        toc = output.get_toc(simple=False)
        output.new_page(pno=index, width=595, height=842)
        for entry in toc:
            if entry[2] >= position:
                entry[2] += 1
            if len(entry) > 3:
                destination = entry[3]
                if destination.get("kind") == fitz.LINK_GOTO and destination.get("page", -1) >= index:
                    destination["page"] += 1
        output.set_toc(toc)
        result = copy.deepcopy(state)
        result.annotations = [replace(a, page=a.page + (a.page >= index)) for a in result.annotations]
        result.bookmarks = [replace(b, page=b.page + (b.page >= index)) for b in result.bookmarks]
        return output, result
    except Exception:
        output.close()
        raise


def run(window) -> str | None:
    with snapshot(window, unprotected=True) as (document, state, source):
        position, accepted = QInputDialog.getInt(
            window, "Insert Blank Page", "Insert before page (last position appends):",
            1, 1, document.page_count + 1,
        )
        if not accepted:
            return None
        target = choose_file(window, source, "-blank-page", ".pdf", "Save PDF with Blank Page")
        if target is None:
            return None
        output, remapped = insert_blank_page(document, state, position)
        with output:
            return save_copy(output, remapped, source, target)
