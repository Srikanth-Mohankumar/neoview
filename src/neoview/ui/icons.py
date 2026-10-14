"""Bundled SVG icon set (Lucide 1.57.0, ISC licence - see assets/icons/LICENSE).

Every icon in the app comes from here so Linux and Windows show the same glyphs, instead of
whatever the desktop icon theme or ``QStyle`` happens to provide.

    from neoview.ui import icons
    action.setIcon(icons.icon("zoom-in"))

Icons are tinted at render time: the SVGs use ``currentColor``, which is replaced with the
requested colour (default: the foreground for the current ``theme_mode``). Each ``QIcon``
carries crisp pixmaps for the common UI sizes at 1x and 2x device-pixel ratios, plus a faded
copy for the disabled state. Results are cached per (name, colour, size).
"""

from __future__ import annotations

from importlib import resources

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

ICON_PACKAGE = "neoview.assets"
ICON_SUBDIR = "icons"

# Default glyph colours per theme mode (the app sets QApplication property "theme_mode").
DEFAULT_COLORS = {"light": "#3c3f44", "dark": "#d6d8dc"}

# Opacity of the disabled-state glyph relative to the normal one.
DISABLED_OPACITY = 0.38

# Logical sizes always rendered into each QIcon (toolbars use 18, menus 16, docks 20/24).
_BASE_SIZES = (16, 18, 20, 24, 32, 48)
_SCALES = (1.0, 2.0)

# freedesktop icon-theme names used by MainWindow._icon() -> bundled Lucide names.
THEME_NAME_MAP: dict[str, str] = {
    "document-open": "folder-open",
    "document-open-recent": "file-clock",
    "document-save": "save",
    "edit-copy": "copy",
    "zoom-in": "zoom-in",
    "zoom-out": "zoom-out",
    "zoom-fit-width": "move-horizontal",
    "zoom-fit-best": "expand",
    "zoom-original": "scan",
    "cursor-arrow": "mouse-pointer-2",
    "draw-rectangle": "ruler-dimension-line",
    "draw-brush": "pen-line",
    "format-text-highlight": "highlighter",
    "format-text-underline": "underline",
    "insert-text": "sticky-note",
    "image-x-generic": "image",
}


class UnknownIconError(KeyError):
    """Raised when an icon name is neither bundled nor a mapped theme name."""


_cache: dict[tuple[str, str, int], QIcon] = {}
_svg_cache: dict[str, bytes] = {}


def _icons_dir():
    return resources.files(ICON_PACKAGE).joinpath(ICON_SUBDIR)


def available_icons() -> list[str]:
    """Sorted names of every bundled icon (file stem of each SVG)."""
    return sorted(
        entry.name[: -len(".svg")]
        for entry in _icons_dir().iterdir()
        if entry.name.endswith(".svg")
    )


def resolve_name(name: str) -> str:
    """Return the bundled icon name for a Lucide name or a mapped freedesktop name."""
    return THEME_NAME_MAP.get(name, name)


def _svg_bytes(name: str) -> bytes:
    data = _svg_cache.get(name)
    if data is None:
        path = _icons_dir().joinpath(f"{name}.svg")
        if not path.is_file():
            raise UnknownIconError(
                f"unknown icon {name!r}: no bundled assets/icons/{name}.svg "
                f"(see neoview.ui.icons.available_icons())"
            )
        data = path.read_bytes()
        _svg_cache[name] = data
    return data


def default_color() -> str:
    """Glyph colour for the current QApplication 'theme_mode' (light if unset)."""
    app = QGuiApplication.instance()
    mode = str(app.property("theme_mode") or "").lower() if app is not None else ""
    return DEFAULT_COLORS.get(mode, DEFAULT_COLORS["light"])


def _renderer(name: str, tint: str) -> QSvgRenderer:
    renderer = QSvgRenderer(QByteArray(_svg_bytes(name).replace(b"currentColor", tint.encode())))
    if not renderer.isValid():
        raise ValueError(f"icon {name!r} could not be parsed as SVG")
    return renderer


def _render(renderer: QSvgRenderer, size: int, scale: float, opacity: float) -> QPixmap:
    px = max(1, round(size * scale))
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.setOpacity(opacity)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pix.setDevicePixelRatio(scale)
    return pix


def _scales() -> tuple[float, ...]:
    scales = set(_SCALES)
    app = QGuiApplication.instance()
    if app is not None:
        for screen in QGuiApplication.screens():
            ratio = float(screen.devicePixelRatio())
            if ratio > 0:
                scales.add(ratio)
    return tuple(sorted(scales))


def pixmap(name: str, color: str | None = None, size: int = 20, scale: float = 1.0) -> QPixmap:
    """Render one tinted pixmap (``size`` logical px at device-pixel ratio ``scale``)."""
    name = resolve_name(name)
    tint = color or default_color()
    renderer = _renderer(name, tint)
    return _render(renderer, size, scale, 1.0)


def icon(name: str, color: str | None = None, size: int = 20) -> QIcon:
    """Return a tinted, cached QIcon for a bundled icon.

    ``name`` is a Lucide name (see ``available_icons()``) or a freedesktop name from
    ``THEME_NAME_MAP``. ``color`` is any SVG colour string; default is the theme foreground.
    ``size`` is the preferred logical size; common UI sizes are always included as well.
    Raises ``UnknownIconError`` for names that are not bundled.
    """
    name = resolve_name(name)
    tint = color or default_color()
    key = (name, tint, int(size))
    cached = _cache.get(key)
    if cached is not None:
        return cached

    renderer = _renderer(name, tint)

    result = QIcon()
    for logical in sorted(set(_BASE_SIZES) | {int(size)}):
        for scale in _scales():
            result.addPixmap(_render(renderer, logical, scale, 1.0), QIcon.Mode.Normal)
            result.addPixmap(
                _render(renderer, logical, scale, DISABLED_OPACITY), QIcon.Mode.Disabled
            )
    _cache[key] = result
    return result


def clear_cache() -> None:
    """Drop cached icons (e.g. after the theme changes)."""
    _cache.clear()
