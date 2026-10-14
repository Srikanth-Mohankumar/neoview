"""NeoView theme: design tokens, Qt palette and the generated application stylesheet.

Both themes are rendered from one stylesheet template, so light and dark always cover
exactly the same selectors and only the token values differ. The app runs on Qt's Fusion
style with an explicit QPalette (see ``apply_theme``) so Linux and Windows draw the same
widgets, and on the bundled Inter font (see ``neoview.resources.register_fonts``).

Public helpers for other modules:

- ``tokens(mode)``      -> dict of color tokens (hex strings) for "light" or "dark"
- ``current_mode()``    -> "light" or "dark" for the running app
- ``icon_color(mode)``  -> hex color to tint monochrome icons with
- ``build_palette(mode)`` / ``build_stylesheet(mode)`` / ``apply_theme(app, mode)``
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
)

THEMES = ("light", "dark")
DEFAULT_MODE = "light"

# Color tokens. Every theme defines exactly the same keys (a test enforces it).
_LIGHT: dict[str, str] = {
    "background": "#f3f4f6",      # window chrome: menu bar, toolbar, tab strip, status bar
    "surface": "#ffffff",         # panels, docks, lists, inputs
    "surface_alt": "#f7f8fa",     # alternating rows, inactive tabs inside panels
    "surface_raised": "#ffffff",  # menus, popups, tooltips, floating badges
    "hover": "#e7e9ed",
    "pressed": "#dcdfe4",
    "border": "#dfe1e6",
    "border_strong": "#c4c8cf",
    "text": "#1f2329",
    "text_muted": "#5c636e",
    "text_disabled": "#a3a9b2",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_text": "#ffffff",
    "selection": "#dbe6fd",
    "selection_text": "#1f2329",
    "danger": "#d93025",
    "canvas": "#e8e8ec",          # QGraphicsView background behind the pages
    "scrollbar": "#b9bec6",
    "scrollbar_hover": "#8f959e",
}

_DARK: dict[str, str] = {
    "background": "#2b2d31",
    "surface": "#232428",
    "surface_alt": "#27292d",
    "surface_raised": "#313338",
    "hover": "#3a3c42",
    "pressed": "#45484f",
    "border": "#3b3e44",
    "border_strong": "#4e5159",
    "text": "#e6e7ea",
    "text_muted": "#a2a6ae",
    "text_disabled": "#666a72",
    "accent": "#4c8dff",
    "accent_hover": "#6ea2ff",
    "accent_text": "#ffffff",
    "selection": "#2c4775",
    "selection_text": "#ffffff",
    "danger": "#f28b82",
    "canvas": "#1e1f22",
    "scrollbar": "#585c64",
    "scrollbar_hover": "#7a7f88",
}

_TOKENS: dict[str, dict[str, str]] = {"light": _LIGHT, "dark": _DARK}

SPACING: dict[str, int] = {"xs": 4, "sm": 8, "md": 12, "lg": 16}
RADIUS: dict[str, int] = {"sm": 4, "md": 6, "lg": 8}
FONT_SIZE: dict[str, int] = {"xs": 11, "sm": 12, "md": 13, "lg": 15}  # pixels

UI_FONT_FAMILY = "Inter"
UI_FONT_STACK = '"Inter", sans-serif'
# Numeric read-outs use the bundled UI font too: a system fixed-pitch font differs per OS
# (DejaVu Sans Mono vs Courier New), which is exactly what the redesign removes.
MONO_FONT_STACK = UI_FONT_STACK


def normalize_mode(mode: str | None) -> str:
    """Map any user value to "light" or "dark" (unknown values fall back to light)."""
    value = (mode or "").strip().lower()
    return value if value in THEMES else DEFAULT_MODE


def tokens(mode: str | None = None) -> dict[str, str]:
    """Return a copy of the color tokens for ``mode`` (default: the current mode)."""
    return dict(_TOKENS[normalize_mode(mode or current_mode())])


def current_mode() -> str:
    """Return the active theme: the app's "theme_mode" property, else NEOVIEW_THEME."""
    app = QGuiApplication.instance()
    if app is not None:
        value = app.property("theme_mode")
        if value:
            return normalize_mode(str(value))
    return normalize_mode(os.getenv("NEOVIEW_THEME", DEFAULT_MODE))


