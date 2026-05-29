"""PDF page rendering item."""

from __future__ import annotations

from collections import OrderedDict
from typing import Optional

import fitz
from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsPixmapItem


class PageItem(QGraphicsPixmapItem):
    """A single PDF page rendered at optimized quality."""

    BASE_RENDER_SCALE = 2.0
    TARGET_RENDER_SCALE = 3.0
    MAX_RENDER_PIXELS = 16_000_000
    CACHE_LIMIT = 96
    _PIXMAP_CACHE: "OrderedDict[tuple, QPixmap]" = OrderedDict()

    def __init__(self, page: fitz.Page, scale: float, page_index: int, lazy: bool = True):
        super().__init__()
        self.page_index = page_index
        self.page_rect = QRectF(0, 0, page.rect.width, page.rect.height)
        self._fitz_page = page
        self.render_zoom: float = 0.0  # 0 means "not yet rendered"
        self.render_scale_factor: float = self.BASE_RENDER_SCALE
        self.rotation_degrees: int = 0
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._shadow: Optional[QGraphicsDropShadowEffect] = None
        if lazy:
            # Defer the drop-shadow until first real render — Qt would otherwise
            # allocate an offscreen buffer per page even for placeholders.
            self._set_placeholder(scale)
        else:
            self._ensure_shadow()
            self._render(page, scale)

    def _ensure_shadow(self) -> None:
        if self._shadow is not None:
            return
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24.0)
        shadow.setOffset(0.0, 4.0)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(shadow)
        self._shadow = shadow

    def _set_placeholder(self, scale: float) -> None:
        """Cheap aspect-correct placeholder so opening a long PDF doesn't render every page."""
        pw_pt = max(1.0, float(self.page_rect.width()))
        ph_pt = max(1.0, float(self.page_rect.height()))
        long_side = max(pw_pt, ph_pt)
        target = 64.0  # placeholder pixmap long edge in pixels
        sf = target / long_side
        pix_w = max(2, int(round(pw_pt * sf)))
        pix_h = max(2, int(round(ph_pt * sf)))
        pixmap = QPixmap(pix_w, pix_h)
        pixmap.fill(QColor("#ffffff"))
        self.setPixmap(pixmap)
        # Pick render_zoom/render_scale_factor so _layout_pages math draws this
        # at page_rect.width() * current_zoom pixels on screen.
        self.render_zoom = sf
        self.render_scale_factor = 1.0
        self.setScale(scale / sf)

    @classmethod
    def _effective_render_scale(cls, page: fitz.Page, scale: float) -> float:
        page_rect = getattr(page, "rect", None)
        width = float(getattr(page_rect, "width", 0.0) or 0.0)
        height = float(getattr(page_rect, "height", 0.0) or 0.0)
        scaled_area = max(1.0, width * height * max(scale, 0.25) * max(scale, 0.25))
        max_scale = (cls.MAX_RENDER_PIXELS / scaled_area) ** 0.5
        return max(cls.BASE_RENDER_SCALE, min(cls.TARGET_RENDER_SCALE, max_scale))

    @classmethod
    def _cache_key(cls, page: fitz.Page, scale: float, render_scale: float, rotation: int = 0) -> tuple:
        doc = getattr(page, "parent", None)
        doc_name = getattr(doc, "name", "") or f"doc-{id(doc)}"
        doc_identity = id(doc)
        page_num = getattr(page, "number", -1)
        return (doc_name, doc_identity, page_num, round(scale, 2), round(render_scale, 2), int(rotation) % 360)

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
        self._ensure_shadow()
        self.render_zoom = scale
        render_factor = self._effective_render_scale(page, scale)
        self.render_scale_factor = render_factor
        key = self._cache_key(page, scale, render_factor, self.rotation_degrees)
        cached = self._cache_get(key)
        if cached is not None:
            self.setPixmap(cached)
            self.setScale(1.0 / render_factor)
            return

        render_scale = scale * render_factor
        mat = fitz.Matrix(render_scale, render_scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(img.copy())
        self.setPixmap(pixmap)
        self.setScale(1.0 / render_factor)
        self._cache_put(key, pixmap)

    def rerender(self, scale: float) -> bool:
        # Placeholder pages have render_zoom set to the placeholder scale
        # factor (much less than the real zoom) — the abs() check below
        # naturally treats them as "needs render".
        if self.render_zoom > 0 and abs(scale - self.render_zoom) < 0.01:
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
                                        "bbox": bbox,
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
