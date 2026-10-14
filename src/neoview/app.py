"""NeoView application entry point."""

from __future__ import annotations

import os
import sys

import fitz
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from neoview.resources import load_app_icon
from neoview.theme import apply_theme
from neoview.ui.main_window import APP_NAME, MainWindow


def main() -> None:
    # Suppress noisy parser diagnostics from malformed third-party PDFs.
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)

    # Must precede QApplication: render at the real fractional scale (125%, 150%)
    # instead of rounding, so Windows and Linux HiDPI screens size the UI the same.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    # Fusion style, explicit palette, bundled Inter font and the generated stylesheet,
    # so the app looks the same on every OS. NEOVIEW_THEME=light|dark picks the theme.
    apply_theme(app, os.getenv("NEOVIEW_THEME", "light"))

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
