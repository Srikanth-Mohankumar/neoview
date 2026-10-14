"""PDF page rendering item."""

from __future__ import annotations

import itertools
import sys
from collections import OrderedDict

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QGraphicsPixmapItem

from neoview.ui.page_modes import apply_color_mode, page_background

_doc_tokens = itertools.count(1)


def new_doc_token() -> int:
    """Return a process-unique token for one loaded document (an open or a reload)."""
    return next(_doc_tokens)


_malloc_trim = None


def release_freed_memory() -> None:
    """Best effort: hand freed heap memory back to the OS after dropping page pixmaps.

    glibc keeps freed multi-megabyte pixmap buffers in the process heap, so RSS stays at its
    peak after a large document is closed although the memory is free (measured: 602 MB ->
    104 MB with malloc_trim after reading 300 image pages). Only glibc has malloc_trim; on
    other platforms this does nothing.
    """
    global _malloc_trim
    if _malloc_trim is None:
        _malloc_trim = False
        if sys.platform.startswith("linux"):
            try:
                import ctypes

                _malloc_trim = ctypes.CDLL("libc.so.6").malloc_trim
            except (OSError, AttributeError):
                _malloc_trim = False
    if _malloc_trim:
        try:
            _malloc_trim(0)
        except Exception:
            pass


