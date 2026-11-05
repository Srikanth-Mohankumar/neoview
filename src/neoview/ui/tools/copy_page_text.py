"""Copy selectable text from the active page without changing the document."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication


def run(window) -> None:
    viewer = window.current_view()
    document = viewer.document
    if document is None:
        raise ValueError("Open a PDF before copying page text.")
    page_index = viewer.current_page
    if not 0 <= page_index < document.page_count:
        raise ValueError("The current page is outside the PDF page range.")

    text = document[page_index].get_text("text")
    if not text.strip():
        window._status.showMessage("No selectable text on current page", 3000)
        return
    QApplication.clipboard().setText(text)
    window._status.showMessage("Copied current page text", 3000)
