"""UI dialogs."""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QLineEdit


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
