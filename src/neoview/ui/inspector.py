"""Right-hand Inspector panel: measurement, text/font and document information.

One scrollable column of collapsible sections, so nothing hides behind tabs. MainWindow
fills the value labels; this module only builds them.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from neoview.ui.chrome import IconBinder
from neoview.utils.units import UNIT_LABELS, UNITS


class CollapsibleSection(QWidget):
    """Simple expandable/collapsible content section."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QToolButton(self)
        self._header.setText(title)
        self._header.setObjectName("InspectorSectionHeader")
        self._header.setCheckable(True)
        self._header.setChecked(True)
        self._header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._header.setArrowType(Qt.ArrowType.DownArrow)
        self._header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._header.clicked.connect(self._on_toggled)

        self._content = QWidget()
        self._content.setObjectName("InspectorSectionContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 2, 0, 6)
        self._content_layout.setSpacing(6)

        root.addWidget(self._header)
        root.addWidget(self._content)

    @property
    def header(self) -> QToolButton:
        return self._header

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def is_expanded(self) -> bool:
        return self._header.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self._header.setChecked(expanded)
        self._on_toggled(expanded)

    def _on_toggled(self, expanded: bool):
        self._header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._content.setVisible(expanded)


class PanelTitleBar(QWidget):
    """Dock title bar: bold title on the left, a close button on the right."""

    close_requested = Signal()

    def __init__(self, title: str, binder: IconBinder, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PanelTitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 6, 6)
        layout.setSpacing(6)
        self.title = QLabel(title, self)
        self.title.setObjectName("PanelTitle")
        self.extra = QHBoxLayout()
        self.extra.setContentsMargins(0, 0, 0, 0)
        self.extra.setSpacing(4)
        self.close_button = QToolButton(self)
        self.close_button.setAutoRaise(True)
        self.close_button.setIconSize(QSize(14, 14))
        self.close_button.setToolTip(f"Close {title.lower()}")
        self.close_button.setAccessibleName(f"Close {title.lower()}")
        binder.bind(self.close_button, "x")
        self.close_button.clicked.connect(self.close_requested.emit)
        layout.addWidget(self.title)
        layout.addStretch(1)
        layout.addLayout(self.extra)
        layout.addWidget(self.close_button)


def _value_label(text: str = "--", mono: bool = False) -> QLabel:
    label = QLabel(text)
    label.setObjectName("MonoValue" if mono else "InfoValue")
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(not mono)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


class _Rows:
    """Two-column key/value grid inside a section."""

    def __init__(self, section: CollapsibleSection):
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(6)
        self.grid.setColumnStretch(1, 1)
        section.content_layout.addLayout(self.grid)

    def add(self, key: str, value: str = "--", mono: bool = False) -> QLabel:
        row = self.grid.rowCount()
        key_label = QLabel(key)
        key_label.setObjectName("InfoLabel")
        key_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        val = _value_label(value, mono)
        self.grid.addWidget(key_label, row, 0)
        self.grid.addWidget(val, row, 1)
        return val


class InspectorPanel(QWidget):
    """Measurement, Text and Document sections in one scroll area."""

    def __init__(self, binder: IconBinder, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("InspectorPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = PanelTitleBar("Inspector", binder, self)

        scroll = QScrollArea(self)
        scroll.setObjectName("InspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("InspectorBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 4, 14, 14)
        body_layout.setSpacing(4)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        # -- Measurement --------------------------------------------------------
        self.measure_section = CollapsibleSection("MEASUREMENT")
        measure_rows = _Rows(self.measure_section)
        self.measure_w = measure_rows.add("Width", mono=True)
        self.measure_h = measure_rows.add("Height", mono=True)
        self.measure_x = measure_rows.add("X", mono=True)
        self.measure_y = measure_rows.add("Y", mono=True)

        unit_row = QHBoxLayout()
        unit_row.setContentsMargins(0, 4, 0, 0)
        unit_row.setSpacing(6)
        unit_label = QLabel("Units")
        unit_label.setObjectName("InfoLabel")
        self.units_combo = QComboBox()
        for unit in UNITS:
            self.units_combo.addItem(unit, unit)
            self.units_combo.setItemData(self.units_combo.count() - 1, UNIT_LABELS[unit], Qt.ItemDataRole.ToolTipRole)
        self.units_combo.setToolTip("Measurement units (Tools > Units)")
        self.copy_button = QPushButton("Copy")
        self.copy_button.setProperty("secondary", True)
        self.copy_button.setToolTip("Copy measurements (Ctrl+C)")
        unit_row.addWidget(unit_label)
        unit_row.addWidget(self.units_combo)
        unit_row.addStretch(1)
        unit_row.addWidget(self.copy_button)
        self.measure_section.content_layout.addLayout(unit_row)

        self.measure_hint = QLabel("Drag on the page with the Measure tool (3) to measure an area.")
        self.measure_hint.setObjectName("InfoLabel")
        self.measure_hint.setWordWrap(True)
        self.measure_section.content_layout.addWidget(self.measure_hint)

        # -- Text ---------------------------------------------------------------
        self.text_section = CollapsibleSection("TEXT")
        text_hint = QLabel("Hover over text with the Select tool (1) to inspect its font.")
        text_hint.setObjectName("InfoLabel")
        text_hint.setWordWrap(True)
        self.text_section.content_layout.addWidget(text_hint)
        text_rows = _Rows(self.text_section)
        self.font_name = text_rows.add("Font")
        self.font_size = text_rows.add("Size")
        self.font_style = text_rows.add("Style")

        # -- Document -----------------------------------------------------------
        self.document_section = CollapsibleSection("DOCUMENT")
        doc_rows = _Rows(self.document_section)
        self.doc_name = doc_rows.add("File", "No file")
        self.doc_page = doc_rows.add("Page", "0 / 0")
        self.doc_zoom = doc_rows.add("Zoom", "--")
        self.doc_title = doc_rows.add("Title")
        self.doc_author = doc_rows.add("Author")
        self.doc_subject = doc_rows.add("Subject")
        self.doc_keywords = doc_rows.add("Keywords")
        self.doc_creator = doc_rows.add("Created by")
        self.doc_engine = doc_rows.add("Produced by")
        self.doc_format = doc_rows.add("Format")
        self.doc_created = doc_rows.add("Created")
        self.doc_modified = doc_rows.add("Modified")
        self.doc_encryption = doc_rows.add("Encryption")
        self.doc_file_size = doc_rows.add("File size")

        self.reload_toggle = QCheckBox("Auto-reload on change")
        self.reload_toggle.setToolTip("Reload the document automatically when the file changes on disk")
        self.reload_toggle.setChecked(True)
        self.document_section.content_layout.addSpacing(4)
        self.document_section.content_layout.addWidget(self.reload_toggle)

        body_layout.addWidget(self.measure_section)
        body_layout.addWidget(self.text_section)
        body_layout.addWidget(self.document_section)
        body_layout.addStretch(1)

    def sizeHint(self) -> QSize:
        return QSize(280, 600)