class PageItem(QGraphicsPixmapItem):
    """A single PDF page.

    Geometry (``page_rect``, position, scale) is valid from construction; the image is a
    placeholder until ``apply_render`` installs a real render. Whatever pixmap it holds, the
    item covers ``page_rect.size() * zoom`` scene units, because
    ``scale() == (zoom / render_zoom) / render_scale_factor``.
    """

    # Render resolution relative to device pixels (devicePixelRatio is applied separately).
    # 1.0 renders exactly the device pixels the page covers on screen.
    RENDER_HEADROOM = 1.0
    MIN_RENDER_FACTOR = 0.25
    MAX_RENDER_PIXELS = 16_000_000
    # Byte budget of the pixmap cache shared by all views.
    CACHE_BUDGET_BYTES = 256 * 1024 * 1024
    _PIXMAP_CACHE: OrderedDict[tuple, QPixmap] = OrderedDict()

    # Painted drop shadow: (spread, alpha) per layer, in screen pixels. A few translucent
    # strips cost far less than QGraphicsDropShadowEffect, which re-renders the whole page
    # into an offscreen buffer on every paint.
    SHADOW_OFFSET_Y = 3.0
    SHADOW_LAYERS = ((1.0, 34), (3.0, 20), (6.0, 11), (10.0, 5))
    SHADOW_MARGIN = 14.0

    def __init__(
        self,
        page: fitz.Page,
        scale: float,
        page_index: int,
        lazy: bool = True,
        doc_token: int = 0,
        color_mode: str = "normal",
    ):
        super().__init__()
        self.page_index = page_index
        # Reading colour mode renders are made for (page_modes.COLOR_MODES); part of the
        # cache key. rendered_color_mode is the mode of the pixmap currently shown.
        self.color_mode = color_mode
        self.rendered_color_mode = color_mode
        self.page_rect = QRectF(0, 0, page.rect.width, page.rect.height)
        self._fitz_page = page
        self.doc_token = doc_token
        self.render_zoom: float = 0.0  # 0 means "not yet rendered"
        self.render_scale_factor: float = 1.0
        self.rotation_degrees: int = 0
        # True while the pixmap is a stand-in: a blank page or an older render shown scaled.
        self.is_preview = True
        # True while the pixmap is the blank placeholder.
        self.is_blank = True
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        if lazy:
            self._set_placeholder(scale)
        else:
            self._render(page, scale)

    # -- geometry and painting -----------------------------------------------------------

    def setScale(self, scale: float) -> None:  # noqa: N802 - Qt API
        # boundingRect includes a shadow margin measured in screen pixels, so it changes
        # with the item scale.
        self.prepareGeometryChange()
        super().setScale(scale)

    def _pixel_unit(self) -> float:
        s = self.scale()
        return 1.0 / s if s > 0 else 1.0

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        unit = self._pixel_unit()
        m = self.SHADOW_MARGIN * unit
        return QRectF(self.pixmap().rect()).adjusted(-m, -m, m, m + self.SHADOW_OFFSET_Y * unit)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(QRectF(self.pixmap().rect()))
        return path

    def contains(self, point: QPointF) -> bool:
        return QRectF(self.pixmap().rect()).contains(point)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        pm = self.pixmap()
        if not pm.isNull():
            unit = self._pixel_unit()
            r = QRectF(pm.rect())
            dy = self.SHADOW_OFFSET_Y * unit
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            for spread, alpha in self.SHADOW_LAYERS:
                d = spread * unit
                outer = r.adjusted(-d, -d + dy, d, d + dy)
                painter.setBrush(QColor(0, 0, 0, alpha))
                # Four strips around the page; the page itself covers the middle.
                top = max(outer.top(), r.top())
                bottom = min(outer.bottom(), r.bottom())
                if r.top() > outer.top():
                    painter.drawRect(QRectF(outer.left(), outer.top(), outer.width(),
                                            r.top() - outer.top()))
                painter.drawRect(QRectF(outer.left(), r.bottom(), outer.width(),
                                        outer.bottom() - r.bottom()))
                painter.drawRect(QRectF(outer.left(), top, r.left() - outer.left(), bottom - top))
                painter.drawRect(QRectF(r.right(), top, outer.right() - r.right(), bottom - top))
            painter.restore()
        super().paint(painter, option, widget)

    # -- placeholders and previews --------------------------------------------------------

    def _set_placeholder(self, scale: float) -> None:
        """Cheap aspect-correct blank page so opening a long PDF renders nothing up front."""
        pw_pt = max(1.0, float(self.page_rect.width()))
        ph_pt = max(1.0, float(self.page_rect.height()))
        long_side = max(pw_pt, ph_pt)
        target = 64.0  # placeholder pixmap long edge in pixels
        sf = target / long_side
        pix_w = max(2, int(round(pw_pt * sf)))
        pix_h = max(2, int(round(ph_pt * sf)))
        pixmap = QPixmap(pix_w, pix_h)
        pixmap.fill(page_background(self.color_mode))
        self.setPixmap(pixmap)
        self.rendered_color_mode = self.color_mode
        # Pick render_zoom/render_scale_factor so _layout_pages math draws this
        # at page_rect.width() * current_zoom pixels on screen.
        self.render_zoom = sf
        self.render_scale_factor = 1.0
        self.is_preview = True
        self.is_blank = True
        self.setScale(scale / sf)

    def release(self, scale: float) -> None:
        """Drop the displayed render (the cache may keep it) and show a blank page."""
        self._set_placeholder(scale)

    def show_preview(self, pixmap: QPixmap, zoom: float, factor: float, scale: float) -> None:
        """Show *pixmap*, rendered at *zoom* x *factor*, scaled to the current zoom *scale*."""
        self.setPixmap(pixmap)
        self.render_zoom = zoom
        self.render_scale_factor = factor
        self.is_preview = True
        self.is_blank = False
        self.setScale((scale / zoom) / factor)

    def show_best_cached_preview(self, scale: float) -> bool:
        """Show the largest cached render of this page, if any, as a scaled preview."""
        best = None
        for key, pixmap in self._PIXMAP_CACHE.items():
            if (key[0] == self.doc_token and key[1] == self.page_index
                    and key[4] == self.color_mode):
                if best is None or pixmap.width() > best[2].width():
                    best = (key[2], key[3], pixmap)
        if best is None:
            return False
        self.show_preview(best[2], best[0], best[1], scale)
        self.rendered_color_mode = self.color_mode
        return True

    # -- real renders ---------------------------------------------------------------------

    @classmethod
    def render_factor_for(cls, page_rect: QRectF, zoom: float, device_pixel_ratio: float) -> float:
        """Pixels to render per scene unit: the device pixels, capped by MAX_RENDER_PIXELS."""
        want = max(1.0, float(device_pixel_ratio)) * cls.RENDER_HEADROOM
        area = max(1.0, page_rect.width() * page_rect.height()) * zoom * zoom
        cap = (cls.MAX_RENDER_PIXELS / area) ** 0.5
        return round(max(cls.MIN_RENDER_FACTOR, min(want, cap)), 3)

    def needs_render(self, zoom: float, factor: float) -> bool:
        return (
            self.is_preview
            or self.rendered_color_mode != self.color_mode
            or abs(zoom - self.render_zoom) >= 0.01
            or abs(factor - self.render_scale_factor) >= 0.01
        )

    def apply_render(self, pixmap: QPixmap, zoom: float, factor: float, scale: float) -> None:
        """Install a finished render made at *zoom* x *factor*; *scale* is the current zoom.

        *pixmap* must already be in this item's ``color_mode``.
        """
        self.setPixmap(pixmap)
        self.render_zoom = zoom
        self.render_scale_factor = factor
        self.rendered_color_mode = self.color_mode
        self.is_preview = False
        self.is_blank = False
        self.setScale((scale / zoom) / factor)
        self._cache_put(
            self._cache_key(self.doc_token, self.page_index, zoom, factor, self.color_mode),
            pixmap,
        )

    def apply_cached(self, zoom: float, factor: float) -> bool:
        """Install the cached render for *zoom* x *factor* if there is one."""
        pixmap = self._cache_get(
            self._cache_key(self.doc_token, self.page_index, zoom, factor, self.color_mode)
        )
        if pixmap is None:
            return False
        self.apply_render(pixmap, zoom, factor, zoom)
        return True

    # -- cache ----------------------------------------------------------------------------

    @staticmethod
    def _cache_key(
        doc_token: int, page_index: int, zoom: float, factor: float, color_mode: str = "normal"
    ) -> tuple:
        return (doc_token, page_index, round(zoom, 4), round(factor, 3), color_mode)

    @staticmethod
    def _pixmap_bytes(pixmap: QPixmap) -> int:
        return pixmap.width() * pixmap.height() * max(1, pixmap.depth()) // 8

    @classmethod
    def cache_bytes(cls) -> int:
        return sum(cls._pixmap_bytes(p) for p in cls._PIXMAP_CACHE.values())

    @classmethod
    def _cache_get(cls, key: tuple) -> QPixmap | None:
        pixmap = cls._PIXMAP_CACHE.get(key)
        if pixmap is None:
            return None
        cls._PIXMAP_CACHE.move_to_end(key)
        return pixmap

    @classmethod
    def _cache_put(cls, key: tuple, pixmap: QPixmap) -> None:
        cls._PIXMAP_CACHE[key] = pixmap
        cls._PIXMAP_CACHE.move_to_end(key)
        total = cls.cache_bytes()
        # Evict least recently used first; never the entry just added.
        while total > cls.CACHE_BUDGET_BYTES and len(cls._PIXMAP_CACHE) > 1:
            _key, old = cls._PIXMAP_CACHE.popitem(last=False)
            total -= cls._pixmap_bytes(old)

    @classmethod
    def purge_cache(cls, doc_token: int) -> None:
        """Forget every cached render of the document loaded as *doc_token*."""
        for key in [k for k in cls._PIXMAP_CACHE if k[0] == doc_token]:
            del cls._PIXMAP_CACHE[key]

    # -- synchronous rendering (non-lazy construction) ------------------------------------

    def _render(self, page: fitz.Page, scale: float, device_pixel_ratio: float = 1.0) -> None:
        factor = self.render_factor_for(self.page_rect, scale, device_pixel_ratio)
        if self.apply_cached(scale, factor):
            return
        mat = fitz.Matrix(scale * factor, scale * factor)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        img = img.copy() if self.color_mode == "normal" else apply_color_mode(img, self.color_mode)
        self.apply_render(QPixmap.fromImage(img), scale, factor, scale)

    def rerender(self, scale: float) -> bool:
        """Render synchronously at *scale* unless that render is already shown."""
        factor = self.render_factor_for(self.page_rect, scale, 1.0)
        if not self.needs_render(scale, factor):
            return False
        self._render(self._fitz_page, scale)
        return True

    def get_text_info_at(self, page_point: QPointF) -> dict | None:
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