def icon_color(mode: str | None = None) -> str:
    """Return the hex color monochrome icons should be tinted with."""
    return tokens(mode)["text"]


def _rgba(hex_color: str, alpha: int) -> str:
    color = QColor(hex_color)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


# Small glyphs the stylesheet needs (combo/spin arrows, check mark, close/float buttons).
# Once a stylesheet restyles those sub-controls Qt stops drawing the native glyphs, and
# url() only takes file paths, so they are painted here once per process into a private
# temp dir (removed at exit), at 1x and @2x for HiDPI screens.
_GLYPH_SIZES: dict[str, int] = {
    "chevron_down": 10,
    "chevron_up": 10,
    "check": 12,
    "close": 10,
    "float": 10,
}
_glyph_dir: Path | None = None


def _glyph_root() -> Path:
    global _glyph_dir
    if _glyph_dir is None:
        _glyph_dir = Path(tempfile.mkdtemp(prefix="neoview-theme-"))
        atexit.register(shutil.rmtree, str(_glyph_dir), True)
    return _glyph_dir


def _glyph_path(name: str, size: float) -> QPainterPath:
    s = size
    path = QPainterPath()
    if name == "chevron_down":
        path.moveTo(0.2 * s, 0.35 * s)
        path.lineTo(0.5 * s, 0.65 * s)
        path.lineTo(0.8 * s, 0.35 * s)
    elif name == "chevron_up":
        path.moveTo(0.2 * s, 0.65 * s)
        path.lineTo(0.5 * s, 0.35 * s)
        path.lineTo(0.8 * s, 0.65 * s)
    elif name == "check":
        path.moveTo(0.18 * s, 0.52 * s)
        path.lineTo(0.42 * s, 0.75 * s)
        path.lineTo(0.82 * s, 0.28 * s)
    elif name == "close":
        path.moveTo(0.2 * s, 0.2 * s)
        path.lineTo(0.8 * s, 0.8 * s)
        path.moveTo(0.8 * s, 0.2 * s)
        path.lineTo(0.2 * s, 0.8 * s)
    elif name == "float":
        path.addRect(QRectF(QPointF(0.15 * s, 0.35 * s), QPointF(0.65 * s, 0.85 * s)))
        path.moveTo(0.35 * s, 0.15 * s)
        path.lineTo(0.85 * s, 0.15 * s)
        path.lineTo(0.85 * s, 0.65 * s)
    return path


def _paint_glyph(name: str, color: str, target: Path, scale: int) -> None:
    size = _GLYPH_SIZES[name]
    image = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), 1.5 * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_glyph_path(name, size * scale))
    painter.end()
    image.save(str(target), "PNG")


def glyph_url(name: str, color: str) -> str:
    """Return a stylesheet-ready file path for glyph ``name`` painted in ``color``."""
    root = _glyph_root()
    stem = f"{name}-{color.lstrip('#').lower()}"
    base = root / f"{stem}.png"
    if not base.exists():
        _paint_glyph(name, color, root / f"{stem}@2x.png", 2)
        _paint_glyph(name, color, base, 1)
    return base.as_posix()


def build_palette(mode: str | None = None) -> QPalette:
    """Build the QPalette matching the stylesheet, for palette-driven drawing in Fusion."""
    t = tokens(mode)
    pal = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup

    def put(r: QPalette.ColorRole, value: str) -> None:
        pal.setColor(r, QColor(value))

    put(role.Window, t["background"])
    put(role.WindowText, t["text"])
    put(role.Base, t["surface"])
    put(role.AlternateBase, t["surface_alt"])
    put(role.Text, t["text"])
    put(role.Button, t["surface"])
    put(role.ButtonText, t["text"])
    put(role.BrightText, t["danger"])
    put(role.ToolTipBase, t["surface_raised"])
    put(role.ToolTipText, t["text"])
    put(role.PlaceholderText, t["text_muted"])
    put(role.Highlight, t["accent"])
    put(role.HighlightedText, t["accent_text"])
    put(role.Link, t["accent"])
    put(role.LinkVisited, t["accent_hover"])
    put(role.Light, t["surface_raised"])
    put(role.Midlight, t["border"])
    put(role.Mid, t["border_strong"])
    put(role.Dark, t["border_strong"])
    put(role.Shadow, "#000000")
    for r in (role.WindowText, role.Text, role.ButtonText, role.HighlightedText):
        pal.setColor(group.Disabled, r, QColor(t["text_disabled"]))
    pal.setColor(group.Disabled, role.Highlight, QColor(t["border_strong"]))
    pal.setColor(group.Disabled, role.Base, QColor(t["background"]))
    return pal


