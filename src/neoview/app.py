"""NeoView application entry point."""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import QApplication

from neoview.resources import load_app_icon
from neoview.theme import LIGHT_STYLE
from neoview.ui.main_window import MainWindow, APP_NAME


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(LIGHT_STYLE)

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
