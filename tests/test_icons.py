import re
from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication

from neoview.ui import icons

MAIN_WINDOW = Path(icons.__file__).with_name("main_window.py")


def _opaque_pixels(image: QImage) -> int:
    return sum(
        1
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 0
    )


def _darkest_opaque(image: QImage):
    best = None
    for x in range(image.width()):
        for y in range(image.height()):
            color = image.pixelColor(x, y)
            if color.alpha() == 255 and (best is None or color.lightness() < best.lightness()):
                best = color
    return best


@pytest.fixture
def theme_mode():
    app = QApplication.instance()
    previous = app.property("theme_mode")

    def _set(mode):
        app.setProperty("theme_mode", mode)

    yield _set
    app.setProperty("theme_mode", previous)


def test_every_mapped_name_has_a_bundled_svg():
    bundled = set(icons.available_icons())
    missing = {k: v for k, v in icons.THEME_NAME_MAP.items() if v not in bundled}
    assert not missing


def test_main_window_icon_names_are_all_mapped():
    source = MAIN_WINDOW.read_text(encoding="utf-8")
    requested = set(re.findall(r'self\._icon\(\s*"([^"]+)"', source))
    assert requested, "expected MainWindow to request icons via self._icon(...)"
    bundled = set(icons.available_icons())
    unresolved = {n for n in requested if icons.resolve_name(n) not in bundled}
    assert not unresolved


@pytest.mark.parametrize("name", sorted(set(icons.THEME_NAME_MAP) | {"hand", "link"}))
def test_icon_renders_visible_pixmap(name):
    icon = icons.icon(name)
    assert isinstance(icon, QIcon) and not icon.isNull()
    pix = icon.pixmap(QSize(20, 20))
    assert not pix.isNull()
    assert _opaque_pixels(pix.toImage()) > 0


def test_every_bundled_icon_is_valid_svg():
    for name in icons.available_icons():
        pix = icons.pixmap(name, "#000000", 20)
        assert _opaque_pixels(pix.toImage()) > 0, name


def test_hidpi_pixmap_is_rendered_at_device_resolution():
    pix = icons.icon("zoom-in").pixmap(QSize(20, 20), 2.0)
    assert pix.devicePixelRatio() == 2.0
    assert (pix.width(), pix.height()) == (40, 40)


def test_disabled_state_is_fainter_than_normal():
    icon = icons.icon("save", "#000000")
    normal = icon.pixmap(QSize(20, 20), 1.0, QIcon.Mode.Normal).toImage()
    disabled = icon.pixmap(QSize(20, 20), 1.0, QIcon.Mode.Disabled).toImage()
    max_normal = max(normal.pixelColor(x, y).alpha() for x in range(20) for y in range(20))
    max_disabled = max(disabled.pixelColor(x, y).alpha() for x in range(20) for y in range(20))
    assert max_normal == 255
    assert 0 < max_disabled < max_normal


def test_light_and_dark_tints_differ(theme_mode):
    theme_mode("light")
    light = _darkest_opaque(icons.icon("zoom-in").pixmap(QSize(24, 24)).toImage())
    theme_mode("dark")
    dark = _darkest_opaque(icons.icon("zoom-in").pixmap(QSize(24, 24)).toImage())
    assert light is not None and dark is not None
    assert light.name() == icons.DEFAULT_COLORS["light"]
    assert dark.name() == icons.DEFAULT_COLORS["dark"]


def test_explicit_color_is_applied():
    pix = icons.icon("search", "#ff0000", 24).pixmap(QSize(24, 24))
    color = _darkest_opaque(pix.toImage())
    assert color is not None and color.name() == "#ff0000"


def test_icon_is_cached():
    assert icons.icon("copy", "#123456") is icons.icon("copy", "#123456")


def test_unknown_name_raises():
    with pytest.raises(icons.UnknownIconError, match="no-such-icon"):
        icons.icon("no-such-icon")


def test_default_color_falls_back_to_env_theme(theme_mode, monkeypatch):
    theme_mode(None)
    monkeypatch.setenv("NEOVIEW_THEME", "dark")
    assert icons.default_color() == icons.DEFAULT_COLORS["dark"]
    monkeypatch.delenv("NEOVIEW_THEME")
    assert icons.default_color() == icons.DEFAULT_COLORS["light"]
