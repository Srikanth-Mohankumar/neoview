"""Empty state shown while no document is open: open button, drop hint, recent files."""

from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from neoview import theme
from neoview.ui import icons
from neoview.ui.chrome import IconBinder

MAX_RECENT = 6


class WelcomePanel(QWidget):
    """Centred card. Emits ``open_requested`` and ``recent_requested(path)``.

    Drops are handled by MainWindow: this widget does not accept drops, so Qt delivers
    them to the window behind it.
    """

    open_requested = Signal()
    recent_requested = Signal(str)

    def __init__(self, binder: IconBinder, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("WelcomePanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._binder = binder

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(2)

        row = QHBoxLayout()
        row.addStretch(1)
        self.card = QFrame(self)
        self.card.setObjectName("WelcomeCard")
        self.card.setFixedWidth(440)
        self.card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(3)

        card = QVBoxLayout(self.card)
        card.setContentsMargins(32, 28, 32, 24)
        card.setSpacing(6)

        # A theme-tinted glyph rather than the app logo: the logo is a raster with a white
        # background that would sit as a bright square in the dark theme.
        logo = QLabel(self.card)
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        binder.bind(
            logo,
            "file-text",
            lambda _icon: logo.setPixmap(
                icons.icon("file-text", theme.tokens()["text_muted"]).pixmap(QSize(44, 44))
            ),
        )

        title = QLabel("Open a PDF to get started", self.card)
        title.setObjectName("WelcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        subtitle = QLabel("Drop a file anywhere in this window, or choose one.", self.card)
        subtitle.setObjectName("WelcomeSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        subtitle.setWordWrap(True)

        self.open_button = QPushButton("Open PDF...", self.card)
        self.open_button.setProperty("primary", True)
        self.open_button.setToolTip("Open a PDF (Ctrl+O)")
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        binder.bind(self.open_button, "folder-open", lambda _icon: self._set_open_icon())
        self.open_button.clicked.connect(self.open_requested.emit)
        open_row = QHBoxLayout()
        open_row.addStretch(1)
        open_row.addWidget(self.open_button)
        open_row.addStretch(1)

        card.addWidget(logo)
        card.addSpacing(6)
        card.addWidget(title)
        card.addWidget(subtitle)
        card.addSpacing(14)
        card.addLayout(open_row)

        self._recent_header = QLabel("RECENT", self.card)
        self._recent_header.setObjectName("WelcomeSection")
        self._recent_box = QVBoxLayout()
        self._recent_box.setContentsMargins(0, 0, 0, 0)
        self._recent_box.setSpacing(0)
        card.addSpacing(18)
        card.addWidget(self._recent_header)
        card.addSpacing(2)
        card.addLayout(self._recent_box)

        self.recent_buttons: list[QPushButton] = []
        self.set_recent_files([])

    def _set_open_icon(self) -> None:
        # The primary button has light text on the accent colour; a dark glyph would vanish.
        self.open_button.setIcon(icons.icon("folder-open", theme.tokens()["accent_text"]))

    def set_recent_files(self, paths: list[str]) -> None:
        shown = [p for p in paths if p][:MAX_RECENT]
        if shown == [btn.toolTip() for btn in self.recent_buttons]:
            return
        for btn in self.recent_buttons:
            self._recent_box.removeWidget(btn)
            btn.hide()  # deleteLater waits for the event loop; do not paint it meanwhile
            btn.deleteLater()
        self.recent_buttons = []

        for path in shown:
            name = os.path.basename(path)
            folder = os.path.dirname(path)
            btn = QPushButton(self.card)
            btn.setObjectName("RecentFileButton")
            btn.setToolTip(path)
            btn.setAccessibleName(f"Open {name}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            row = QHBoxLayout(btn)
            row.setContentsMargins(8, 6, 8, 6)
            row.setSpacing(8)
            glyph = QLabel(btn)
            self._binder.bind(glyph, "file-text", lambda icon, g=glyph: g.setPixmap(icon.pixmap(QSize(16, 16))))
            name_label = QLabel(name, btn)
            folder_label = QLabel(self._shorten(folder), btn)
            folder_label.setObjectName("MutedLabel")
            for child in (glyph, name_label, folder_label):
                child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            row.addWidget(glyph)
            row.addWidget(name_label)
            row.addWidget(folder_label, 1)
            btn.setMinimumHeight(32)
            btn.clicked.connect(lambda _checked=False, p=path: self.recent_requested.emit(p))
            self._recent_box.addWidget(btn)
            self.recent_buttons.append(btn)
        self._recent_header.setVisible(bool(shown))

    @staticmethod
    def _shorten(folder: str, limit: int = 34) -> str:
        home = os.path.expanduser("~")
        if home and folder.startswith(home):
            folder = "~" + folder[len(home):]
        if len(folder) > limit:
            folder = "..." + folder[-(limit - 3):]
        return folder
