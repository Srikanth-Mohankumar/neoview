"""Open the active PDF's containing local folder through desktop services."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def run(window) -> None:
    source = window.current_context().file_path
    if window.current_view().document is None or not source:
        raise ValueError("Open a PDF before opening its containing folder.")
    folder = Path(source).absolute().parent
    if not folder.is_dir():
        raise ValueError("The PDF's containing folder no longer exists.")
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
        raise OSError("The desktop could not open the containing folder.")
    window._status.showMessage("Opened PDF containing folder", 3000)
