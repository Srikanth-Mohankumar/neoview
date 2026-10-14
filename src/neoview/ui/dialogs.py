"""UI dialogs."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Selection")
        self.setFixedWidth(280)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        row = QHBoxLayout()
        row.addWidget(QLabel("DPI:"))
        self.dpi = QComboBox()
        self.dpi.addItems(["150", "300", "600"])
        self.dpi.setCurrentIndex(1)
        row.addWidget(self.dpi)
        row.addStretch()
        layout.addLayout(row)

        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        export = QPushButton("Export")
        export.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(export)
        layout.addLayout(btns)

    @property
    def selected_dpi(self) -> int:
        return int(self.dpi.currentText())


class FindDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Find")

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Find:"))
        self.input = QLineEdit()
        row.addWidget(self.input)
        layout.addLayout(row)

        btns = QHBoxLayout()
        self.prev_btn = QPushButton("Previous")
        self.next_btn = QPushButton("Next")
        close_btn = QPushButton("Close")
        close_btn.setProperty("secondary", True)
        btns.addStretch()
        btns.addWidget(self.prev_btn)
        btns.addWidget(self.next_btn)
        btns.addWidget(close_btn)
        layout.addLayout(btns)

        close_btn.clicked.connect(self.close)


class LayoutGridDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Layout Grid")
        self.setFixedWidth(380)
        self.setObjectName("LayoutGridDialog")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._grid_color = QColor(config.get("color", "#d92fd4"))
        self._apply_dialog_style()

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(14, 14, 14, 14)

        panel = QWidget(self)
        panel.setObjectName("LayoutGridPanel")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setSpacing(12)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(panel)

        self.enabled = QCheckBox("Show layout grid")
        self.enabled.setChecked(bool(config.get("enabled", False)))
        panel_layout.addWidget(self.enabled)

        self.corner_marks = QCheckBox("Show corner marks")
        self.corner_marks.setChecked(bool(config.get("corner_marks", False)))
        panel_layout.addWidget(self.corner_marks)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)

        self.width_between = QDoubleSpinBox()
        self.width_between.setRange(8.0, 5000.0)
        self.width_between.setDecimals(1)
        self.width_between.setSuffix(" pt")
        self.width_between.setValue(float(config.get("width", 72.0)))

        self.height_between = QDoubleSpinBox()
        self.height_between.setRange(8.0, 5000.0)
        self.height_between.setDecimals(1)
        self.height_between.setSuffix(" pt")
        self.height_between.setValue(float(config.get("height", 72.0)))

        self.offset_left = QDoubleSpinBox()
        self.offset_left.setRange(0.0, 5000.0)
        self.offset_left.setDecimals(1)
        self.offset_left.setSuffix(" pt")
        self.offset_left.setValue(float(config.get("offset_x", 0.0)))

        self.offset_top = QDoubleSpinBox()
        self.offset_top.setRange(0.0, 5000.0)
        self.offset_top.setDecimals(1)
        self.offset_top.setSuffix(" pt")
        self.offset_top.setValue(float(config.get("offset_y", 0.0)))

        self.subdivisions = QSpinBox()
        self.subdivisions.setRange(0, 8)
        self.subdivisions.setValue(int(config.get("subdivisions", 0)))

        self.corner_length = QDoubleSpinBox()
        self.corner_length.setRange(2.0, 200.0)
        self.corner_length.setDecimals(1)
        self.corner_length.setSuffix(" pt")
        self.corner_length.setValue(float(config.get("corner_length", 12.0)))

        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._choose_color)
        self._sync_color_button()

        form.addWidget(QLabel("Width between lines:"), 0, 0)
        form.addWidget(self.width_between, 0, 1)
        form.addWidget(QLabel("Height between lines:"), 1, 0)
        form.addWidget(self.height_between, 1, 1)
        form.addWidget(QLabel("Grid offset from left:"), 2, 0)
        form.addWidget(self.offset_left, 2, 1)
        form.addWidget(QLabel("Grid offset from top:"), 3, 0)
        form.addWidget(self.offset_top, 3, 1)
        form.addWidget(QLabel("Subdivisions:"), 4, 0)
        form.addWidget(self.subdivisions, 4, 1)
        form.addWidget(QLabel("Corner mark length:"), 5, 0)
        form.addWidget(self.corner_length, 5, 1)
        form.addWidget(QLabel("Grid line color:"), 6, 0)
        form.addWidget(self.color_btn, 6, 1)
        panel_layout.addLayout(form)

        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(apply_btn)
        panel_layout.addLayout(btns)

    def _apply_dialog_style(self):
        app = QApplication.instance()
        theme_mode = ""
        if app is not None:
            theme_mode = str(app.property("theme_mode") or "").lower()
        if theme_mode == "dark":
            self.setStyleSheet(
                """
                QDialog#LayoutGridDialog { background: #1e1e1e; }
                QWidget#LayoutGridPanel { background: #2a2a2a; border: 1px solid #424242; border-radius: 8px; }
                QWidget#LayoutGridPanel QLabel, QWidget#LayoutGridPanel QCheckBox { color: #e2e4e9; background: transparent; }
                """
            )
        else:
            self.setStyleSheet(
                """
                QDialog#LayoutGridDialog { background: #f2f4f7; }
                QWidget#LayoutGridPanel { background: #ffffff; border: 1px solid #d4dae3; border-radius: 8px; }
                QWidget#LayoutGridPanel QLabel, QWidget#LayoutGridPanel QCheckBox { color: #2c3440; background: transparent; }
                """
            )

    def _choose_color(self):
        color = QColorDialog.getColor(self._grid_color, self, "Choose Grid Color")
        if color.isValid():
            self._grid_color = color
            self._sync_color_button()

    def _sync_color_button(self):
        self.color_btn.setText(self._grid_color.name().upper())
        self.color_btn.setStyleSheet(
            f"background:{self._grid_color.name()}; color:#ffffff; border:1px solid #666; padding:4px 8px;"
        )

    @property
    def grid_config(self) -> dict:
        return {
            "enabled": self.enabled.isChecked(),
            "corner_marks": self.corner_marks.isChecked(),
            "width": float(self.width_between.value()),
            "height": float(self.height_between.value()),
            "offset_x": float(self.offset_left.value()),
            "offset_y": float(self.offset_top.value()),
            "subdivisions": int(self.subdivisions.value()),
            "corner_length": float(self.corner_length.value()),
            "color": self._grid_color.name(),
        }


class AnnotationPropertiesDialog(QDialog):
    """Edit colour, opacity, text and stroke width of one annotation record.

    The dialog never mutates the record itself; call ``apply_to(record)`` after it was
    accepted.
    """

    _TEXT_TYPES = ("note", "text-box")
    _STROKE_TYPES = ("rectangle", "ellipse", "line", "arrow", "freehand", "text-box")

    def __init__(self, ann, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Annotation Properties ({ann.type})")
        self.setMinimumWidth(380)
        form = QFormLayout(self)

        # Text / contents (for types that support it)
        self.text_edit: QTextEdit | None = None
        if ann.type in self._TEXT_TYPES:
            self.text_edit = QTextEdit()
            self.text_edit.setPlainText(ann.contents)
            self.text_edit.setFixedHeight(90)
            form.addRow("Text:", self.text_edit)

        # Color
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(60, 24)
        self._color = QColor(ann.color or "#f7c948")
        self._update_color_btn()
        self.color_btn.clicked.connect(self._pick_color)
        form.addRow("Color:", self.color_btn)

        # Opacity
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(5, 100)
        self.opacity_slider.setValue(int(ann.opacity * 100))
        opacity_label = QLabel(f"{int(ann.opacity * 100)}%")
        self.opacity_slider.valueChanged.connect(lambda v: opacity_label.setText(f"{v}%"))
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity_slider)
        opacity_row.addWidget(opacity_label)
        opacity_container = QWidget()
        opacity_container.setLayout(opacity_row)
        form.addRow("Opacity:", opacity_container)

        # Border width (for shapes, freehand, line, arrow)
        self.width_spin: QDoubleSpinBox | None = None
        if ann.type in self._STROKE_TYPES:
            self.width_spin = QDoubleSpinBox()
            self.width_spin.setRange(0.5, 20.0)
            self.width_spin.setSingleStep(0.5)
            self.width_spin.setDecimals(1)
            self.width_spin.setValue(ann.border_width)
            form.addRow("Stroke width:", self.width_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _update_color_btn(self):
        pix = QPixmap(40, 16)
        pix.fill(self._color)
        self.color_btn.setIcon(QIcon(pix))
        self.color_btn.setText(self._color.name())

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, "Annotation Color")
        if c.isValid():
            self._color = c
            self._update_color_btn()

    def apply_to(self, ann) -> None:
        ann.color = self._color.name()
        ann.opacity = self.opacity_slider.value() / 100.0
        if self.text_edit is not None:
            ann.contents = self.text_edit.toPlainText()
        if self.width_spin is not None:
            ann.border_width = self.width_spin.value()
        ann.updated_at = ""
