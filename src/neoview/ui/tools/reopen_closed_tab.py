"""Reopen the newest available closed PDF through the normal open workflow."""
from __future__ import annotations

from pathlib import Path


def run(window) -> None:
    """Consume missing history entries and reopen or select the newest existing PDF."""
    history = window._closed_pdf_paths
    action = window._extra_tool_actions["reopen_closed_tab"]
    try:
        while history:
            path = history.pop()
            if not Path(path).is_file():
                continue
            window._open_file(path)
            if window._find_open_view(path) is not None:
                window._status.showMessage(f"Reopened {Path(path).name}", 3000)
            else:
                window._status.showMessage(f"Could not reopen {Path(path).name}", 3000)
            return
        window._status.showMessage("No closed PDF files available to reopen", 3000)
    finally:
        action.setEnabled(bool(history))
