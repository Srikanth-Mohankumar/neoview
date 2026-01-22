"""Selection rectangle graphics item."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen, QBrush, QColor
from PySide6.QtWidgets import QGraphicsRectItem


class SelectionRect(QGraphicsRectItem):
    """Measurement rectangle with thin border and resize handles."""

    HANDLE_SIZE = 2
    MIN_SIZE = 2

    def __init__(self, rect: QRectF, page_rect: QRectF, parent=None):
        super().__init__(parent)
        self._page_rect = page_rect
        self._rect = self._clamp(rect.normalized())

        pen = QPen(QColor(0, 0, 0, 200))
        pen.setWidthF(0.5)
        pen.setStyle(Qt.PenStyle.DotLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(QColor(0, 0, 0, 18)))
        self.setZValue(1000)
        self.setAcceptHoverEvents(True)

        self._drag_mode: Optional[str] = None
        self._drag_start: Optional[QPointF] = None
        self._start_rect: Optional[QRectF] = None

        self._sync()

    @property
    def pdf_rect(self) -> QRectF:
        return self._rect

    @pdf_rect.setter
    def pdf_rect(self, r: QRectF):
        self._rect = self._clamp(r.normalized())
        self._sync()

    def _clamp(self, r: QRectF) -> QRectF:
        p = self._page_rect
        x = max(p.left(), min(r.x(), p.right() - self.MIN_SIZE))
        y = max(p.top(), min(r.y(), p.bottom() - self.MIN_SIZE))
        w = max(self.MIN_SIZE, min(r.width(), p.right() - x))
        h = max(self.MIN_SIZE, min(r.height(), p.bottom() - y))
        return QRectF(x, y, w, h)

    def _sync(self):
        self.setRect(self._rect)

    def hit_test(self, pos: QPointF) -> str:
        """Returns 'tl','tr','bl','br','t','b','l','r','move' or ''."""
        r = self._rect
        s = self.HANDLE_SIZE

        def near(a, b):
            return abs(a - b) < s

        on_left = near(pos.x(), r.left())
        on_right = near(pos.x(), r.right())
        on_top = near(pos.y(), r.top())
        on_bottom = near(pos.y(), r.bottom())

        if on_top and on_left:
            return "tl"
        if on_top and on_right:
            return "tr"
        if on_bottom and on_left:
            return "bl"
        if on_bottom and on_right:
            return "br"
        if on_top:
            return "t"
        if on_bottom:
            return "b"
        if on_left:
            return "l"
        if on_right:
            return "r"
        if r.contains(pos):
            return "move"
        return ""

    def start_drag(self, pos: QPointF, mode: str):
        self._drag_mode = mode
        self._drag_start = pos
        self._start_rect = QRectF(self._rect)

    def update_drag(self, pos: QPointF):
        if not self._drag_mode or not self._start_rect:
            return
        d = pos - self._drag_start
        r = QRectF(self._start_rect)
        m = self._drag_mode

        if m == "move":
            r.translate(d)
        else:
            if "l" in m:
                r.setLeft(r.left() + d.x())
            if "r" in m:
                r.setRight(r.right() + d.x())
            if "t" in m:
                r.setTop(r.top() + d.y())
            if "b" in m:
                r.setBottom(r.bottom() + d.y())

        self.pdf_rect = r

    def end_drag(self):
        self._drag_mode = None

    def nudge(self, dx: float, dy: float):
        r = QRectF(self._rect)
        r.translate(dx, dy)
        self.pdf_rect = r

    def resize_by(self, dw: float, dh: float):
        r = QRectF(self._rect)
        r.setWidth(max(self.MIN_SIZE, r.width() + dw))
        r.setHeight(max(self.MIN_SIZE, r.height() + dh))
        self.pdf_rect = r

    def cursor_for_mode(self, mode: str) -> Qt.CursorShape:
        cursors = {
            "tl": Qt.CursorShape.SizeFDiagCursor,
            "br": Qt.CursorShape.SizeFDiagCursor,
            "tr": Qt.CursorShape.SizeBDiagCursor,
            "bl": Qt.CursorShape.SizeBDiagCursor,
            "t": Qt.CursorShape.SizeVerCursor,
            "b": Qt.CursorShape.SizeVerCursor,
            "l": Qt.CursorShape.SizeHorCursor,
            "r": Qt.CursorShape.SizeHorCursor,
            "move": Qt.CursorShape.SizeAllCursor,
        }
        return cursors.get(mode, Qt.CursorShape.ArrowCursor)
