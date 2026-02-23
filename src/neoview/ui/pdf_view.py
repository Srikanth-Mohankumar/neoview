"""PDF viewer widget and interaction logic."""

from __future__ import annotations

from bisect import bisect_right
import os
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

import fitz
from PySide6.QtCore import QPoint, QPointF, QRectF, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QKeyEvent, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView, QLabel, QMessageBox, QStyle, QToolTip
import shiboken6

from neoview.ui.selection import SelectionRect
from neoview.ui.page_item import PageItem


class ToolMode(Enum):
    SELECT = auto()
    HAND = auto()
    MEASURE = auto()


class PdfView(QGraphicsView):
    """Full-featured PDF viewer with tools."""

    ZOOM_MODE_CUSTOM = "custom"
    ZOOM_MODE_FIT_WIDTH = "fit_width"
    ZOOM_MODE_FIT_PAGE = "fit_page"
    ZOOM_MODE_ACTUAL_SIZE = "actual_size"

    selection_changed = Signal()
    zoom_changed = Signal(float)
    page_changed = Signal(int, int)
    text_info_changed = Signal(str)
    text_selected = Signal(str)
    document_loaded = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.grabGesture(Qt.GestureType.PinchGesture)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QBrush(QColor("#141417")))
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.SmartViewportUpdate)
        self.verticalScrollBar().setSingleStep(36)
        self.horizontalScrollBar().setSingleStep(36)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._doc: Optional[fitz.Document] = None
        self._doc_path: Optional[str] = None
        self._pages: List[PageItem] = []
        self._page_positions: List[float] = []
        self._zoom: float = 1.0
        self._zoom_mode: str = self.ZOOM_MODE_CUSTOM
        self._tool: ToolMode = ToolMode.HAND

        self._rerender_timer = QTimer(self)
        self._rerender_timer.setSingleShot(True)
        self._rerender_timer.timeout.connect(self._rerender_pages)

        self._text_selecting = False
        self._text_select_start: Optional[QPointF] = None
        self._text_select_page: int = -1
        self._text_select_item: Optional[QGraphicsRectItem] = None
        self._text_highlight_items: List[Tuple[int, QGraphicsRectItem]] = []

        self._search_highlights: List[tuple] = []
        self._search_items: List[QGraphicsRectItem] = []
        self._page_links: List[List[Tuple[QRectF, Dict]]] = []
        self._hover_link: Optional[Dict] = None
        self._pressed_link: Optional[Dict] = None
        self._pressed_pos: Optional[QPointF] = None
        self._link_highlight_item: Optional[QGraphicsRectItem] = None

        self._selection: Optional[SelectionRect] = None
        self._selection_page: int = -1
        self._creating = False
        self._create_start: Optional[QPointF] = None
        self._interacting = False

        self._panning = False
        self._pan_start: Optional[QPointF] = None

        self._pinch_start_zoom: float = 1.0
        self._rotation: int = 0

        self._measure_badge = QLabel(self.viewport())
        self._measure_badge.setObjectName("FloatingMeasureBadge")
        self._measure_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._measure_badge.hide()
        self._link_badge = QLabel(self.viewport())
        self._link_badge.setObjectName("LinkBadge")
        self._link_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._link_badge.setFixedSize(18, 18)
        link_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon)
        self._link_badge.setPixmap(link_icon.pixmap(12, 12))
        self._link_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._link_badge.hide()

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.horizontalScrollBar().valueChanged.connect(self._on_scroll)

        self._update_cursor()

    @property
    def document(self) -> Optional[fitz.Document]:
        return self._doc

    @property
    def doc_path(self) -> Optional[str]:
        return self._doc_path

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def tool(self) -> ToolMode:
        return self._tool

    @tool.setter
    def tool(self, t: ToolMode):
        self._tool = t
        if t != ToolMode.SELECT:
            self.clear_text_selection()
            self.text_info_changed.emit("")
        self._update_cursor()

    @property
    def zoom_mode(self) -> str:
        return self._zoom_mode

    @property
    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0

    @property
    def current_page(self) -> int:
        if not self._page_positions:
            return 0
        scroll_y = self.verticalScrollBar().value() + self.viewport().height() / 3
        for i, y in enumerate(self._page_positions):
            if i + 1 < len(self._page_positions):
                if y <= scroll_y < self._page_positions[i + 1]:
                    return i
            else:
                return i
        return 0

    @property
    def selection_rect(self) -> Optional[QRectF]:
        return self._selection.pdf_rect if self._selection else None

    @property
    def selection_page(self) -> int:
        return self._selection_page

    @property
    def rotation(self) -> int:
        return self._rotation

    def _update_cursor(self):
        if self._tool != ToolMode.HAND:
            self._panning = False
            self._pan_start = None
        if self._tool == ToolMode.SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif self._tool == ToolMode.HAND:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif self._tool == ToolMode.MEASURE:
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def open_document(self, path: str) -> bool:
        try:
            doc = fitz.open(path)
            if doc.page_count == 0:
                raise ValueError("PDF has no pages")

            if self._doc:
                self._doc.close()

            self._doc = doc
            self._doc_path = os.path.abspath(path)
            self._clear_selection()
            self._render_all_pages()
            self.document_loaded.emit()
            return True
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Cannot open PDF:\n{exc}")
            return False

    def reload_document(self) -> bool:
        if not self._doc_path:
            return False

        scroll_pos = self.verticalScrollBar().value()
        sel_rect = self.selection_rect
        sel_page = self._selection_page

        new_doc = None
        try:
            new_doc = fitz.open(self._doc_path)
            if new_doc.page_count == 0:
                new_doc.close()
                return False

            new_pages = []
            gap = 20
            y = gap

            for i in range(new_doc.page_count):
                page = new_doc.load_page(i)
                item = PageItem(page, self._zoom, i)
                item.setPos(0, y)
                new_pages.append((item, y))
                y += item.page_rect.height() * self._zoom + gap

            if self._doc:
                self._doc.close()
            self._doc = new_doc

            self._scene.clear()
            self._pages.clear()
            self._page_positions.clear()
            self._page_links.clear()
            self._hover_link = None
            self._pressed_link = None
            self._pressed_pos = None
            self._selection = None
            self.clear_text_selection()
            self._clear_search_items()
            self._hide_link_badge()

            for item, pos_y in new_pages:
                self._scene.addItem(item)
                self._pages.append(item)
                self._page_positions.append(pos_y)

            if self._pages:
                max_width = max(p.page_rect.width() for p in self._pages) * self._zoom
                for p in self._pages:
                    offset = (max_width - p.page_rect.width() * self._zoom) / 2
                    p.setPos(offset, p.pos().y())

            max_width = max((p.page_rect.width() for p in self._pages), default=600) * self._zoom
            self._scene.setSceneRect(0, 0, max_width, y)

            self.verticalScrollBar().setValue(scroll_pos)

            if sel_rect and 0 <= sel_page < self.page_count:
                self._create_selection_on_page(sel_page, sel_rect)

            self._cache_page_links()
            self._rebuild_search_highlights()
            self._update_measure_badge()
            self._emit_page_info()
            self.document_loaded.emit()
            return True
        except Exception:
            if new_doc is not None:
                try:
                    new_doc.close()
                except Exception:
                    pass
            return False

    def close_document(self):
        if self._doc:
            self._doc.close()
            self._doc = None
        self._doc_path = None
        self._scene.clear()
        self._pages.clear()
        self._page_positions.clear()
        self._page_links.clear()
        self._link_highlight_item = None
        self._hover_link = None
        self._pressed_link = None
        self._pressed_pos = None
        self._selection = None
        self.clear_text_selection()
        self._clear_search_items()
        self._hide_measure_badge()
        self._hide_link_badge()

    def _render_all_pages(self, keep_selection: bool = False):
        selected_rect = self.selection_rect if keep_selection else None
        selected_page = self._selection_page if keep_selection else -1

        self._scene.clear()
        self._pages.clear()
        self._page_positions.clear()
        self._page_links.clear()
        self._link_highlight_item = None
        self._hover_link = None
        self._pressed_link = None
        self._pressed_pos = None
        self._selection = None
        self._selection_page = -1
        self.clear_text_selection()
        self._clear_search_items()
        self._hide_measure_badge()
        self._hide_link_badge()

        if not self._doc:
            return

        gap = 20
        y = gap

        for i in range(self._doc.page_count):
            page = self._doc.load_page(i)
            item = PageItem(page, self._zoom, i)
            item.setPos(0, y)
            self._scene.addItem(item)
            self._pages.append(item)
            self._page_positions.append(y)
            y += item.page_rect.height() * self._zoom + gap

        if self._pages:
            max_width = max(p.page_rect.width() for p in self._pages) * self._zoom
            for p in self._pages:
                offset = (max_width - p.page_rect.width() * self._zoom) / 2
                p.setPos(offset, p.pos().y())

        total_height = y
        max_width = max((p.page_rect.width() for p in self._pages), default=600) * self._zoom
        self._scene.setSceneRect(0, 0, max_width, total_height)

        if selected_rect and 0 <= selected_page < len(self._pages):
            self._create_selection_on_page(selected_page, selected_rect)

        self._cache_page_links()
        self._rebuild_search_highlights()
        self._update_measure_badge()
        self._emit_page_info()

    def _layout_pages(self):
        if not self._pages:
            self._scene.setSceneRect(0, 0, 600, 0)
            return

        gap = 20
        y = gap

        for p in self._pages:
            render_zoom = p.render_zoom if p.render_zoom > 0 else self._zoom
            p.setScale((self._zoom / render_zoom) / PageItem.RENDER_SCALE)
            p.setPos(0, y)
            y += p.page_rect.height() * self._zoom + gap

        max_width = max(p.page_rect.width() for p in self._pages) * self._zoom
        for p in self._pages:
            offset = (max_width - p.page_rect.width() * self._zoom) / 2
            p.setPos(offset, p.pos().y())

        self._scene.setSceneRect(0, 0, max_width, y)

        if self._selection and 0 <= self._selection_page < len(self._pages):
            page = self._pages[self._selection_page]
            self._selection.setPos(page.pos())
            self._selection.setScale(self._zoom)

        if self._text_select_item and 0 <= self._text_select_page < len(self._pages):
            page = self._pages[self._text_select_page]
            self._text_select_item.setPos(page.pos())
            self._text_select_item.setScale(self._zoom)

        if self._text_highlight_items:
            for page_idx, item in self._text_highlight_items:
                if 0 <= page_idx < len(self._pages) and shiboken6.isValid(item):
                    page = self._pages[page_idx]
                    item.setPos(page.pos())
                    item.setScale(self._zoom)

        self._rebuild_search_highlights()
        self._update_measure_badge()

    def _cache_page_links(self):
        self._page_links = []
        for page_item in self._pages:
            links: List[Tuple[QRectF, Dict]] = []
            try:
                for link in page_item._fitz_page.get_links():
                    src = link.get("from")
                    if not src:
                        continue
                    rect = QRectF(src.x0, src.y0, src.width, src.height)
                    if rect.width() <= 0 or rect.height() <= 0:
                        continue
                    kind = link.get("kind")
                    has_internal_target = isinstance(link.get("page"), int) or bool(link.get("to"))
                    if kind in (fitz.LINK_URI, fitz.LINK_GOTO, fitz.LINK_NAMED) or has_internal_target:
                        links.append((rect, link))
            except Exception:
                pass
            self._page_links.append(links)

    def _visible_page_indices(self, overscan: int = 0) -> List[int]:
        if not self._pages:
            return []
        visible_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        top = visible_rect.top()
        bottom = visible_rect.bottom()
        visible: List[int] = []

        start_idx = max(0, bisect_right(self._page_positions, top) - 1)
        for idx in range(start_idx, len(self._pages)):
            page = self._pages[idx]
            page_top = page.pos().y()
            page_bottom = page_top + page.page_rect.height() * self._zoom
            if page_top > bottom:
                break
            if page_bottom < top:
                continue
            visible.append(idx)

        if not visible:
            current = self.current_page
            if 0 <= current < len(self._pages):
                visible = [current]

        if overscan <= 0:
            return visible

        expanded = set()
        for idx in visible:
            start = max(0, idx - overscan)
            end = min(len(self._pages) - 1, idx + overscan)
            expanded.update(range(start, end + 1))
        return sorted(expanded)

    def _visible_page_needs_rerender(self) -> bool:
        for idx in self._visible_page_indices():
            page = self._pages[idx]
            if abs(page.render_zoom - self._zoom) >= 0.01:
                return True
        return False

    def _rerender_pages(self):
        if not self._pages:
            return

        rerendered = False
        for idx in self._visible_page_indices(overscan=2):
            page = self._pages[idx]
            if page.rerender(self._zoom):
                page.setScale(1.0 / PageItem.RENDER_SCALE)
                rerendered = True

        if rerendered:
            self.viewport().update()

    def _emit_page_info(self):
        self.page_changed.emit(self.current_page + 1, self.page_count)

    def _on_scroll(self):
        self._emit_page_info()
        self._update_measure_badge()
        self._hide_link_badge()
        if self._visible_page_needs_rerender():
            self._rerender_timer.start(40)

    def set_zoom(self, z: float, immediate: bool = False, zoom_mode: str = ZOOM_MODE_CUSTOM):
        z = max(0.25, min(z, 5.0))
        if zoom_mode not in {
            self.ZOOM_MODE_CUSTOM,
            self.ZOOM_MODE_FIT_WIDTH,
            self.ZOOM_MODE_FIT_PAGE,
            self.ZOOM_MODE_ACTUAL_SIZE,
        }:
            zoom_mode = self.ZOOM_MODE_CUSTOM

        if abs(z - self._zoom) < 0.01:
            self._zoom_mode = zoom_mode
            return

        self._zoom = z
        self._zoom_mode = zoom_mode
        if self._pages:
            self._layout_pages()
            if immediate:
                self._rerender_timer.stop()
                self._rerender_pages()
            else:
                self._rerender_timer.start(55)
        else:
            self._render_all_pages()
        self.zoom_changed.emit(z)

    def rotate_by(self, delta_degrees: int):
        self.set_rotation(self._rotation + delta_degrees)

    def set_rotation(self, degrees: int):
        degrees = degrees % 360
        if degrees == self._rotation:
            return
        self._rotation = degrees
        self.resetTransform()
        if self._rotation:
            self.rotate(self._rotation)

    def zoom_by(self, factor: float):
        self.set_zoom(self._zoom * factor, zoom_mode=self.ZOOM_MODE_CUSTOM)

    def fit_width(self):
        if not self._pages:
            return
        page_width = self._pages[0].page_rect.width()
        view_width = self.viewport().width() - 40
        self.set_zoom(view_width / page_width, immediate=True, zoom_mode=self.ZOOM_MODE_FIT_WIDTH)

    def fit_page(self):
        if not self._pages:
            return
        page = self._pages[0].page_rect
        view_w = self.viewport().width() - 40
        view_h = self.viewport().height() - 40
        scale_w = view_w / page.width()
        scale_h = view_h / page.height()
        self.set_zoom(min(scale_w, scale_h), immediate=True, zoom_mode=self.ZOOM_MODE_FIT_PAGE)

    def actual_size(self):
        self.set_zoom(1.0, immediate=True, zoom_mode=self.ZOOM_MODE_ACTUAL_SIZE)

    def current_page_size(self) -> Optional[QRectF]:
        if 0 <= self.current_page < len(self._pages):
            page = self._pages[self.current_page]
            return page.page_rect
        return None

    def go_to_page(self, page_num: int):
        if 0 <= page_num < len(self._page_positions):
            self.verticalScrollBar().setValue(int(self._page_positions[page_num]))

    def next_page(self):
        self.go_to_page(self.current_page + 1)

    def prev_page(self):
        self.go_to_page(self.current_page - 1)

    def first_page(self):
        self.go_to_page(0)

    def last_page(self):
        self.go_to_page(self.page_count - 1)

    def _clear_selection(self):
        if self._selection:
            if shiboken6.isValid(self._selection):
                self._scene.removeItem(self._selection)
            self._selection = None
            self._selection_page = -1
            self._hide_measure_badge()
            self.selection_changed.emit()

    def clear_selection(self):
        self._clear_selection()

    def clear_text_selection(self):
        self._clear_text_drag_box()
        self._clear_text_highlights()
        self._text_select_page = -1
        self._text_select_start = None

    def clear_all_selection(self):
        self._clear_selection()
        self.clear_text_selection()

    def _clear_text_drag_box(self):
        if self._text_select_item and shiboken6.isValid(self._text_select_item):
            self._scene.removeItem(self._text_select_item)
        self._text_select_item = None

    def _clear_text_highlights(self):
        for page_idx, item in self._text_highlight_items:
            if shiboken6.isValid(item):
                self._scene.removeItem(item)
        self._text_highlight_items.clear()

    def set_search_highlights(self, highlights: List[tuple]):
        self._search_highlights = highlights
        self._rebuild_search_highlights()

    def _clear_search_items(self):
        for item in self._search_items:
            if shiboken6.isValid(item):
                self._scene.removeItem(item)
        self._search_items.clear()

    def _rebuild_search_highlights(self):
        self._clear_search_items()
        if not self._search_highlights:
            return
        for page_idx, rect, is_current in self._search_highlights:
            if not (0 <= page_idx < len(self._pages)):
                continue
            page = self._pages[page_idx]
            item = QGraphicsRectItem(rect)
            item.setPos(page.pos())
            item.setScale(self._zoom)
            pen = QPen(QColor(255, 200, 0, 220 if is_current else 140))
            pen.setWidthF(1.0 if is_current else 0.8)
            pen.setCosmetic(True)
            item.setPen(pen)
            item.setBrush(QBrush(QColor(255, 255, 0, 60 if is_current else 35)))
            item.setZValue(900)
            self._scene.addItem(item)
            self._search_items.append(item)

    def extract_text_in_rect(self, page_idx: int, rect: QRectF) -> str:
        if 0 <= page_idx < len(self._pages):
            page_item = self._pages[page_idx]
            r = fitz.Rect(rect.x(), rect.y(), rect.right(), rect.bottom())
            return page_item._fitz_page.get_textbox(r).strip()
        return ""

    def _highlight_text_in_rect(self, page_idx: int, rect: QRectF) -> bool:
        self._clear_text_highlights()
        if not (0 <= page_idx < len(self._pages)):
            return False
        page_item = self._pages[page_idx]
        try:
            blocks = page_item._fitz_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        except Exception:
            return False

        page = self._pages[page_idx]
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span.get("bbox", (0, 0, 0, 0))
                    span_rect = QRectF(bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1])
                    if not span_rect.intersects(rect):
                        continue
                    item = QGraphicsRectItem(span_rect)
                    item.setPos(page.pos())
                    item.setScale(self._zoom)
                    pen = QPen(QColor(255, 200, 0, 200))
                    pen.setWidthF(0.5)
                    pen.setCosmetic(True)
                    item.setPen(pen)
                    item.setBrush(QBrush(QColor(255, 255, 0, 70)))
                    item.setZValue(940)
                    self._scene.addItem(item)
                    self._text_highlight_items.append((page_idx, item))
        return bool(self._text_highlight_items)

    def scroll_to_rect(self, page_idx: int, rect: fitz.Rect):
        if 0 <= page_idx < len(self._pages):
            page = self._pages[page_idx]
            y = page.pos().y() + rect.y0 * self._zoom - 40
            self.verticalScrollBar().setValue(int(max(0, y)))

    def _get_page_at(self, scene_pos: QPointF) -> int:
        for i, page in enumerate(self._pages):
            rect = QRectF(page.pos(), page.page_rect.size() * self._zoom)
            if rect.contains(scene_pos):
                return i
        return -1

    def _scene_to_page(self, scene_pos: QPointF, page_idx: int) -> QPointF:
        if 0 <= page_idx < len(self._pages):
            page = self._pages[page_idx]
            local = scene_pos - page.pos()
            return QPointF(local.x() / self._zoom, local.y() / self._zoom)
        return QPointF()

    def _create_selection_on_page(self, page_idx: int, rect: QRectF):
        if not (0 <= page_idx < len(self._pages)):
            return

        self._clear_selection()
        page = self._pages[page_idx]
        self._selection = SelectionRect(rect, page.page_rect)
        self._selection.setPos(page.pos())
        self._selection.setScale(self._zoom)
        self._scene.addItem(self._selection)
        self._selection_page = page_idx
        self._update_measure_badge()
        self.selection_changed.emit()

    def _hide_measure_badge(self):
        self._measure_badge.hide()

    def _hide_link_badge(self):
        self._hover_link = None
        self._link_badge.hide()
        if self._link_highlight_item and shiboken6.isValid(self._link_highlight_item):
            self._link_highlight_item.hide()
        QToolTip.hideText()

    def _clear_link_press(self):
        self._pressed_link = None
        self._pressed_pos = None

    def _same_link(self, first: Dict, second: Dict) -> bool:
        f = first.get("link", {})
        s = second.get("link", {})
        return (
            f.get("uri") == s.get("uri")
            and f.get("page") == s.get("page")
            and f.get("to") == s.get("to")
            and f.get("kind") == s.get("kind")
        )

    def _extract_target_y(self, target) -> Optional[float]:
        if target is None:
            return None
        if isinstance(target, (tuple, list)) and len(target) >= 2:
            try:
                return float(target[1])
            except (TypeError, ValueError):
                return None

        y_attr = getattr(target, "y", None)
        if callable(y_attr):
            try:
                return float(y_attr())
            except (TypeError, ValueError):
                return None
        if y_attr is not None:
            try:
                return float(y_attr)
            except (TypeError, ValueError):
                return None
        return None

    def _link_at_scene_pos(self, scene_pos: QPointF) -> Optional[Dict]:
        page_idx = self._get_page_at(scene_pos)
        if page_idx < 0 or page_idx >= len(self._page_links):
            return None
        page_pos = self._scene_to_page(scene_pos, page_idx)
        for rect, link in self._page_links[page_idx]:
            if rect.contains(page_pos):
                return {"page_idx": page_idx, "rect": rect, "link": link}
        return None

    def _ensure_link_highlight_item(self) -> QGraphicsRectItem:
        if self._link_highlight_item and shiboken6.isValid(self._link_highlight_item):
            return self._link_highlight_item

        item = QGraphicsRectItem()
        pen = QPen(QColor(91, 141, 246, 215))
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(QBrush(QColor(91, 141, 246, 45)))
        item.setZValue(980)
        self._scene.addItem(item)
        self._link_highlight_item = item
        return item

    def _show_link_highlight(self, link_info: Dict):
        page_idx = link_info.get("page_idx", -1)
        if not (0 <= page_idx < len(self._pages)):
            return
        rect = link_info.get("rect")
        if not isinstance(rect, QRectF):
            return

        page = self._pages[page_idx]
        highlight = self._ensure_link_highlight_item()
        scene_rect = QRectF(
            page.pos().x() + rect.x() * self._zoom,
            page.pos().y() + rect.y() * self._zoom,
            rect.width() * self._zoom,
            rect.height() * self._zoom,
        )
        highlight.setRect(scene_rect)
        highlight.show()

    def _link_tooltip_text(self, link: Dict) -> str:
        uri = str(link.get("uri") or "").strip()
        if uri:
            if uri.startswith("#"):
                return f"Navigate to destination {uri}"
            return uri

        page_idx = link.get("page")
        if isinstance(page_idx, int) and page_idx >= 0:
            target_y = self._extract_target_y(link.get("to"))
            if target_y is not None:
                return f"Go to page {page_idx + 1} at y={target_y:.0f}"
            return f"Go to page {page_idx + 1}"

        return "Follow link"

    def _update_link_hover(self, scene_pos: QPointF, viewport_pos: QPoint):
        if self._tool not in (ToolMode.HAND, ToolMode.SELECT):
            self._hide_link_badge()
            return
        if self._text_selecting or self._creating or self._interacting or self._panning:
            self._hide_link_badge()
            return

        link_info = self._link_at_scene_pos(scene_pos)
        if not link_info:
            self._hide_link_badge()
            if self._tool == ToolMode.HAND:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        self._hover_link = link_info
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        x = min(viewport_pos.x() + 12, self.viewport().width() - self._link_badge.width() - 6)
        y = max(6, viewport_pos.y() - self._link_badge.height() - 8)
        self._link_badge.move(x, y)
        self._link_badge.show()
        self._link_badge.raise_()
        self._show_link_highlight(link_info)

        tooltip = self._link_tooltip_text(link_info.get("link", {}))
        if tooltip:
            QToolTip.showText(self.viewport().mapToGlobal(viewport_pos + QPoint(14, 16)), tooltip, self.viewport())

    def _activate_link(self, link_info: Dict):
        if not link_info:
            return
        link = link_info["link"]
        self._hide_link_badge()

        kind = link.get("kind")
        uri = link.get("uri")
        if uri:
            if kind == fitz.LINK_URI and not str(uri).startswith("#"):
                QDesktopServices.openUrl(QUrl(uri))
                return
            if self._doc:
                try:
                    page_id, _x, y = self._doc.resolve_link(uri)
                except Exception:
                    page_id, y = None, None
                if isinstance(page_id, int) and 0 <= page_id < self.page_count:
                    self.go_to_page(page_id)
                    if y is not None and 0 <= page_id < len(self._pages):
                        page = self._pages[page_id]
                        dest_y = page.pos().y() + float(y) * self._zoom - 30
                        self.verticalScrollBar().setValue(int(max(0, dest_y)))
                    return

        page_idx = link.get("page")
        if isinstance(page_idx, int) and 0 <= page_idx < self.page_count:
            self.go_to_page(page_idx)
            target_y = self._extract_target_y(link.get("to"))
            if target_y is not None and 0 <= page_idx < len(self._pages):
                page = self._pages[page_idx]
                y = page.pos().y() + target_y * self._zoom - 30
                self.verticalScrollBar().setValue(int(max(0, y)))

    def _update_measure_badge(self):
        if not self._selection or not (0 <= self._selection_page < len(self._pages)):
            self._hide_measure_badge()
            return

        rect = self._selection.pdf_rect
        text = (
            f"W {rect.width():.1f}  "
            f"H {rect.height():.1f}  "
            f"X {rect.x():.1f}  "
            f"Y {rect.y():.1f}"
        )
        self._measure_badge.setText(text)
        self._measure_badge.adjustSize()

        page = self._pages[self._selection_page]
        anchor_scene = page.pos() + QPointF(rect.left() * self._zoom, rect.top() * self._zoom)
        anchor = self.mapFromScene(anchor_scene)

        margin = 8
        x = anchor.x()
        y = anchor.y() - self._measure_badge.height() - 8
        max_x = self.viewport().width() - self._measure_badge.width() - margin

        x = max(margin, min(x, max_x))
        y = max(margin, y)

        self._measure_badge.move(int(x), int(y))
        self._measure_badge.show()
        self._measure_badge.raise_()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            return

        self._clear_link_press()
        scene_pos = self.mapToScene(e.position().toPoint())
        self._update_link_hover(scene_pos, e.position().toPoint())

        if self._hover_link and self._tool in (ToolMode.HAND, ToolMode.SELECT):
            self._pressed_link = self._hover_link
            self._pressed_pos = QPointF(e.position())
            e.accept()
            return

        if self._tool == ToolMode.HAND:
            self._panning = True
            self._pan_start = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return

        if self._tool == ToolMode.SELECT:
            page_idx = self._get_page_at(scene_pos)
            if page_idx >= 0:
                self.clear_text_selection()
                self._text_selecting = True
                self._text_select_page = page_idx
                self._text_select_start = self._scene_to_page(scene_pos, page_idx)
                rect = QRectF(self._text_select_start, self._text_select_start)
                page = self._pages[page_idx]
                self._text_select_item = QGraphicsRectItem(rect)
                self._text_select_item.setPos(page.pos())
                self._text_select_item.setScale(self._zoom)
                pen = QPen(QColor(91, 141, 246, 220))
                pen.setWidthF(0.5)
                pen.setStyle(Qt.PenStyle.DotLine)
                pen.setCosmetic(True)
                self._text_select_item.setPen(pen)
                self._text_select_item.setBrush(QBrush(QColor(91, 141, 246, 40)))
                self._text_select_item.setZValue(950)
                self._scene.addItem(self._text_select_item)
            e.accept()
            return

        if self._tool == ToolMode.MEASURE:
            if self._selection:
                page = self._pages[self._selection_page] if 0 <= self._selection_page < len(self._pages) else None
                if page:
                    local_pos = self._scene_to_page(scene_pos, self._selection_page)
                    hit = self._selection.hit_test(local_pos)
                    if hit:
                        self._interacting = True
                        self._selection.start_drag(local_pos, hit)
                        e.accept()
                        return

            page_idx = self._get_page_at(scene_pos)
            if page_idx >= 0:
                self._creating = True
                self._create_start = self._scene_to_page(scene_pos, page_idx)
                self._selection_page = page_idx
                self._clear_selection()
                e.accept()
                return

        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        scene_pos = self.mapToScene(e.position().toPoint())
        self._update_link_hover(scene_pos, e.position().toPoint())

        if self._tool == ToolMode.HAND and self._panning and self._pan_start is not None:
            delta = e.position() - self._pan_start
            self._pan_start = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            e.accept()
            return

        if self._tool == ToolMode.SELECT and self._text_selecting and self._text_select_item:
            page_idx = self._text_select_page
            if page_idx >= 0:
                local_pos = self._scene_to_page(scene_pos, page_idx)
                page = self._pages[page_idx]
                local_pos = QPointF(
                    max(0, min(local_pos.x(), page.page_rect.width())),
                    max(0, min(local_pos.y(), page.page_rect.height())),
                )
                rect = QRectF(self._text_select_start, local_pos).normalized()
                self._text_select_item.setRect(rect)
            e.accept()
            return

        if self._tool == ToolMode.MEASURE:
            if self._interacting and self._selection:
                local_pos = self._scene_to_page(scene_pos, self._selection_page)
                self._selection.update_drag(local_pos)
                self._update_measure_badge()
                self.selection_changed.emit()
                e.accept()
                return

            if self._creating and self._create_start is not None:
                page_idx = self._selection_page
                if page_idx >= 0:
                    local_pos = self._scene_to_page(scene_pos, page_idx)
                    page = self._pages[page_idx]
                    local_pos = QPointF(
                        max(0, min(local_pos.x(), page.page_rect.width())),
                        max(0, min(local_pos.y(), page.page_rect.height())),
                    )
                    rect = QRectF(self._create_start, local_pos).normalized()

                    if not self._selection:
                        self._create_selection_on_page(page_idx, rect)
                    else:
                        self._selection.pdf_rect = rect

                    self._update_measure_badge()
                    self.selection_changed.emit()
                e.accept()
                return

            if self._selection:
                local_pos = self._scene_to_page(scene_pos, self._selection_page)
                hit = self._selection.hit_test(local_pos)
                if hit:
                    self.setCursor(self._selection.cursor_for_mode(hit))
                else:
                    self.setCursor(Qt.CursorShape.CrossCursor)

        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._pressed_link and self._pressed_pos is not None:
                moved = e.position() - self._pressed_pos
                moved_too_far = abs(moved.x()) + abs(moved.y()) > 6
                current_link = self._link_at_scene_pos(self.mapToScene(e.position().toPoint()))
                same_link = current_link is not None and self._same_link(self._pressed_link, current_link)
                if not moved_too_far and same_link:
                    self._activate_link(current_link)
                self._clear_link_press()
                e.accept()
                return

            if self._tool == ToolMode.HAND and self._panning:
                self._panning = False
                self._pan_start = None
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                self._hide_link_badge()
                e.accept()
                return

            if self._tool == ToolMode.SELECT and self._text_selecting:
                self._text_selecting = False
                if self._text_select_item and self._text_select_start is not None:
                    rect = self._text_select_item.rect()
                    if rect.width() < 2 and rect.height() < 2:
                        page_idx = self._text_select_page
                        if page_idx >= 0:
                            page_item = self._pages[page_idx]
                            info = page_item.get_text_info_at(self._text_select_start)
                            if info:
                                text_info = f"Font: {info['font']} | Size: {info['size']:.1f}pt"
                                style = info.get("style")
                                if style:
                                    text_info += f" | Style: {style}"
                                self.text_info_changed.emit(text_info)
                            else:
                                self.text_info_changed.emit("")
                        self.clear_text_selection()
                    else:
                        text = self.extract_text_in_rect(self._text_select_page, rect)
                        self.text_selected.emit(text)
                        self._highlight_text_in_rect(self._text_select_page, rect)
                        self._clear_text_drag_box()
                    self._text_select_page = -1
                    self._text_select_start = None
                e.accept()
                return

            if self._interacting and self._selection:
                self._selection.end_drag()
                self._interacting = False

            if self._creating:
                self._creating = False
                self._create_start = None
                if self._selection and (
                    self._selection.pdf_rect.width() < SelectionRect.MIN_SIZE
                    or self._selection.pdf_rect.height() < SelectionRect.MIN_SIZE
                ):
                    self._clear_selection()

        super().mouseReleaseEvent(e)

    def wheelEvent(self, e: QWheelEvent):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = e.angleDelta().y()
            if delta == 0 and not e.pixelDelta().isNull():
                delta = e.pixelDelta().y()
            if delta != 0:
                anchor = e.position().toPoint()
                before = self.mapToScene(anchor)
                factor = 1.08 ** (delta / 120.0)
                self.zoom_by(factor)
                after = self.mapToScene(anchor)
                shift = after - before
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + int(shift.x()))
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() + int(shift.y()))
            e.accept()
            return
        super().wheelEvent(e)

    def keyPressEvent(self, e: QKeyEvent):
        if self._selection:
            key = e.key()
            mods = e.modifiers()
            step = 10.0 if mods & Qt.KeyboardModifier.ShiftModifier else 1.0
            resize = bool(mods & Qt.KeyboardModifier.ControlModifier)

            if key == Qt.Key.Key_Left:
                if resize:
                    self._selection.resize_by(-step, 0)
                else:
                    self._selection.nudge(-step, 0)
                self._update_measure_badge()
                self.selection_changed.emit()
                e.accept()
                return
            if key == Qt.Key.Key_Right:
                if resize:
                    self._selection.resize_by(step, 0)
                else:
                    self._selection.nudge(step, 0)
                self._update_measure_badge()
                self.selection_changed.emit()
                e.accept()
                return
            if key == Qt.Key.Key_Up:
                if resize:
                    self._selection.resize_by(0, -step)
                else:
                    self._selection.nudge(0, -step)
                self._update_measure_badge()
                self.selection_changed.emit()
                e.accept()
                return
            if key == Qt.Key.Key_Down:
                if resize:
                    self._selection.resize_by(0, step)
                else:
                    self._selection.nudge(0, step)
                self._update_measure_badge()
                self.selection_changed.emit()
                e.accept()
                return
            if key == Qt.Key.Key_Escape:
                self._clear_selection()
                e.accept()
                return

        super().keyPressEvent(e)

    def event(self, e):
        if e.type() == e.Type.Gesture:
            pinch = e.gesture(Qt.GestureType.PinchGesture)
            if pinch:
                state = pinch.state()
                if state == Qt.GestureState.GestureStarted:
                    self._pinch_start_zoom = self._zoom
                elif state == Qt.GestureState.GestureUpdated:
                    total = pinch.totalScaleFactor()
                    if total and total > 0:
                        self.set_zoom(self._pinch_start_zoom * total, zoom_mode=self.ZOOM_MODE_CUSTOM)
                return True
        return super().event(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._pages and self._zoom_mode in (self.ZOOM_MODE_FIT_WIDTH, self.ZOOM_MODE_FIT_PAGE):
            if self._zoom_mode == self.ZOOM_MODE_FIT_WIDTH:
                page_width = self._pages[0].page_rect.width()
                view_width = self.viewport().width() - 40
                self.set_zoom(view_width / page_width, zoom_mode=self.ZOOM_MODE_FIT_WIDTH)
            else:
                page = self._pages[0].page_rect
                view_w = self.viewport().width() - 40
                view_h = self.viewport().height() - 40
                self.set_zoom(min(view_w / page.width(), view_h / page.height()), zoom_mode=self.ZOOM_MODE_FIT_PAGE)
        self._update_measure_badge()
        self._hide_link_badge()

    def leaveEvent(self, e):
        self._hide_link_badge()
        super().leaveEvent(e)
