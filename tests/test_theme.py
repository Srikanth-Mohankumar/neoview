"""Tests for the design-token theme, palette, stylesheet and bundled fonts."""

from __future__ import annotations

import re
from importlib import resources

import pytest
from PySide6.QtGui import QFontDatabase, QFontInfo, QPalette
from PySide6.QtWidgets import QApplication

from neoview import theme
from neoview.resources import APP_FONT_FILES, app_font_family, register_fonts

_HEX = re.compile(r"^#[0-9a-f]{6}$")
_SELECTOR = re.compile(r"^([^{}\n][^{}]*)\{", re.MULTILINE)


def _selectors(sheet: str) -> list[str]:
    return [" ".join(m.group(1).split()) for m in _SELECTOR.finditer(sheet)]


@pytest.fixture
def _restore_app_theme(_qt_app):
    """apply_theme mutates the shared QApplication; put it back afterwards."""
    app = QApplication.instance()
    saved = (app.styleSheet(), app.palette(), app.font(), app.property("theme_mode"))
    yield app
    sheet, palette, font, mode = saved
    app.setStyleSheet(sheet)
    app.setPalette(palette)
    app.setFont(font)
    app.setProperty("theme_mode", mode)


def test_both_themes_define_the_same_color_tokens():
    light, dark = theme.tokens("light"), theme.tokens("dark")
    assert set(light) == set(dark)
    required = {
        "background", "surface", "surface_raised", "border", "text", "text_muted",
        "accent", "accent_hover", "selection", "danger", "canvas",
    }
    assert required <= set(light)
    for value in (*light.values(), *dark.values()):
        assert _HEX.match(value), value


def test_tokens_returns_a_copy():
    theme.tokens("light")["text"] = "#000001"
    assert theme.tokens("light")["text"] != "#000001"


def test_light_and_dark_stylesheets_cover_the_same_selectors():
    light = _selectors(theme.LIGHT_STYLE)
    dark = _selectors(theme.DARK_STYLE)
    assert light == dark
    assert len(light) > 50
    assert theme.LIGHT_STYLE != theme.DARK_STYLE


def test_stylesheet_has_no_unfilled_placeholders_or_os_font_names():
    for sheet in (theme.LIGHT_STYLE, theme.DARK_STYLE):
        assert "$" not in sheet
        for os_font in ("Segoe UI", "SF Pro", "Helvetica", "Consolas", "Menlo"):
            assert os_font not in sheet


def test_stylesheet_keeps_selectors_other_modules_rely_on():
    sheet = theme.LIGHT_STYLE
    for selector in (
        "QWidget#InspectorPanel", "QLabel#MonoValue", "QLabel#FloatingMeasureBadge",
        "QLabel#LinkBadge", "QPushButton#PanelToggleBtn", 'QPushButton[secondary="true"]',
        'QFrame[separator="true"]', 'QLabel#StatusDot[offline="true"]',
        "QTabWidget#InspectorTabs::pane", "QGraphicsView", "QToolTip", "QScrollBar",
        "QDockWidget::title", "QSplitter::handle", "QMenuBar", "QStatusBar",
    ):
        assert selector in sheet, selector


def test_stylesheet_glyph_files_exist():
    urls = re.findall(r'url\("([^"]+)"\)', theme.DARK_STYLE)
    assert urls
    from pathlib import Path

    for url in urls:
        assert Path(url).is_file(), url
        assert Path(url.replace(".png", "@2x.png")).is_file(), url


def test_icon_color_is_the_text_token():
    for mode in theme.THEMES:
        assert theme.icon_color(mode) == theme.tokens(mode)["text"]
        assert _HEX.match(theme.icon_color(mode))


def test_current_mode_follows_env_and_app_property(monkeypatch, _restore_app_theme):
    app = _restore_app_theme
    app.setProperty("theme_mode", None)
    monkeypatch.setenv("NEOVIEW_THEME", "dark")
    assert theme.current_mode() == "dark"
    monkeypatch.setenv("NEOVIEW_THEME", "bogus")
    assert theme.current_mode() == "light"
    app.setProperty("theme_mode", "dark")
    assert theme.current_mode() == "dark"


def test_build_palette_matches_tokens():
    for mode in theme.THEMES:
        t = theme.tokens(mode)
        pal = theme.build_palette(mode)
        assert pal.color(QPalette.ColorRole.Window).name() == t["background"]
        assert pal.color(QPalette.ColorRole.Base).name() == t["surface"]
        assert pal.color(QPalette.ColorRole.WindowText).name() == t["text"]
        assert pal.color(QPalette.ColorRole.Highlight).name() == t["accent"]


def test_apply_theme_sets_fusion_palette_font_and_mode(_restore_app_theme):
    app = _restore_app_theme
    assert theme.apply_theme(app, "dark") == "dark"
    assert app.property("theme_mode") == "dark"
    assert theme.current_mode() == "dark"
    assert app.palette().color(QPalette.ColorRole.Window).name() == theme.tokens("dark")[
        "background"
    ]
    assert QFontInfo(app.font()).family() == "Inter"
    assert "QGraphicsView" in app.styleSheet()
    assert theme.apply_theme(app, "nonsense") == "light"


def test_apply_theme_forces_fusion_before_the_palette(_qt_app):
    calls: list[str] = []

    class _Recorder:
        def setProperty(self, name, value):
            calls.append(f"property:{name}={value}")

        def setStyle(self, style):
            calls.append(f"style:{style}")

        def setPalette(self, _palette):
            calls.append("palette")

        def setFont(self, _font):
            calls.append("font")

        def setStyleSheet(self, _sheet):
            calls.append("stylesheet")

    theme.apply_theme(_Recorder(), "light")
    assert "style:Fusion" in calls
    # setStyle() resets the palette, so the palette must come after it.
    assert calls.index("style:Fusion") < calls.index("palette") < calls.index("stylesheet")


def test_bundled_fonts_and_license_are_package_data():
    fonts = resources.files("neoview.assets").joinpath("fonts")
    for name in (*APP_FONT_FILES, "OFL.txt"):
        assert fonts.joinpath(name).is_file(), name
    assert "SIL OPEN FONT LICENSE" in fonts.joinpath("OFL.txt").read_text(encoding="utf-8")


def test_register_fonts_registers_inter_weights(_qt_app):
    families = register_fonts()
    assert "Inter" in families
    assert app_font_family() == "Inter"
    assert register_fonts() == families  # idempotent
    styles = set(QFontDatabase.styles("Inter"))
    assert {"Regular", "Medium", "SemiBold"} <= styles
