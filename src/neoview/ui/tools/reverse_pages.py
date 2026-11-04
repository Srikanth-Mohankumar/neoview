"""Save all PDF pages in reverse order without changing the original."""
from __future__ import annotations

import fitz

from neoview.models.page_extraction import validate_extraction_destination
from neoview.models.page_organization import PageOrganization
from neoview.models.view_state import DocumentSidecarState
from neoview.ui.tool_support import choose_file, snapshot


def reverse_pdf(
    document: fitz.Document,
    state: DocumentSidecarState,
    source: str,
    destination: str,
) -> str:
    """Write reversed pages and remapped sidecar records to a separate PDF."""
    if not document.is_pdf or document.page_count == 0:
        raise ValueError("Open a nonempty PDF first.")
    output = validate_extraction_destination(source, destination)
    session = PageOrganization(document, state)
    try:
        session.reorder(list(reversed(session.order)))
        session.save(output)
    finally:
        session.close()
    return output


def run(window) -> str | None:
    """Prompt for a separate output PDF and return its path after saving."""
    with snapshot(window, unprotected=True) as (document, state, source):
        destination = choose_file(
            window, source, "-reversed", ".pdf", "Save Reversed PDF"
        )
        if not destination:
            return None
        return reverse_pdf(document, state, source, destination)
