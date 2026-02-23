"""PDF page rendering item."""

from __future__ import annotations

from typing import Optional

import fitz
from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsPixmapItem


class PageItem(QGraphicsPixmapItem):
    """A single PDF page rendered at optimized quality."""

    RENDER_SCALE = 1.5

    def __init__(self, page: fitz.Page, scale: float, page_index: int):
        super().__init__()
        self.page_index = page_index
        self.page_rect = QRectF(0, 0, page.rect.width, page.rect.height)
        self._fitz_page = page
        self._shadow = QGraphicsDropShadowEffect()
        self._shadow.setBlurRadius(24.0)
        self._shadow.setOffset(0.0, 4.0)
        self._shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(self._shadow)
        self._render(page, scale)

    def _render(self, page: fitz.Page, scale: float):
        render_scale = scale * self.RENDER_SCALE
        mat = fitz.Matrix(render_scale, render_scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(img.copy())
        self.setPixmap(pixmap)
        self.setScale(1.0 / self.RENDER_SCALE)

    def get_text_info_at(self, page_point: QPointF) -> Optional[dict]:
        """Get font info for text at the given page coordinate."""
        try:
            blocks = self._fitz_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        bbox = span.get("bbox", (0, 0, 0, 0))
                        rect = QRectF(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1])
                        if rect.contains(page_point):
                            return {
                                "font": span.get("font", "Unknown"),
                                "size": span.get("size", 0),
                                "color": span.get("color", 0),
                                "text": span.get("text", "")[:50],
                            }
        except Exception:
            pass
        return None
