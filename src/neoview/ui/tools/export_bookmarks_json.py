"""Export portable bookmarks using one-based page numbers."""
from __future__ import annotations

import copy
import json
import math

from PySide6.QtWidgets import QMessageBox

from neoview.ui.tool_support import atomic_text, choose_file


def render_bookmarks(bookmarks) -> str:
    """Serialize the version-one transfer format without changing bookmark records."""
    records = []
    for bookmark in bookmarks:
        if (not isinstance(bookmark.page, int) or isinstance(bookmark.page, bool)
                or bookmark.page < 0):
            raise ValueError("Bookmark pages must be nonnegative integer indexes.")
        if not isinstance(bookmark.title, str) or not isinstance(bookmark.created_at, str):
            raise ValueError("Bookmark titles and creation dates must be text.")
        if (isinstance(bookmark.y, bool) or not isinstance(bookmark.y, (int, float))
                or not math.isfinite(bookmark.y) or bookmark.y < 0):
            raise ValueError("Bookmark positions must be finite, nonnegative numbers.")
        records.append({
            "title": bookmark.title,
            "page": bookmark.page + 1,
            "y": bookmark.y,
            "created_at": bookmark.created_at,
        })
    return json.dumps({"version": 1, "bookmarks": records}, ensure_ascii=False,
                      indent=2, allow_nan=False) + "\n"


def run(window) -> None:
    context = window.current_context()
    source = context.file_path
    if not source:
        raise ValueError("Open a PDF first.")
    # Destination dialogs can run reload timers; retain the state at invocation.
    bookmarks = copy.deepcopy(context.sidecar_state.bookmarks)
    if not bookmarks:
        QMessageBox.information(window, "Export Bookmarks", "No bookmarks to export.")
        return
    text = render_bookmarks(bookmarks)
    target = choose_file(window, source, "-bookmarks", ".json", "Export Bookmarks as JSON")
    if not target:
        return
    atomic_text(source, target, text)
    if hasattr(window, "_status"):
        window._status.showMessage(f"Exported {len(bookmarks)} bookmarks", 3000)
