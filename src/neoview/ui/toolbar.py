"""Composite widgets for the main toolbar: page field, zoom box, tool segment, search field.

They only build and lay out controls; MainWindow wires the signals to its slots, so the
search, navigation and zoom logic stays in one place.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QAction, QIntValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from neoview.ui.chrome import TOOLBAR_ICON, IconBinder

# Zoom presets offered in the toolbar box, after the two fit modes.
ZOOM_PRESETS = ("50%", "75%", "100%", "125%", "150%", "200%", "300%", "400%")
ZOOM_FIT_WIDTH = "Fit Width"
ZOOM_FIT_PAGE = "Fit Page"


class PageField(QWidget):
    """Editable current page plus a muted " / N" total, e.g. ``[ 3 ] / 12``."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PageField")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(0)

        self.edit = QLineEdit(self)
        self.edit.setObjectName("PageInput")
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.setValidator(QIntValidator(1, 9_999_999, self.edit))
        self.edit.setToolTip("Current page - type a number and press Enter (Ctrl+G)")
        self.edit.setAccessibleName("Page number")
        self.edit.setFixedWidth(48)

        self.total_label = QLabel("/ 0", self)
        self.total_label.setObjectName("PageTotal")

        layout.addWidget(self.edit)
        layout.addWidget(self.total_label)

    def set_pages(self, current: int, total: int) -> None:
        """Show ``current`` (1-based) of ``total``; leaves the text alone while the user edits."""
        self.total_label.setText(f"/ {total}")
        if not self.edit.hasFocus():
            self.edit.setText(str(current) if total else "")
        self.edit.setEnabled(total > 0)


class ZoomBox(QComboBox):
    """Editable zoom percentage with presets and the two fit modes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ZoomCombo")
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.addItems([ZOOM_FIT_WIDTH, ZOOM_FIT_PAGE])
        self.insertSeparator(2)
        self.addItems(list(ZOOM_PRESETS))
        self.setCurrentText("100%")
        self.setMinimumContentsLength(5)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setToolTip("Zoom - pick a preset or type a percentage")
        self.setAccessibleName("Zoom")
        self.view().setMinimumWidth(110)


class ToolSegment(QFrame):
    """A segmented control: one connected row of exclusive, checkable tool buttons."""

    def __init__(self, actions: list[QAction], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ToolSegment")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self.buttons: list[QToolButton] = []
        for action in actions:
            btn = QToolButton(self)
            btn.setDefaultAction(action)
            btn.setIconSize(QSize(TOOLBAR_ICON - 2, TOOLBAR_ICON - 2))
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            btn.setAutoRaise(True)
            btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            layout.addWidget(btn)
            self.buttons.append(btn)


class SearchField(QFrame):
    """Inline find box: [icon][text......][1/3][Aa][^][v][list]."""

    focus_changed = Signal(bool)
    previous_requested = Signal()  # Shift+Enter in the text box

    def __init__(self, binder: IconBinder, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SearchField")
        self.setProperty("focused", False)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(200)
        self.setMaximumWidth(340)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 1, 3, 1)
        layout.setSpacing(1)

        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("SearchIcon")
        binder.bind(self.icon_label, "search", lambda icon: self.icon_label.setPixmap(icon.pixmap(QSize(16, 16))))

        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Find in document")
        self.edit.setAccessibleName("Find in document")
        self.edit.setToolTip("Find in document (Ctrl+F) - Enter: next, Shift+Enter: previous")
        self.edit.installEventFilter(self)

        self.count_label = QLabel("", self)
        self.count_label.setObjectName("SearchCount")

        self.case_button = self._button(binder, "case-sensitive", "Match case", checkable=True)
        self.prev_button = self._button(binder, "chevron-up", "Previous match (Shift+F3)")
        self.next_button = self._button(binder, "chevron-down", "Next match (F3)")
        self.results_button = self._button(binder, "list", "Show all results (Ctrl+Shift+F)", checkable=True)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.count_label)
        layout.addWidget(self.case_button)
        layout.addWidget(self.prev_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.results_button)

    def _button(self, binder: IconBinder, icon_name: str, tip: str, checkable: bool = False) -> QToolButton:
        btn = QToolButton(self)
        binder.bind(btn, icon_name)
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip(tip)
        btn.setAccessibleName(tip)
        btn.setCheckable(checkable)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        return btn

    def eventFilter(self, obj, event):
        if (
            obj is self.edit
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.previous_requested.emit()
            return True
        if obj is self.edit and event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            focused = event.type() == QEvent.Type.FocusIn
            self.setProperty("focused", focused)
            self.style().unpolish(self)
            self.style().polish(self)
            self.focus_changed.emit(focused)
        return super().eventFilter(obj, event)