_TEMPLATE = Template(
    """
* {
    font-family: $font_stack;
    font-size: ${fs_md}px;
    selection-background-color: $accent;
    selection-color: $accent_text;
}

/* Main containers. The window/dialog rule must come AFTER the transparent QWidget
   rule: both are plain type selectors, so the later one wins, and a transparent
   window shows black on X11 (About, Print and message boxes). */
QWidget {
    background: transparent;
    color: $text;
}
QMainWindow,
QDialog {
    background: $background;
}
QMainWindow::separator {
    background: $background;
    width: 5px;
    height: 5px;
}
QMainWindow::separator:hover {
    background: $accent;
}
QSplitter::handle {
    background: $background;
}
QSplitter::handle:horizontal {
    width: 5px;
}
QSplitter::handle:vertical {
    height: 5px;
}
QSplitter::handle:hover {
    background: $accent;
}

/* Document tabs */
QTabWidget::pane {
    border: none;
    background: $canvas;
}
QTabBar {
    background: $background;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background: transparent;
    border: none;
    border-right: 1px solid $border;
    border-bottom: 1px solid $border;
    padding: ${sp_sm}px ${sp_md}px;
    min-width: 96px;
    max-width: 240px;
    font-size: ${fs_sm}px;
    color: $text_muted;
}
QTabBar::tab:selected {
    background: $surface;
    color: $text;
    border-bottom: 2px solid $accent;
}
QTabBar::tab:hover:!selected {
    background: $hover;
    color: $text;
}
QTabBar::close-button {
    image: url("$img_close");
    subcontrol-position: right;
    margin: 2px;
    padding: 2px;
    border-radius: ${r_sm}px;
}
QTabBar::close-button:hover {
    background: $pressed;
}

/* Menu bar and menus */
QMenuBar {
    background: $background;
    border-bottom: 1px solid $border;
    padding: 2px ${sp_xs}px;
    spacing: 2px;
}
QMenuBar::item {
    background: transparent;
    padding: ${sp_xs}px 10px;
    border-radius: ${r_sm}px;
    color: $text;
}
QMenuBar::item:selected {
    background: $hover;
}
QMenuBar::item:pressed {
    background: $pressed;
}
QMenu {
    background: $surface_raised;
    border: 1px solid $border_strong;
    border-radius: 0;
    padding: ${sp_xs}px;
}
QMenu::item {
    background: transparent;
    padding: 6px ${sp_lg}px 6px 28px;
    border-radius: ${r_sm}px;
    min-width: 160px;
    color: $text;
}
QMenu::item:selected {
    background: $hover;
}
QMenu::item:disabled {
    color: $text_disabled;
}
QMenu::separator {
    height: 1px;
    background: $border;
    margin: ${sp_xs}px ${sp_sm}px;
}
QMenu::icon {
    padding-left: ${sp_sm}px;
}

/* Toolbars */
QToolBar {
    background: $background;
    border: none;
    border-bottom: 1px solid $border;
    spacing: ${sp_xs}px;
    padding: ${sp_xs}px ${sp_sm}px;
}
QToolBar::separator {
    width: 1px;
    background: $border;
    margin: 6px ${sp_xs}px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: ${r_md}px;
    padding: ${sp_xs}px;
    min-width: 22px;
    min-height: 22px;
    color: $text;
    font-size: ${fs_sm}px;
}
QToolButton:hover {
    background: $hover;
}
QToolButton:pressed {
    background: $pressed;
}
QToolButton:checked {
    background: $selection;
    border-color: $selection;
    color: $selection_text;
}
QToolButton:checked:hover {
    border-color: $accent;
}
QToolButton:focus {
    border-color: $accent;
    outline: none;
}
QToolButton:disabled {
    color: $text_disabled;
    background: transparent;
    border-color: transparent;
}
QToolButton::menu-indicator {
    image: none;
    width: 0;
}

/* Status bar */
QStatusBar {
    background: $background;
    border-top: 1px solid $border;
    color: $text_muted;
    font-size: ${fs_sm}px;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    padding: 0 6px;
    color: $text_muted;
    font-size: ${fs_sm}px;
}

/* PDF canvas */
QGraphicsView {
    background: $canvas;
    border: none;
}

/* Scroll bars: thin, no arrow buttons */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0;
}
QScrollBar::handle {
    background: $scrollbar;
    border-radius: 3px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    min-height: 32px;
}
QScrollBar::handle:horizontal {
    min-width: 32px;
}
QScrollBar::handle:hover,
QScrollBar::handle:pressed {
    background: $scrollbar_hover;
}
QScrollBar::add-line,
QScrollBar::sub-line {
    width: 0;
    height: 0;
    border: none;
    background: none;
}
QScrollBar::add-page,
QScrollBar::sub-page {
    background: none;
}
QAbstractScrollArea::corner {
    background: transparent;
}

/* Inputs */
QLineEdit,
QComboBox,
QPlainTextEdit,
QTextEdit,
QSpinBox,
QDoubleSpinBox {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: ${r_md}px;
    padding: ${sp_xs}px ${sp_sm}px;
    color: $text;
    font-size: ${fs_md}px;
    min-height: 20px;
}
QLineEdit:hover,
QComboBox:hover,
QPlainTextEdit:hover,
QTextEdit:hover,
QSpinBox:hover,
QDoubleSpinBox:hover {
    border-color: $text_muted;
}
QLineEdit:focus,
QComboBox:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {
    border-color: $accent;
}
QLineEdit:disabled,
QComboBox:disabled,
QPlainTextEdit:disabled,
QTextEdit:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled {
    background: $background;
    border-color: $border;
    color: $text_disabled;
}
QComboBox {
    padding-right: 24px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 20px;
    border: none;
}
QComboBox::down-arrow {
    image: url("$img_chevron_down");
    width: 10px;
    height: 10px;
}
QComboBox QAbstractItemView {
    background: $surface_raised;
    border: 1px solid $border_strong;
    border-radius: 0;
    padding: ${sp_xs}px;
    color: $text;
    selection-background-color: $selection;
    selection-color: $selection_text;
    outline: none;
}
QSpinBox,
QDoubleSpinBox {
    padding-right: 20px;
}
QSpinBox::up-button,
QDoubleSpinBox::up-button,
QSpinBox::down-button,
QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    width: 18px;
    border: none;
    background: transparent;
}
QSpinBox::up-button,
QDoubleSpinBox::up-button {
    subcontrol-position: top right;
}
QSpinBox::down-button,
QDoubleSpinBox::down-button {
    subcontrol-position: bottom right;
}
QSpinBox::up-arrow,
QDoubleSpinBox::up-arrow {
    image: url("$img_chevron_up");
    width: 10px;
    height: 10px;
}
QSpinBox::down-arrow,
QDoubleSpinBox::down-arrow {
    image: url("$img_chevron_down");
    width: 10px;
    height: 10px;
}
QSpinBox::up-button:hover,
QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover,
QDoubleSpinBox::down-button:hover {
    background: $hover;
}

/* Buttons: plain is secondary-looking, default/primary is filled accent */
QPushButton {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: ${r_md}px;
    padding: 5px 14px;
    color: $text;
    font-size: ${fs_md}px;
    min-height: 20px;
}
QPushButton:hover {
    background: $hover;
}
QPushButton:pressed {
    background: $pressed;
}
QPushButton:focus {
    border-color: $accent;
    outline: none;
}
QPushButton:disabled {
    background: $background;
    border-color: $border;
    color: $text_disabled;
}
QPushButton:default,
QPushButton[primary="true"] {
    background: $accent;
    border-color: $accent;
    color: $accent_text;
}
QPushButton:default:hover,
QPushButton[primary="true"]:hover {
    background: $accent_hover;
    border-color: $accent_hover;
}
QPushButton[secondary="true"] {
    background: transparent;
    border: 1px solid $border;
    color: $text_muted;
}
QPushButton[secondary="true"]:hover {
    background: $hover;
    color: $text;
}

/* Check boxes and radio buttons */
QCheckBox,
QRadioButton {
    spacing: 6px;
    color: $text;
}
QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border: 1px solid $border_strong;
    border-radius: ${r_sm}px;
    background: $surface;
}
QCheckBox::indicator:hover {
    border-color: $accent;
}
QCheckBox::indicator:checked {
    image: url("$img_check");
    background: $accent;
    border-color: $accent;
}
QCheckBox::indicator:disabled {
    background: $background;
    border-color: $border;
}
QCheckBox:disabled,
QRadioButton:disabled {
    color: $text_disabled;
}

/* Lists and trees */
QListWidget,
QListView,
QTreeWidget,
QTreeView {
    background: $surface;
    border: 1px solid $border;
    border-radius: ${r_md}px;
    padding: 2px;
    outline: none;
    font-size: ${fs_sm}px;
}
QListWidget::item,
QListView::item,
QTreeWidget::item,
QTreeView::item {
    padding: ${sp_xs}px 6px;
    border-radius: ${r_sm}px;
    border: none;
    color: $text;
}
QListWidget::item:selected,
QListView::item:selected,
QTreeWidget::item:selected,
QTreeView::item:selected {
    background: $selection;
    color: $selection_text;
}
QListWidget::item:hover:!selected,
QListView::item:hover:!selected,
QTreeWidget::item:hover:!selected,
QTreeView::item:hover:!selected {
    background: $hover;
}
QListWidget::item:alternate,
QListView::item:alternate {
    background: $surface_alt;
}
QTreeWidget::branch,
QTreeView::branch {
    background: transparent;
}
QHeaderView::section {
    background: $background;
    border: none;
    border-bottom: 1px solid $border;
    padding: ${sp_xs}px ${sp_sm}px;
    font-size: ${fs_xs}px;
    color: $text_muted;
}

/* Dock widgets */
QDockWidget {
    font-size: ${fs_sm}px;
    color: $text;
    titlebar-close-icon: url("$img_close");
    titlebar-normal-icon: url("$img_float");
}
QDockWidget::title {
    background: $background;
    border: none;
    border-bottom: 1px solid $border;
    padding: 6px ${sp_sm}px;
    text-align: left;
}
QDockWidget::close-button,
QDockWidget::float-button {
    border: none;
    border-radius: ${r_sm}px;
    background: transparent;
    padding: 2px;
}
QDockWidget::close-button:hover,
QDockWidget::float-button:hover {
    background: $hover;
}
QDockWidget > QWidget {
    border: none;
    background: $surface;
}

/* Sliders */
QSlider::groove:horizontal {
    background: $border;
    height: 4px;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: $accent;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: $surface_raised;
    border: 1px solid $border_strong;
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    border-color: $accent;
}

/* Progress bars */
QProgressBar {
    background: $border;
    border: none;
    border-radius: 3px;
    text-align: center;
    color: $text;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: 3px;
}

/* Group boxes */
QGroupBox {
    border: 1px solid $border;
    border-radius: ${r_md}px;
    margin-top: ${sp_md}px;
    padding: ${sp_sm}px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: ${sp_sm}px;
    padding: 0 ${sp_xs}px;
    color: $text_muted;
}

/* Tooltips */
QToolTip {
    background: $surface_raised;
    border: 1px solid $border_strong;
    color: $text;
    padding: ${sp_xs}px ${sp_sm}px;
    border-radius: 0;
    font-size: ${fs_sm}px;
}

/* Separator lines */
QFrame[separator="true"] {
    background: $border;
    max-height: 1px;
    min-height: 1px;
    margin: ${sp_xs}px 0;
}

/* Inspector panel */
QWidget#InspectorPanel {
    background: $surface;
}
QToolButton#InspectorSectionHeader {
    background: transparent;
    border: none;
    border-radius: 0;
    font-weight: 600;
    font-size: ${fs_xs}px;
    text-align: left;
    padding: ${sp_sm}px ${sp_xs}px 6px 0;
    color: $text_muted;
}
QToolButton#InspectorSectionHeader:hover {
    color: $text;
}
QWidget#InspectorSectionContent {
    background: transparent;
}
QLabel#InfoLabel {
    color: $text_muted;
    font-size: ${fs_xs}px;
}
QLabel#InfoValue {
    color: $text;
    font-weight: 600;
    font-size: ${fs_xs}px;
}
QLabel#MonoValue {
    color: $text;
    font-family: $mono_stack;
    font-size: ${fs_md}px;
    font-weight: 600;
}

/* Status indicators */
QLabel#StatusDot {
    min-width: 8px;
    max-width: 8px;
    min-height: 8px;
    max-height: 8px;
    border-radius: 4px;
    background: $accent;
}
QLabel#StatusDot[offline="true"] {
    background: $text_disabled;
}

/* Floating badges over the canvas */
QLabel#FloatingMeasureBadge {
    background: $badge_bg;
    border: 1px solid $badge_border;
    border-radius: ${r_sm}px;
    padding: 3px ${sp_sm}px;
    color: $text;
    font-family: $mono_stack;
    font-size: ${fs_xs}px;
    font-weight: 600;
}
QLabel#LinkBadge {
    background: $badge_bg;
    border: 1px solid $badge_border;
    border-radius: 9px;
}

/* Panel toggle buttons in the toolbar */
QPushButton#PanelToggleBtn {
    background: transparent;
    border: 1px solid transparent;
    border-radius: ${r_md}px;
    padding: ${sp_xs}px ${sp_sm}px;
    font-size: ${fs_sm}px;
    color: $text_muted;
    min-height: 22px;
}
QPushButton#PanelToggleBtn:hover {
    background: $hover;
    color: $text;
}
QPushButton#PanelToggleBtn:checked {
    background: $selection;
    color: $selection_text;
}

/* Inspector tab widget */
QTabWidget#InspectorTabs::pane {
    border: none;
    background: transparent;
}
QTabWidget#InspectorTabs > QTabBar {
    background: $surface;
}
QTabWidget#InspectorTabs > QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 1px solid $border;
    padding: 6px 10px;
    font-size: ${fs_sm}px;
    color: $text_muted;
    min-width: 0;
    max-width: 9999px;
}
QTabWidget#InspectorTabs > QTabBar::tab:selected {
    color: $text;
    border-bottom: 2px solid $accent;
}
QTabWidget#InspectorTabs > QTabBar::tab:hover:!selected {
    background: $hover;
    color: $text;
}
"""
)


