"""Custom QGraphicsItem for PDF annotations with selection handles."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from neoview.models.view_state import AnnotationRecord

HANDLE_SIZE = 8.0  # pixels (cosmetic, unscaled)
_HANDLE_HALF = HANDLE_SIZE / 2.0

# Bit flags returned by hit_test()
HIT_NONE = 0
HIT_BODY = 1
HIT_TL = 2
HIT_TR = 3
HIT_BL = 4
HIT_BR = 5


class AnnotationItem(QGraphicsItem):
    """Renders a single AnnotationRecord on the scene.

    The item lives in *page-local* coordinates (same as SelectionRect).
    Parent is the PageItem, so pos() is relative to the page origin.
    Scale is set by the caller to match the current zoom level.
    """

    def __init__(self, record: AnnotationRecord, parent=None):
        super().__init__(parent)
        self._record = record
        self._selected = False
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, False)
        self.setAcceptHoverEvents(True)
        self.setZValue(880)
        self.setData(0, record.id)
        self.setData(1, record.type)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def record(self) -> AnnotationRecord:
        return self._record

    @property
    def annotation_id(self) -> str:
        return self._record.id

    def set_selected_highlight(self, selected: bool):
        self._selected = selected
        self.update()

    # ------------------------------------------------------------------
    # QGraphicsItem interface
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        x, y, w, h = self._record.rect
        r = QRectF(float(x), float(y), max(1.0, float(w)), max(1.0, float(h)))
        return r.adjusted(-2, -2, 2, 2)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None):
        ann = self._record
        x, y, w, h = ann.rect
        base_rect = QRectF(float(x), float(y), max(0.0, float(w)), max(0.0, float(h)))

        color = QColor(ann.color or "#f7c948")
        opacity = max(0.0, min(1.0, ann.opacity))
        border_color = QColor(ann.border_color) if ann.border_color else color
        bw = max(0.5, float(ann.border_width))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        t = ann.type

        if t == "highlight":
            self._paint_highlight(painter, base_rect, color, opacity)
        elif t == "underline":
            self._paint_underline(painter, base_rect, color)
        elif t == "strikethrough":
            self._paint_strikethrough(painter, base_rect, color)
        elif t == "note":
            self._paint_note(painter, base_rect, color, opacity)
        elif t == "text-box":
            self._paint_textbox(painter, base_rect, color, border_color, bw, opacity, ann.contents, ann.font_size)
        elif t == "rectangle":
            self._paint_rectangle(painter, base_rect, color, border_color, bw, opacity)
        elif t == "ellipse":
            self._paint_ellipse(painter, base_rect, color, border_color, bw, opacity)
        elif t == "freehand":
            self._paint_freehand(painter, ann.points, color, bw, opacity)
        elif t == "line":
            self._paint_line(painter, base_rect, color, bw, opacity)
        elif t == "arrow":
            self._paint_arrow(painter, base_rect, color, bw, opacity)

        if self._selected:
            self._paint_selection_overlay(painter, base_rect)

        painter.restore()

    # ------------------------------------------------------------------
    # Individual type painters
    # ------------------------------------------------------------------

    def _paint_highlight(self, p: QPainter, r: QRectF, color: QColor, opacity: float):
        pen = QPen(QColor(color.red(), color.green(), color.blue(), 180))
        pen.setWidthF(0.6)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), int(255 * opacity))))
        p.drawRect(r)

    def _paint_underline(self, p: QPainter, r: QRectF, color: QColor):
        line_h = max(1.5, min(3.5, r.height() * 0.12))
        line_rect = QRectF(r.x(), r.bottom() - line_h, r.width(), line_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 235)))
        p.drawRect(line_rect)

    def _paint_strikethrough(self, p: QPainter, r: QRectF, color: QColor):
        line_h = max(1.5, min(3.0, r.height() * 0.1))
        cy = r.center().y()
        line_rect = QRectF(r.x(), cy - line_h / 2, r.width(), line_h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 235)))
        p.drawRect(line_rect)

    def _paint_note(self, p: QPainter, r: QRectF, color: QColor, opacity: float):
        icon_size = 16.0
        note_rect = QRectF(r.x(), r.y(), icon_size, icon_size)
        pen = QPen(QColor(250, 250, 250, 220))
        pen.setWidthF(0.8)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), int(255 * opacity))))
        p.drawRoundedRect(note_rect, 3, 3)
        # Draw a small "lines" icon inside
        line_pen = QPen(QColor(255, 255, 255, 200))
        line_pen.setWidthF(1.0)
        line_pen.setCosmetic(True)
        p.setPen(line_pen)
        lx = r.x() + 3
        for dy in (4.5, 7.5, 10.5):
            p.drawLine(QPointF(lx, r.y() + dy), QPointF(lx + 10, r.y() + dy))

    def _paint_textbox(
        self,
        p: QPainter,
        r: QRectF,
        color: QColor,
        border_color: QColor,
        bw: float,
        opacity: float,
        text: str,
        font_size: float,
    ):
        # Background fill (very light version of color)
        fill = QColor(color.red(), color.green(), color.blue(), max(10, int(255 * opacity * 0.3)))
        p.setBrush(QBrush(fill))
        pen = QPen(border_color)
        pen.setWidthF(bw)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawRect(r)
        if text:
            text_color = QColor(color.red(), color.green(), color.blue(), min(255, int(255 * opacity * 3)))
            p.setPen(QPen(text_color))
            font = QFont()
            font.setPointSizeF(font_size)
            p.setFont(font)
            p.drawText(r.adjusted(3, 3, -3, -3), Qt.TextFlag.TextWordWrap, text)

    def _paint_rectangle(
        self, p: QPainter, r: QRectF, color: QColor, border_color: QColor, bw: float, opacity: float
    ):
        fill = QColor(color.red(), color.green(), color.blue(), int(255 * opacity))
        p.setBrush(QBrush(fill))
        pen = QPen(border_color)
        pen.setWidthF(bw)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawRect(r)

    def _paint_ellipse(
        self, p: QPainter, r: QRectF, color: QColor, border_color: QColor, bw: float, opacity: float
    ):
        fill = QColor(color.red(), color.green(), color.blue(), int(255 * opacity))
        p.setBrush(QBrush(fill))
        pen = QPen(border_color)
        pen.setWidthF(bw)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawEllipse(r)

    def _paint_freehand(
        self, p: QPainter, points: List[List[float]], color: QColor, bw: float, opacity: float
    ):
        if len(points) < 2:
            return
        path = QPainterPath()
        path.moveTo(QPointF(points[0][0], points[0][1]))
        for pt in points[1:]:
            path.lineTo(QPointF(pt[0], pt[1]))
        pen = QPen(QColor(color.red(), color.green(), color.blue(), int(255 * opacity)))
        pen.setWidthF(bw)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

    def _paint_line(self, p: QPainter, r: QRectF, color: QColor, bw: float, opacity: float):
        pen = QPen(QColor(color.red(), color.green(), color.blue(), int(255 * opacity)))
        pen.setWidthF(bw)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(r.topLeft(), r.bottomRight())

    def _paint_arrow(self, p: QPainter, r: QRectF, color: QColor, bw: float, opacity: float):
        pen_color = QColor(color.red(), color.green(), color.blue(), int(255 * opacity))
        pen = QPen(pen_color)
        pen.setWidthF(bw)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QBrush(pen_color))

        start = r.topLeft()
        end = r.bottomRight()
        p.drawLine(start, end)

        # Arrowhead
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1:
            return
        ux, uy = dx / length, dy / length
        arrow_len = max(8.0, min(20.0, length * 0.25))
        arrow_w = arrow_len * 0.5
        # Perpendicular
        px, py = -uy, ux
        tip = end
        base1 = QPointF(end.x() - ux * arrow_len + px * arrow_w, end.y() - uy * arrow_len + py * arrow_w)
        base2 = QPointF(end.x() - ux * arrow_len - px * arrow_w, end.y() - uy * arrow_len - py * arrow_w)
        path = QPainterPath()
        path.moveTo(tip)
        path.lineTo(base1)
        path.lineTo(base2)
        path.closeSubpath()
        p.drawPath(path)

    def _paint_selection_overlay(self, p: QPainter, r: QRectF):
        """Draw a dashed blue selection border around the annotation."""
        sel_pen = QPen(QColor(91, 141, 246, 220))
        sel_pen.setWidthF(1.5)
        sel_pen.setStyle(Qt.PenStyle.DashLine)
        sel_pen.setCosmetic(True)
        p.setPen(sel_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r.adjusted(-1, -1, 1, 1))

    # ------------------------------------------------------------------
    # Hit test (in item local coords)
    # ------------------------------------------------------------------

    def hit_test(self, local_pos: QPointF) -> int:
        """Return HIT_* constant for what was hit at local_pos."""
        x, y, w, h = self._record.rect
        r = QRectF(float(x), float(y), max(1.0, float(w)), max(1.0, float(h)))
        if r.adjusted(-2, -2, 2, 2).contains(local_pos):
            return HIT_BODY
        return HIT_NONE
