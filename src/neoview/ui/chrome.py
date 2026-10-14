"""Window chrome helpers: theme-aware icon bindings and the main-window stylesheet.

``neoview.theme`` owns the application-wide stylesheet. The widgets MainWindow adds on top
of the stock Qt ones (toolbar groups, search field, sidebar, inspector, welcome panel) are
styled here, from the same tokens, and installed on the MainWindow itself so they cascade
to its children. Both are regenerated when the theme changes at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from string import Template

import shiboken6
from PySide6.QtGui import QIcon

from neoview import theme
from neoview.ui import icons

# Toolbar hit target (px): 18 px glyph + 6 px padding on each side + 1 px border.
TOOLBAR_ICON = 18
HIT_TARGET = 32


class IconBinder:
    """Remember which widget/action shows which bundled icon so a theme switch can re-tint.

    QIcon pixmaps are rendered once with the theme's text colour; after ``apply_theme`` the
    old icons keep the old tint. ``retint()`` drops the icon cache and sets fresh icons.
    """

    def __init__(self) -> None:
        self._bindings: list[tuple[object, str, Callable[[QIcon], None] | None]] = []

    def bind(self, target, name: str, setter: Callable[[QIcon], None] | None = None):
        """Set ``icons.icon(name)`` on ``target`` (anything with ``setIcon``) and remember it."""
        icon = icons.icon(name)
        if setter is not None:
            setter(icon)
        else:
            target.setIcon(icon)
        self._bindings.append((target, name, setter))
        return target

    def names_for(self, target) -> list[str]:
        return [name for obj, name, _setter in self._bindings if obj is target]

    def retint(self) -> None:
        icons.clear_cache()
        alive: list[tuple[object, str, Callable[[QIcon], None] | None]] = []
        for target, name, setter in self._bindings:
            if not shiboken6.isValid(target):
                continue
            icon = icons.icon(name)
            if setter is not None:
                setter(icon)
            else:
                target.setIcon(icon)
            alive.append((target, name, setter))
        self._bindings = alive


_TEMPLATE = Template(
    """
/* ---- Main toolbar: one compact row of 32 px icon buttons ---- */
QToolBar#MainToolbar {
    padding: 4px ${sp_sm}px;
    spacing: 2px;
}
QToolBar#MainToolbar::separator {
    width: 1px;
    background: $border;
    margin: 7px 6px;
}
QToolBar#MainToolbar QToolButton {
    padding: 6px;
    min-width: 18px;
    min-height: 18px;
    border-radius: ${r_md}px;
}
QToolBar#MainToolbar QToolButton:checked {
    background: $selection;
    border-color: $selection;
}

/* Tool segmented control */
QFrame#ToolSegment {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: ${r_md}px;
}
QFrame#ToolSegment QToolButton {
    border: none;
    border-radius: ${r_sm}px;
    padding: 4px 8px;
    margin: 0px;
}
QFrame#ToolSegment QToolButton:checked {
    background: $accent;
    color: $accent_text;
}
QFrame#ToolSegment QToolButton:checked:hover {
    background: $accent_hover;
}

/* Page field "n / N" */
QLineEdit#PageInput {
    padding: 3px 4px;
    min-height: 20px;
}
QLabel#PageTotal {
    color: $text_muted;
    padding: 0 4px 0 6px;
    font-size: ${fs_md}px;
}

QComboBox#ZoomCombo {
    padding-top: 3px;
    padding-bottom: 3px;
    min-height: 20px;
}

/* Search field: icon, text, count, case toggle, previous/next, results list */
QFrame#SearchField {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: ${r_md}px;
}
QFrame#SearchField:hover {
    border-color: $text_muted;
}
QFrame#SearchField[focused="true"] {
    border-color: $accent;
}
QFrame#SearchField QLineEdit {
    border: none;
    background: transparent;
    padding: 3px 2px;
    min-height: 20px;
}
QFrame#SearchField QToolButton {
    padding: 3px;
    min-width: 16px;
    min-height: 16px;
    border-radius: ${r_sm}px;
    border: none;
}
QFrame#SearchField QToolButton:checked {
    background: $selection;
}
QLabel#SearchIcon {
    padding-left: 6px;
}
QLabel#SearchCount {
    color: $text_muted;
    font-size: ${fs_xs}px;
    padding: 0 2px;
}

