"""Export selectable PDF text, including explicit separators for empty pages."""
from __future__ import annotations

from neoview.ui.tool_support import atomic_text, choose_file, snapshot


def render_text(document) -> str:
    """Return page-ordered text; scanned pages retain an empty numbered section."""
    if not document.is_pdf or document.page_count == 0:
        raise ValueError("Open a nonempty PDF first.")
    sections = []
    for index, page in enumerate(document):
        text = page.get_text("text", sort=True).rstrip("\n")
        sections.append(f"--- Page {index + 1} ---\n{text}\n")
    return "\n".join(sections)


def run(window) -> None:
    with snapshot(window) as (document, _state, source):
        target = choose_file(window, source, "-text", ".txt", "Export Document Text")
        if not target:
            return
        atomic_text(source, target, render_text(document))
        status = getattr(window, "_status", None)
        if status is not None:
            status.showMessage("Exported document text", 3000)
