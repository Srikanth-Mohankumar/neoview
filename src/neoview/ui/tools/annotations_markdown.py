"""Export annotation review text without interpreting user text as Markdown."""
from __future__ import annotations

import copy
import html
import re

from PySide6.QtWidgets import QMessageBox

from neoview.ui.tool_support import atomic_text, choose_file

_MARKDOWN_PUNCTUATION = re.compile(r"([\\`*_{}\[\]()#+.!|>~:=\-])")


def plain_markdown(value) -> str:
    """Escape HTML and Markdown controls, including user-provided link markup."""
    text = html.escape(str(value), quote=False).replace("\r\n", "\n").replace("\r", "\n")
    return _MARKDOWN_PUNCTUATION.sub(r"\\\1", text)


def annotation_report(annotations, native_annotations) -> str:
    """Group both sources by one-based page; retain original order within a page."""
    grouped = {}
    for source, records in (("NeoView", annotations), ("Native PDF", native_annotations)):
        for annotation in records:
            if not isinstance(annotation.page, int) or annotation.page < 0:
                raise ValueError("Annotation pages must be nonnegative integer indices.")
            grouped.setdefault(annotation.page, []).append((source, annotation))
    lines = ["# Annotation Review Report", "", "Page numbers are one-based. Bounds use PDF points.", ""]
    for page, records in sorted(grouped.items()):
        lines.extend([f"## Page {page + 1}", ""])
        for index, (source, annotation) in enumerate(records, 1):
            lines.extend([
                f"### Annotation {index} ({source})", "",
                f"- Type: {plain_markdown(annotation.type)}",
                f"- Color: {plain_markdown(annotation.color)}",
                f"- Opacity: {plain_markdown(annotation.opacity)}",
                "- Bounds (x, y, width, height): "
                + ", ".join(plain_markdown(value) for value in annotation.rect),
                "", "**Contents:**", "",
            ])
            contents = plain_markdown(annotation.contents)
            lines.extend(line + "  " for line in contents.split("\n"))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run(window) -> None:
    context = window.current_context()
    if window.current_view().document is None or not context.file_path:
        raise ValueError("Open a PDF first.")
    source = context.file_path
    # Nested save dialogs can run auto-reload and replace both annotation lists.
    annotations = copy.deepcopy(context.sidecar_state.annotations)
    native_annotations = copy.deepcopy(context.native_annotations)
    if not annotations and not native_annotations:
        QMessageBox.information(window, "Export Annotation Report", "No annotations to export.")
        return
    text = annotation_report(annotations, native_annotations)
    path = choose_file(window, source, "-annotations", ".md", "Export Annotation Report as Markdown")
    if path:
        atomic_text(source, path, text)
