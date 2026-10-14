"""Full-screen presentation mode: one page at a time, fitted to the screen.

The window opens its own ``fitz.Document`` (documents are not shared between widgets or
threads), renders the current page at the widget's device-pixel size, and pre-renders the
next page after each change so advancing is instant.

Keys: Right/Down/Space/PageDown/Enter or left click = next page; Left/Up/Backspace/PageUp
or right click = previous; Home/End = first/last; B or . = toggle black screen;
Esc = close. The mouse wheel also pages.

Usage from MainWindow::

    win = PresentationWindow(view.doc_path(), view.current_page(), password)
    win.closed.connect(lambda page: view.go_to_page(page))
    win.present()

The window does not delete itself on close; the owner keeps a reference while it is open
and calls ``deleteLater()`` from its ``closed`` handler.
"""

from __future__ import annotations

from collections import OrderedDict

import fitz
from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from neoview.ui.password import open_document

_NEXT_KEYS = frozenset(
    {
        Qt.Key.Key_Right,
        Qt.Key.Key_Down,
        Qt.Key.Key_Space,
        Qt.Key.Key_PageDown,
        Qt.Key.Key_Return,
        Qt.Key.Key_Enter,
        Qt.Key.Key_N,
    }
)
_PREVIOUS_KEYS = frozenset(
    {
        Qt.Key.Key_Left,
        Qt.Key.Key_Up,
        Qt.Key.Key_Backspace,
        Qt.Key.Key_PageUp,
        Qt.Key.Key_P,
    }
)
_BLACK_KEYS = frozenset({Qt.Key.Key_B, Qt.Key.Key_Period})

_CACHE_LIMIT = 3


class PresentationWindow(QWidget):
    page_changed = Signal(int)
    closed = Signal(int)  # zero-based page shown when the window closed

    def __init__(
        self,
        path: str,
        start_page: int = 0,
        password: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent, Qt.WindowType.Window)
        self._doc: fitz.Document | None = open_document(path, password)
        if self._doc.page_count == 0:
            self._doc.close()
            self._doc = None
            raise ValueError("PDF has no pages")
        self._path = path
        self._page = min(max(int(start_page), 0), self._doc.page_count - 1)
        self._black = False
        self._closed_emitted = False
        self._cache: OrderedDict[tuple[int, int, int], QImage] = OrderedDict()

        self.setWindowTitle("Presentation")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(False)
        self.setCursor(Qt.CursorShape.BlankCursor)

        self._preload_timer = QTimer(self)
        self._preload_timer.setSingleShot(True)
        self._preload_timer.setInterval(0)
        self._preload_timer.timeout.connect(self._preload_next)

    # -- public API ------------------------------------------------------------------

    def present(self) -> None:
        """Show full screen and take keyboard focus."""
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def current_page(self) -> int:
        return self._page

    def page_count(self) -> int:
        return self._doc.page_count if self._doc is not None else 0

    def is_black(self) -> bool:
        return self._black

    def set_black(self, black: bool) -> None:
        if black != self._black:
            self._black = black
            self.update()

    def toggle_black(self) -> None:
        self.set_black(not self._black)

    def go_to_page(self, index: int) -> None:
        if self._doc is None:
            return
        index = min(max(int(index), 0), self._doc.page_count - 1)
        self._black = False
        if index == self._page:
            self.update()
            return
        self._page = index
        self.update()
        self._preload_timer.start()
        self.page_changed.emit(index)

    def next_page(self) -> None:
        self.go_to_page(self._page + 1)

    def previous_page(self) -> None:
        self.go_to_page(self._page - 1)

    def first_page(self) -> None:
        self.go_to_page(0)

    def last_page(self) -> None:
        self.go_to_page(self.page_count() - 1)

    def cached_pages(self) -> list[int]:
        """Page indices currently rendered for the present size (for tests/diagnostics)."""
        size = self._target_size()
        return [k[0] for k in self._cache if (k[1], k[2]) == (size.width(), size.height())]

    # -- rendering -------------------------------------------------------------------

    def _target_size(self) -> QSize:
        dpr = self.devicePixelRatioF()
        return QSize(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))

    def _render(self, index: int, size: QSize) -> QImage:
        assert self._doc is not None
        page = self._doc[index]
        rect = page.rect
        zoom = min(size.width() / rect.width, size.height() / rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return QImage(
            pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888
        ).copy()

    def page_image(self, index: int) -> QImage | None:
        """Rendered image of ``index`` at the current size, cached."""
        if self._doc is None or not 0 <= index < self._doc.page_count:
            return None
        size = self._target_size()
        key = (index, size.width(), size.height())
        image = self._cache.get(key)
        if image is None:
            image = self._render(index, size)
            self._cache[key] = image
            while len(self._cache) > _CACHE_LIMIT:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(key)
        return image

    def _preload_next(self) -> None:
        if self._doc is not None and self._page + 1 < self._doc.page_count:
            self.page_image(self._page + 1)
            # Keep the current page the most recently used entry.
            self.page_image(self._page)

    # -- events ----------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(0, 0, 0))
            if self._black:
                return
            image = self.page_image(self._page)
            if image is None:
                return
            dpr = self.devicePixelRatioF()
            w = image.width() / dpr
            h = image.height() / dpr
            pos = QPointF((self.width() - w) / 2.0, (self.height() - h) / 2.0)
            image.setDevicePixelRatio(dpr)
            painter.drawImage(pos, image)
        finally:
            painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._cache.clear()
        super().resizeEvent(event)
        self._preload_timer.start()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.close()
        elif key in _NEXT_KEYS:
            self.next_page()
        elif key in _PREVIOUS_KEYS:
            self.previous_page()
        elif key == Qt.Key.Key_Home:
            self.first_page()
        elif key == Qt.Key.Key_End:
            self.last_page()
        elif key in _BLACK_KEYS:
            self.toggle_black()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.next_page()
        elif event.button() == Qt.MouseButton.RightButton:
            self.previous_page()
        else:
            super().mousePressEvent(event)
            return
        event.accept()

    def wheelEvent(self, event: QWheelEvent) -> None:
        dy = event.angleDelta().y()
        if dy < 0:
            self.next_page()
        elif dy > 0:
            self.previous_page()
        event.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._preload_timer.stop()
        self._cache.clear()
        if self._doc is not None:
            self._doc.close()
            self._doc = None
        super().closeEvent(event)
        if not self._closed_emitted:
            self._closed_emitted = True
            self.closed.emit(self._page)
