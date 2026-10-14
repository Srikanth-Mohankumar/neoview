"""Application resources (icons, bundled fonts)."""

from __future__ import annotations

from importlib import resources

from PySide6.QtGui import QFontDatabase, QIcon, QPixmap

APP_ICON_NAME = "feather-logo.png"

# Inter (SIL Open Font License 1.1, see assets/fonts/OFL.txt) is bundled so the UI
# looks the same on every OS instead of depending on which fonts are installed.
APP_FONT_FAMILY = "Inter"
APP_FONT_FILES = ("Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf")

_registered_families: list[str] | None = None


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


def register_fonts() -> list[str]:
    """Register the bundled fonts with Qt and return the family names Qt reports.

    Needs a QGuiApplication. Safe to call more than once: later calls return the
    families from the first registration. Fonts are loaded from bytes so this works
    from a wheel, a zip import or a PyInstaller bundle alike.
    """
    global _registered_families
    if _registered_families is not None:
        return list(_registered_families)

    families: list[str] = []
    fonts_dir = resources.files("neoview.assets").joinpath("fonts")
    for name in APP_FONT_FILES:
        try:
            data = fonts_dir.joinpath(name).read_bytes()
        except Exception:
            continue
        font_id = QFontDatabase.addApplicationFontFromData(data)
        if font_id < 0:
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in families:
                families.append(family)
    _registered_families = families
    return list(families)


def app_font_family() -> str:
    """Return the UI font family: bundled Inter when registered, else Qt's default."""
    families = register_fonts()
    if APP_FONT_FAMILY in families:
        return APP_FONT_FAMILY
    return families[0] if families else ""
