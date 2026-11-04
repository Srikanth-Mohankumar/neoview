"""Validate a portable bookmark file before appending it to the current document."""
from __future__ import annotations

import copy
import json
import math
import uuid
from pathlib import Path

from PySide6.QtWidgets import QFileDialog

from neoview.models.view_state import BookmarkRecord
from neoview.ui.tool_support import apply_state

MAX_BOOKMARKS = 5_000
MAX_FILE_BYTES = 5 * 1024 * 1024


def parse_bookmarks(payload, page_count: int) -> list[BookmarkRecord]:
    """Return new-ID records from version 1 JSON with one-based page numbers."""
    if (not isinstance(payload, dict) or set(payload) != {"version", "bookmarks"}
            or type(payload["version"]) is not int or payload["version"] != 1):
        raise ValueError("Choose a version 1 bookmark export.")
    records = payload["bookmarks"]
    if not isinstance(records, list) or len(records) > MAX_BOOKMARKS:
        raise ValueError(f"The bookmark export must contain at most {MAX_BOOKMARKS} bookmarks.")
    result = []
    required = {"title", "page", "y", "created_at"}
    for record in records:
        if (not isinstance(record, dict) or not required <= set(record)
                or set(record) - required - {"id"}):
            raise ValueError("Each bookmark must contain a title, page, y and created_at.")
        title = record["title"]
        created_at = record["created_at"]
        page = record["page"]
        y = record["y"]
        if (not isinstance(title, str) or len(title) > 4096
                or not isinstance(created_at, str) or len(created_at) > 128
                or ("id" in record and not isinstance(record["id"], str))):
            raise ValueError("Bookmark titles and timestamps must be bounded text values.")
        if type(page) is not int or not 1 <= page <= page_count:
            raise ValueError(f"Bookmark pages must be between 1 and {page_count}.")
        try:
            position = float(y) if type(y) in (int, float) else math.nan
        except (ValueError, OverflowError):
            position = math.nan
        if not math.isfinite(position) or position < 0:
            raise ValueError("Bookmark positions must be finite, nonnegative numbers.")
        result.append(BookmarkRecord(uuid.uuid4().hex, title, page - 1, position, created_at))
    return result


def load_bookmarks(path: str, page_count: int) -> list[BookmarkRecord]:
    with Path(path).open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("The bookmark file is larger than 5 MB.")
    return parse_bookmarks(json.loads(data.decode("utf-8-sig")), page_count)


def run(window) -> None:
    view = window.current_view()
    context = window.current_context()
    source = context.file_path
    if view.document is None or not source:
        raise ValueError("Open a PDF first.")
    path, _ = QFileDialog.getOpenFileName(
        window, "Import Bookmarks from JSON", "", "JSON (*.json)"
    )
    if not path:
        return
    # A modal dialog can run file reloads. Validate against the current document,
    # and never apply an import to a different tab/document than the one chosen.
    if (window.current_view() is not view or window.current_context().file_path != source
            or view.document is None):
        raise ValueError("The active PDF changed. Start the bookmark import again.")
    incoming = load_bookmarks(path, view.document.page_count)
    state = copy.deepcopy(window.current_context().sidecar_state)
    if len(state.bookmarks) + len(incoming) > MAX_BOOKMARKS:
        raise ValueError(f"The document cannot contain more than {MAX_BOOKMARKS} bookmarks.")
    if incoming:
        state.bookmarks.extend(incoming)
        apply_state(window, state)
    window._status.showMessage(f"Imported {len(incoming)} bookmarks", 3000)
