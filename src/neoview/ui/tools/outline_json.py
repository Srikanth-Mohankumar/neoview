"""Export document outlines as versioned, nested UTF-8 JSON."""
from __future__ import annotations

import json

import fitz
from PySide6.QtWidgets import QMessageBox

from neoview.ui.tool_support import atomic_text, choose_file, snapshot


def _json_value(value):
    if isinstance(value, (fitz.Point, fitz.Rect)):
        return list(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("The outline contains an unsupported destination value.")


def outline_payload(document):
    """Return nested entries with one-based local/remote target page numbers.

    ``page`` is null for non-local destinations. Their original URI, filename,
    named destination and other link attributes are retained in ``destination``.
    ``destination.page`` is one-based when PyMuPDF supplies a page target.
    """
    roots = []
    stack = []
    for row in document.get_toc(simple=False):
        level, title, page = row[:3]
        destination = _json_value(row[3] if len(row) > 3 else {})
        kind = destination.get("kind", fitz.LINK_GOTO)
        local_page = page if kind in (fitz.LINK_NONE, fitz.LINK_GOTO) and page > 0 else None
        if isinstance(destination.get("page"), int) and destination["page"] >= 0:
            destination["page"] += 1
        entry = {"level": level, "title": title, "page": local_page,
                 "destination": destination, "children": []}
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        (stack[-1]["children"] if stack else roots).append(entry)
        stack.append(entry)
    return {"version": 1, "outline": roots}


def run(window):
    with snapshot(window) as (document, _state, source):
        payload = outline_payload(document)
        if not payload["outline"]:
            QMessageBox.information(window, "Export Outline", "This document has no outline.")
            return None
        text = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        target = choose_file(window, source, "-outline", ".json", "Export Outline as JSON")
        if target:
            atomic_text(source, target, text)
            if hasattr(window, "_status"):
                window._status.showMessage("Saved document outline", 3000)
    return None
