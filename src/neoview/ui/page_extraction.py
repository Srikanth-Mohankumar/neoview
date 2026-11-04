"""Dialogs for saving an ordered page range as a separate PDF."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from neoview.models.page_extraction import parse_page_ranges, save_extraction
from neoview.models.page_organization import PageOrganization


def extract_pages(parent, document, source_path, sidecar_state) -> str | None:
    """Ask for page ranges and destination, then return a saved path or None."""
    if document is None or not source_path:
        return None
    session = None
    try:
        # Dialogs run an event loop: the viewer may reload and close its original
        # document while the user is choosing ranges or a destination.
        session = PageOrganization(document, sidecar_state)
        ranges, accepted = QInputDialog.getText(
            parent, "Extract Pages", f"Pages (1-{session.document.page_count}), for example 1-3, 5:",
        )
        if not accepted:
            return None
        parse_page_ranges(ranges, session.document.page_count)
        source = Path(source_path)
        default = str(source.with_stem(source.stem + "-extracted"))
        output, _ = QFileDialog.getSaveFileName(
            parent, "Save Extracted PDF", default, "PDF (*.pdf)",
        )
        if not output:
            return None
        if not output.lower().endswith(".pdf"):
            output += ".pdf"
            if Path(output).exists() and QMessageBox.question(
                parent, "Replace PDF", f"Replace {Path(output).name}?"
            ) != QMessageBox.StandardButton.Yes:
                return None
        return save_extraction(session, source_path, ranges, output)
    except Exception as exc:
        QMessageBox.warning(parent, "Could Not Extract Pages", str(exc))
        return None
    finally:
        if session is not None:
            session.close()