def build_stylesheet(mode: str | None = None, mono_family: str | None = None) -> str:
    """Render the application stylesheet for ``mode``.

    ``mono_family`` names the family for numeric read-outs; ``apply_theme`` passes the
    registered UI font so read-outs match on every OS.
    """
    t = tokens(mode)
    mono_stack = MONO_FONT_STACK
    if mono_family:
        mono_stack = f'"{mono_family}", {MONO_FONT_STACK}'
    values: dict[str, object] = dict(t)
    values.update({f"sp_{k}": v for k, v in SPACING.items()})
    values.update({f"r_{k}": v for k, v in RADIUS.items()})
    values.update({f"fs_{k}": v for k, v in FONT_SIZE.items()})
    values.update(
        font_stack=UI_FONT_STACK,
        mono_stack=mono_stack,
        badge_bg=_rgba(t["surface_raised"], 240),
        badge_border=_rgba(t["accent"], 160),
        img_chevron_down=glyph_url("chevron_down", t["text_muted"]),
        img_chevron_up=glyph_url("chevron_up", t["text_muted"]),
        img_check=glyph_url("check", t["accent_text"]),
        img_close=glyph_url("close", t["text_muted"]),
        img_float=glyph_url("float", t["text_muted"]),
    )
    return _TEMPLATE.substitute(values)


def apply_theme(app: QGuiApplication, mode: str | None = None) -> str:
    """Apply style, palette, font and stylesheet for ``mode`` to ``app``; return the mode.

    Order matters: setStyle() resets the palette, so the palette is set after it.
    Registers the bundled fonts first, so this needs a running QApplication.
    """
    from neoview.resources import app_font_family

    resolved = normalize_mode(mode if mode is not None else os.getenv("NEOVIEW_THEME"))
    app.setProperty("theme_mode", resolved)
    if hasattr(app, "setStyle"):
        app.setStyle("Fusion")
    app.setPalette(build_palette(resolved))
    family = app_font_family() or UI_FONT_FAMILY
    font = QFont(family)
    font.setPixelSize(FONT_SIZE["md"])
    app.setFont(font)
    if hasattr(app, "setStyleSheet"):
        app.setStyleSheet(build_stylesheet(resolved, mono_family=family))
    return resolved


def __getattr__(name: str) -> str:
    """Build LIGHT_STYLE / DARK_STYLE on first access (they paint glyph files)."""
    if name == "LIGHT_STYLE":
        return build_stylesheet("light")
    if name == "DARK_STYLE":
        return build_stylesheet("dark")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
