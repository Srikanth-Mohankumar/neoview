"""Application resources (icons, assets)."""

from __future__ import annotations

from importlib import resources

from PySide6.QtGui import QIcon, QPixmap


APP_ICON_NAME = "feather-logo.png"


def load_app_icon() -> QIcon:
    """Load the app icon from package data, or return an empty icon."""
    try:
        data = resources.files("neoview.assets").joinpath(APP_ICON_NAME).read_bytes()
    except Exception:
        return QIcon()

    pixmap = QPixmap()
    if pixmap.loadFromData(data):
        return QIcon(pixmap)
    return QIcon()
