"""PDF page rendering item."""

from __future__ import annotations

from collections import OrderedDict
from typing import Optional

import fitz
from PySide6.QtCore import QRectF, QPointF
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsPixmapItem


class PageItem(QGraphicsPixmapItem):
    """A single PDF page rendered at optimized quality."""

    RENDER_SCALE = 2.0
    CACHE_LIMIT = 96
    _PIXMAP_CACHE: "OrderedDict[tuple, QPixmap]" = OrderedDict()

    def __init__(self, page: fitz.Page, scale: float, page_index: int):
        super().__init__()
        self.page_index = page_index
        self.page_rect = QRectF(0, 0, page.rect.width, page.rect.height)
        self._fitz_page = page
        self.render_zoom: float = scale
        self._shadow = QGraphicsDropShadowEffect()
        self._shadow.setBlurRadius(24.0)
        self._shadow.setOffset(0.0, 4.0)
        self._shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(self._shadow)
        self._render(page, scale)

    @classmethod
    def _cache_key(cls, page: fitz.Page, scale: float) -> tuple:
        doc = getattr(page, "parent", None)
        doc_name = getattr(doc, "name", "") or f"doc-{id(doc)}"
        page_num = getattr(page, "number", -1)
        return (doc_name, page_num, round(scale, 2), cls.RENDER_SCALE)

    @classmethod
    def _cache_get(cls, key: tuple) -> Optional[QPixmap]:
        pixmap = cls._PIXMAP_CACHE.get(key)
        if pixmap is None:
            return None
        cls._PIXMAP_CACHE.move_to_end(key)
        return pixmap

    @classmethod
    def _cache_put(cls, key: tuple, pixmap: QPixmap):
        cls._PIXMAP_CACHE[key] = pixmap
        cls._PIXMAP_CACHE.move_to_end(key)
        while len(cls._PIXMAP_CACHE) > cls.CACHE_LIMIT:
            cls._PIXMAP_CACHE.popitem(last=False)

    def _render(self, page: fitz.Page, scale: float):
        self.render_zoom = scale
        key = self._cache_key(page, scale)
        cached = self._cache_get(key)
        if cached is not None:
            self.setPixmap(cached)
            self.setScale(1.0 / self.RENDER_SCALE)
            return

        render_scale = scale * self.RENDER_SCALE
        mat = fitz.Matrix(render_scale, render_scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(img.copy())
        self.setPixmap(pixmap)
        self.setScale(1.0 / self.RENDER_SCALE)
        self._cache_put(key, pixmap)

    def rerender(self, scale: float) -> bool:
        if abs(scale - self.render_zoom) < 0.01:
            return False
        self._render(self._fitz_page, scale)
        return True

    def get_text_info_at(self, page_point: QPointF) -> Optional[dict]:
        """Get font info for text at the given page coordinate."""
        try:
            blocks = self._fitz_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            candidates = []
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        bbox = span.get("bbox", (0, 0, 0, 0))
                        rect = QRectF(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1])
                        if rect.contains(page_point):
                            area = max(1.0, rect.width() * rect.height())
                            center_dx = page_point.x() - rect.center().x()
                            center_dy = page_point.y() - rect.center().y()
                            center_dist = center_dx * center_dx + center_dy * center_dy

                            font_name = span.get("font", "Unknown")
                            style_bits = []
                            lower_font = font_name.lower()
                            if "bold" in lower_font:
                                style_bits.append("Bold")
                            if "italic" in lower_font or "oblique" in lower_font:
                                style_bits.append("Italic")
                            style = " + ".join(style_bits) if style_bits else "Regular"

                            candidates.append(
                                (
                                    area,
                                    center_dist,
                                    {
                                        "font": font_name,
                                        "size": span.get("size", 0),
                                        "color": span.get("color", 0),
                                        "text": span.get("text", "")[:50],
                                        "style": style,
                                    },
                                )
                            )
            if candidates:
                candidates.sort(key=lambda item: (item[0], item[1]))
                return candidates[0][2]
        except Exception:
            pass
        return None
