"""NeoView application entry point."""

from __future__ import annotations

import os
import sys

import fitz
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from neoview.resources import load_app_icon
from neoview.theme import DARK_STYLE
from neoview.ui.main_window import MainWindow, APP_NAME


def main() -> None:
    # Suppress noisy parser diagnostics from malformed third-party PDFs.
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(DARK_STYLE)
    app.setFont(QFont("JetBrains Mono", 10))

    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    pdf = None
    if len(sys.argv) > 1:
        pdf = sys.argv[1]
        if not os.path.isfile(pdf):
            print(f"Error: {pdf} not found")
            sys.exit(1)

    win = MainWindow(pdf)
    win.show()

    sys.exit(app.exec())
