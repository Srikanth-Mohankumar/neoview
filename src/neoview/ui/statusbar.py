"""Status bar: file name on the left; measurement, page and zoom read-outs on the right."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QStatusBar, QWidget


class ViewerStatusBar(QStatusBar):
    """Muted, single-line status bar. Transient messages replace the file name while shown."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("ViewerStatusBar")
        self.setSizeGripEnabled(False)

        self.file_label = QLabel("No document")
        self.file_label.setObjectName("StatusFile")
        self.perf_label = QLabel("")
        self.perf_label.setObjectName("StatusPerf")
        self.measure_label = QLabel("")
        self.measure_label.setObjectName("StatusMeasure")
        self.measure_label.setToolTip("Measured area (width x height)")
        self.page_label = QLabel("")
        self.page_label.setObjectName("StatusPage")
        self.zoom_label = QLabel("")
        self.zoom_label.setObjectName("StatusZoom")
        self.zoom_label.setMinimumWidth(44)

        self.addWidget(self.file_label, 1)
        for label in (self.perf_label, self.measure_label, self.page_label, self.zoom_label):
            self.addPermanentWidget(label)

    def set_document(self, name: str | None) -> None:
        self.file_label.setText(name or "No document")

    def set_page(self, current: int, total: int) -> None:
        self.page_label.setText(f"Page {current} of {total}" if total else "")

    def set_zoom(self, percent: float | None) -> None:
        self.zoom_label.setText(f"{percent:.0f}%" if percent is not None else "")

    def set_measurement(self, text: str) -> None:
        self.measure_label.setText(text)
        self.measure_label.setVisible(bool(text))
