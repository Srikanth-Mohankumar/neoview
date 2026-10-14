"""PdfView follows the theme: canvas colour token and the measurement badge font."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication

from neoview import theme
from neoview.ui.pdf_view import PdfView


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


def _canvas(view: PdfView) -> QColor:
    return view.backgroundBrush().color()


def test_canvas_uses_theme_token(qtbot, _restore_app_theme):
    theme.apply_theme(_restore_app_theme, "light")
    view = PdfView()
    qtbot.addWidget(view)
    assert _canvas(view) == QColor(theme.tokens("light")["canvas"])


def test_canvas_follows_theme_change(qtbot, _restore_app_theme):
    app = _restore_app_theme
    theme.apply_theme(app, "light")
    view = PdfView()
    qtbot.addWidget(view)
    view.show()
    QApplication.processEvents()

    theme.apply_theme(app, "dark")
    QApplication.processEvents()
    assert _canvas(view) == QColor(theme.tokens("dark")["canvas"])

    theme.apply_theme(app, "light")
    QApplication.processEvents()
    assert _canvas(view) == QColor(theme.tokens("light")["canvas"])


def test_apply_theme_colors_is_public(qtbot, _restore_app_theme):
    view = PdfView()
    qtbot.addWidget(view)
    _restore_app_theme.setProperty("theme_mode", "dark")
    view.apply_theme_colors()
    assert _canvas(view) == QColor(theme.tokens("dark")["canvas"])


def test_measure_badge_uses_app_font_with_tabular_figures(qtbot, _restore_app_theme):
    app = _restore_app_theme
    theme.apply_theme(app, "light")
    view = PdfView()
    qtbot.addWidget(view)
    badge = view._measure_badge
    badge.ensurePolished()
    font = badge.font()
    assert font.family() == app.font().family()
    assert QFont.Tag("tnum") in font.featureTags()
    assert font.featureValue(QFont.Tag("tnum")) == 1
    # Size and weight still come from the theme stylesheet's badge rule.
    assert font.weight() == QFont.Weight.DemiBold
