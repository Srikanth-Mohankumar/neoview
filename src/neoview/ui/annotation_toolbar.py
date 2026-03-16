"""Annotation toolbar widget — type selector, color picker, opacity/width controls."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QColorDialog,
    QDoubleSpinBox,
    QLabel,
    QSizePolicy,
    QSlider,
    QToolBar,
    QToolButton,
    QWidget,
)


# (type_key, label, tooltip)
_ANNOTATION_TOOLS = [
    ("highlight",      "H",  "Highlight (drag to mark text)"),
    ("underline",      "U",  "Underline"),
    ("strikethrough",  "S",  "Strikethrough"),
    ("note",           "N",  "Sticky note"),
    ("text-box",       "T",  "Text box"),
    ("rectangle",      "[]", "Rectangle shape"),
    ("ellipse",        "O",  "Ellipse/circle shape"),
    ("line",           "/",  "Line"),
    ("arrow",          "->", "Arrow"),
    ("freehand",       "~",  "Freehand / ink"),
]


def _color_icon(color: str, size: int = 16) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(QColor(0, 0, 0, 80))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 3, 3)
    painter.end()
    return QIcon(pix)


class AnnotationToolbar(QToolBar):
    """A toolbar for annotation tool selection and property controls.

    Signals
    -------
    type_changed(str)     -- annotation type key selected
    color_changed(str)    -- hex color string
    opacity_changed(float)
    border_width_changed(float)
    """

    type_changed = Signal(str)
    color_changed = Signal(str)
    opacity_changed = Signal(float)
    border_width_changed = Signal(float)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__("Annotations", parent)
        self.setObjectName("AnnotationToolbar")
        self.setMovable(False)

        self._current_type = "highlight"
        self._current_color = "#f7c948"
        self._type_buttons: dict[str, QToolButton] = {}

        self._build()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_type(self) -> str:
        return self._current_type

    def set_color(self, hex_color: str):
        self._current_color = hex_color
        self._color_btn.setIcon(_color_icon(hex_color))

    def set_type(self, type_key: str):
        self._current_type = type_key
        for k, btn in self._type_buttons.items():
            btn.setChecked(k == type_key)

    # ------------------------------------------------------------------
    # Internal build
    # ------------------------------------------------------------------

    def _build(self):
        self.setIconSize(QSize(18, 18))

        # ---- annotation type buttons ----
        for type_key, label, tip in _ANNOTATION_TOOLS:
            btn = QToolButton(self)
            btn.setText(label)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            btn.setChecked(type_key == self._current_type)
            btn.setMinimumSize(30, 28)
            btn.clicked.connect(lambda checked, k=type_key: self._on_type_clicked(k))
            self.addWidget(btn)
            self._type_buttons[type_key] = btn

        self.addSeparator()

        # ---- color button ----
        self._color_btn = QToolButton(self)
        self._color_btn.setIcon(_color_icon(self._current_color, 14))
        self._color_btn.setToolTip("Annotation color")
        self._color_btn.setMinimumSize(30, 28)
        self._color_btn.clicked.connect(self._on_color_clicked)
        self.addWidget(self._color_btn)

        self.addSeparator()

        # ---- opacity ----
        opacity_lbl = QLabel("Opacity")
        opacity_lbl.setStyleSheet("font-size: 11px; color: #888; padding: 0 2px;")
        self.addWidget(opacity_lbl)
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(5, 100)
        self._opacity_slider.setValue(30)
        self._opacity_slider.setFixedWidth(90)
        self._opacity_slider.setToolTip("Annotation opacity")
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.addWidget(self._opacity_slider)
        self._opacity_label = QLabel("30%")
        self._opacity_label.setFixedWidth(36)
        self._opacity_label.setStyleSheet("font-size: 11px;")
        self.addWidget(self._opacity_label)

        self.addSeparator()

        # ---- stroke width (for shapes, freehand, line, arrow) ----
        width_lbl = QLabel("Stroke")
        width_lbl.setStyleSheet("font-size: 11px; color: #888; padding: 0 2px;")
        self.addWidget(width_lbl)
        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(0.5, 20.0)
        self._width_spin.setSingleStep(0.5)
        self._width_spin.setValue(2.0)
        self._width_spin.setDecimals(1)
        self._width_spin.setFixedWidth(62)
        self._width_spin.setToolTip("Stroke / border width (pt)")
        self._width_spin.valueChanged.connect(self._on_width_changed)
        self.addWidget(self._width_spin)

        # push everything to the left
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.addWidget(spacer)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_type_clicked(self, type_key: str):
        self._current_type = type_key
        for k, btn in self._type_buttons.items():
            btn.setChecked(k == type_key)
        self.type_changed.emit(type_key)

    def _on_color_clicked(self):
        color = QColorDialog.getColor(QColor(self._current_color), self, "Annotation Color")
        if color.isValid():
            self._current_color = color.name()
            self._color_btn.setIcon(_color_icon(self._current_color))
            self.color_changed.emit(self._current_color)

    def _on_opacity_changed(self, value: int):
        self._opacity_label.setText(f"{value}%")
        self.opacity_changed.emit(value / 100.0)

    def _on_width_changed(self, value: float):
        self.border_width_changed.emit(value)
