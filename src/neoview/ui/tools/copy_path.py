"""Copy the active document's absolute local path to the clipboard."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication


def run(window) -> None:
    source = window.current_context().file_path
    if window.current_view().document is None or not source:
        raise ValueError("Open a PDF before copying its file path.")
    QApplication.clipboard().setText(str(Path(source).absolute()))
    window._status.showMessage("Copied PDF file path", 3000)