/* Muted helper text (was inline #888) */
QLabel#MutedLabel {
    color: $text_muted;
    font-size: ${fs_xs}px;
    padding: 0 2px;
}

/* ---- Left sidebar ---- */
QWidget#Sidebar {
    background: $surface;
}
QWidget#SidebarHeader {
    background: $surface;
    border-bottom: 1px solid $border;
}
QToolButton#SidebarTab {
    padding: 5px;
    min-width: 18px;
    min-height: 18px;
    border-radius: ${r_md}px;
    border: 1px solid transparent;
}
QToolButton#SidebarTab:checked {
    background: $selection;
    border-color: $selection;
}
QLabel#PanelTitle {
    color: $text;
    font-weight: 600;
    font-size: ${fs_sm}px;
}
QLabel#EmptyHint {
    color: $text_muted;
    font-size: ${fs_sm}px;
    padding: ${sp_lg}px ${sp_md}px;
}
QWidget#Sidebar QListWidget,
QWidget#Sidebar QTreeWidget {
    border: none;
    border-radius: 0;
    background: $surface;
}
QListWidget#ThumbnailList::item {
    border-radius: ${r_sm}px;
    padding: ${sp_xs}px;
    color: $text_muted;
}
QListWidget#ThumbnailList::item:selected {
    background: $selection;
    color: $selection_text;
}

/* ---- Panel title bars (inspector, search results) ---- */
QWidget#PanelTitleBar {
    background: $surface;
    border-bottom: 1px solid $border;
}
QWidget#PanelTitleBar QToolButton {
    padding: 3px;
    border-radius: ${r_sm}px;
    min-width: 16px;
    min-height: 16px;
}
QWidget#InspectorBody,
QScrollArea#InspectorScroll,
QWidget#SearchPanel {
    background: $surface;
    border: none;
}

/* ---- Empty state ---- */
QWidget#WelcomePanel {
    background: $canvas;
}
QFrame#WelcomeCard {
    background: $surface;
    border: 1px solid $border;
    border-radius: ${r_lg}px;
}
QLabel#WelcomeTitle {
    color: $text;
    font-size: 20px;
    font-weight: 600;
}
QLabel#WelcomeSubtitle {
    color: $text_muted;
    font-size: ${fs_md}px;
}
QLabel#WelcomeSection {
    color: $text_muted;
    font-size: ${fs_xs}px;
    font-weight: 600;
}
QPushButton#RecentFileButton {
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    border-radius: ${r_md}px;
    padding: 6px ${sp_sm}px;
    color: $text;
}
QPushButton#RecentFileButton:hover {
    background: $hover;
}
QPushButton#RecentFileButton:focus {
    border-color: $accent;
}

/* ---- Status bar ---- */
QStatusBar QLabel#StatusMeasure {
    font-family: $mono_stack;
}

/* ---- Document tabs: room for the close button ---- */
QTabWidget#DocumentTabs > QTabBar::tab {
    padding-right: 6px;
}
"""
)


def build_chrome_stylesheet(mode: str | None = None) -> str:
    """Stylesheet for the MainWindow's own widgets, generated from ``theme.tokens(mode)``."""
    values: dict[str, object] = dict(theme.tokens(mode))
    values.update({f"sp_{k}": v for k, v in theme.SPACING.items()})
    values.update({f"r_{k}": v for k, v in theme.RADIUS.items()})
    values.update({f"fs_{k}": v for k, v in theme.FONT_SIZE.items()})
    values["mono_stack"] = theme.MONO_FONT_STACK
    return _TEMPLATE.substitute(values)
