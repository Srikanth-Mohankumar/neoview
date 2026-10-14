"""Left sidebar: a row of icon tabs over stacked panels (thumbnails, outline, bookmarks, ...).

The sidebar only switches panels; MainWindow builds each panel's content and fills it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from neoview.ui.chrome import IconBinder


@dataclass
class _Page:
    key: str
    title: str
    button: QToolButton
    widget: QWidget
    actions: QWidget | None


class Sidebar(QWidget):
    """Icon tab row + title line + stacked pages. Emits ``current_changed(key)``."""

    current_changed = Signal(str)

    def __init__(self, binder: IconBinder, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._binder = binder
        self._pages: dict[str, _Page] = {}
        self._order: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("SidebarHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(6)

        self._tab_row = QHBoxLayout()
        self._tab_row.setContentsMargins(0, 0, 0, 0)
        self._tab_row.setSpacing(2)
        self._tab_row.addStretch(1)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(2, 0, 0, 0)
        title_row.setSpacing(4)
        self._title = QLabel("", header)
        self._title.setObjectName("PanelTitle")
        self._actions_stack = QStackedWidget(header)
        title_row.addWidget(self._title, 1)
        title_row.addWidget(self._actions_stack, 0, Qt.AlignmentFlag.AlignRight)

        header_layout.addLayout(self._tab_row)
        header_layout.addLayout(title_row)

        self._stack = QStackedWidget(self)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        root.addWidget(header)
        root.addWidget(self._stack, 1)

    # -- building ------------------------------------------------------------------
    def add_page(
        self,
        key: str,
        icon_name: str,
        title: str,
        widget: QWidget,
        tooltip: str = "",
        actions: QWidget | None = None,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("SidebarTab")
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip or title)
        button.setAccessibleName(title)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._binder.bind(button, icon_name)
        button.clicked.connect(lambda _checked=False, k=key: self.set_current(k))
        self._group.addButton(button)
        self._tab_row.insertWidget(self._tab_row.count() - 1, button)

        holder = actions if actions is not None else QWidget(self)
        self._actions_stack.addWidget(holder)
        self._stack.addWidget(widget)
        self._pages[key] = _Page(key, title, button, widget, holder)
        self._order.append(key)
        if len(self._order) == 1:
            self.set_current(key)
        return button

    # -- state ---------------------------------------------------------------------
    def keys(self) -> list[str]:
        return list(self._order)

    def current_key(self) -> str:
        widget = self._stack.currentWidget()
        for page in self._pages.values():
            if page.widget is widget:
                return page.key
        return ""

    def page(self, key: str) -> QWidget:
        return self._pages[key].widget

    def tab_button(self, key: str) -> QToolButton:
        return self._pages[key].button

    def set_current(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        changed = self._stack.currentWidget() is not page.widget
        page.button.setChecked(True)
        self._title.setText(page.title)
        self._actions_stack.setCurrentWidget(page.actions)
        self._stack.setCurrentWidget(page.widget)
        if changed:
            self.current_changed.emit(key)

    def sizeHint(self) -> QSize:
        return QSize(240, 600)
