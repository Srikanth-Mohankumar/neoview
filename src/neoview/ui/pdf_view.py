"""PDF viewer widget and interaction logic."""

from __future__ import annotations

from bisect import bisect_right
import html
import os
import re
from urllib.parse import unquote
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple

import fitz
from PySide6.QtCore import QPoint, QPointF, QRectF, QTimer, QUrl, Signal, Qt
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QStyle,
    QToolTip,
)
import shiboken6

from neoview.models.view_state import AnnotationRecord
from neoview.ui.annotation_item import AnnotationItem
from neoview.ui.selection import SelectionRect
from neoview.ui.page_item import PageItem


class ToolMode(Enum):
    SELECT = auto()
    HAND = auto()
    MEASURE = auto()
    ANNOTATE = auto()


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
    annotation_clicked = Signal(str)
    annotation_created = Signal(object)   # emits AnnotationRecord
    annotation_deleted = Signal(str)      # emits annotation id
    annotation_edit_requested = Signal(str)  # emits annotation id (double-click / context menu)
    document_loaded = Signal()
    performance_mode_toggled = Signal(bool)

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
        app = QApplication.instance()
        theme_mode = ""
        if app is not None:
            theme_mode = str(app.property("theme_mode") or "").lower()
        canvas_bg = "#141417" if theme_mode == "dark" else "#eef2f7"
        self.setBackgroundBrush(QBrush(QColor(canvas_bg)))
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
        self._annotations: List[AnnotationRecord] = []
        self._annotation_items: List[Tuple[int, AnnotationItem]] = []
        self._annotation_index: Dict[str, AnnotationRecord] = {}
        self._selected_annotation_id: Optional[str] = None

        # Annotate tool state
        self._annotate_type: str = "highlight"
        self._annotate_color: str = "#f7c948"
        self._annotate_opacity: float = 0.3
        self._annotate_border_width: float = 2.0
        self._annotate_font_size: float = 12.0
        self._annotate_creating: bool = False
        self._annotate_start: Optional[QPointF] = None
        self._annotate_page: int = -1
        self._annotate_preview_rect: Optional[QGraphicsRectItem] = None
        self._annotate_freehand_points: List[List[float]] = []
        self._annotate_freehand_path_item: Optional[QGraphicsPathItem] = None

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

        self._performance_mode = False
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
        if t != ToolMode.ANNOTATE:
            self._cancel_annotate_drawing()
        self._update_cursor()

    @property
    def annotate_type(self) -> str:
        return self._annotate_type

    @annotate_type.setter
    def annotate_type(self, t: str):
        self._annotate_type = t

    @property
    def annotate_color(self) -> str:
        return self._annotate_color

    @annotate_color.setter
    def annotate_color(self, c: str):
        self._annotate_color = c

    @property
    def annotate_opacity(self) -> float:
        return self._annotate_opacity

    @annotate_opacity.setter
    def annotate_opacity(self, v: float):
        self._annotate_opacity = max(0.05, min(1.0, v))

    @property
    def annotate_border_width(self) -> float:
        return self._annotate_border_width

    @annotate_border_width.setter
    def annotate_border_width(self, v: float):
        self._annotate_border_width = max(0.5, min(20.0, v))

    @property
    def annotate_font_size(self) -> float:
        return self._annotate_font_size

    @annotate_font_size.setter
    def annotate_font_size(self, v: float):
        self._annotate_font_size = max(6.0, min(72.0, v))

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
        elif self._tool == ToolMode.ANNOTATE:
            if self._annotate_type == "freehand":
                self.setCursor(Qt.CursorShape.ArrowCursor)
            else:
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
            self._annotation_items.clear()
            self._selected_annotation_id = None
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
            self._rebuild_annotation_items()
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
        self._annotations.clear()
        self._annotation_index.clear()
        self._annotation_items.clear()
        self._selected_annotation_id = None
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
        self._annotation_items.clear()
        self._selected_annotation_id = None
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
        self._rebuild_annotation_items()
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

        if self._annotation_items:
            for page_idx, item in self._annotation_items:
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
            page_rect = getattr(page, "page_rect", QRectF())
            page_bottom = page_top + page_rect.height() * self._zoom
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
            render_zoom = getattr(page, "render_zoom", self._zoom)
            if abs(render_zoom - self._zoom) >= 0.01:
                return True
        return False

    def _rerender_pages(self):
        if not self._pages:
            return

        rerendered = False
        for idx in self._visible_page_indices(overscan=2):
            page = self._pages[idx]
            rerender = getattr(page, "rerender", None)
            if callable(rerender) and rerender(self._zoom):
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
            if not self._performance_mode:
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
                if not self._performance_mode:
                    self._rerender_timer.start(55)
        else:
            self._render_all_pages()
        self.zoom_changed.emit(z)

    def set_performance_mode(self, enabled: bool) -> None:
        """Enable/disable performance mode. When enabled, defers expensive zoom/scroll rerenders."""
        self._performance_mode = enabled
        self.performance_mode_toggled.emit(enabled)
        if not enabled:
            if self._visible_page_needs_rerender():
                self._rerender_timer.start(40)

    def is_performance_mode(self) -> bool:
        """Return True if performance mode is currently enabled."""
        return self._performance_mode

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

    def _clear_annotation_items(self):
        for _page_idx, item in self._annotation_items:
            if shiboken6.isValid(item):
                self._scene.removeItem(item)
        self._annotation_items.clear()

    def set_annotations(self, annotations: List[AnnotationRecord]):
        self._annotations = list(annotations or [])
        self._annotation_index = {item.id: item for item in self._annotations if item.id}
        self._rebuild_annotation_items()

    def select_annotation(self, ann_id: Optional[str]):
        """Visually select/deselect an annotation by id."""
        self._selected_annotation_id = ann_id
        for _pg, item in self._annotation_items:
            if shiboken6.isValid(item):
                item.set_selected_highlight(item.annotation_id == ann_id)

    def scroll_to_page_y(self, page_idx: int, y: float):
        self._scroll_to_destination(page_idx, y, y_is_pdf_coords=False)

    def _annotation_hit_at_scene_pos(self, scene_pos: QPointF) -> Optional[str]:
        for item in self._scene.items(scene_pos):
            if isinstance(item, AnnotationItem):
                return item.annotation_id
        return None

    def _rebuild_annotation_items(self):
        self._clear_annotation_items()
        if not self._annotations or not self._pages:
            return

        for ann in self._annotations:
            if not (0 <= ann.page < len(self._pages)):
                continue
            x, y, w, h = ann.rect
            base_rect = QRectF(float(x), float(y), max(0.0, float(w)), max(0.0, float(h)))
            # For non-rect types (freehand/line/arrow) allow zero-area rects as long as points exist
            if base_rect.width() <= 0 and base_rect.height() <= 0 and ann.type not in ("freehand",):
                continue

            page = self._pages[ann.page]
            item = AnnotationItem(ann)
            if ann.contents and ann.type in ("note", "text-box"):
                item.setToolTip(html.escape(ann.contents))
            item.setPos(page.pos())
            item.setScale(self._zoom)
            # Restore selection state
            if ann.id == self._selected_annotation_id:
                item.set_selected_highlight(True)
            self._scene.addItem(item)
            self._annotation_items.append((ann.page, item))

    # ------------------------------------------------------------------
    # Annotate tool helpers
    # ------------------------------------------------------------------

    def _cancel_annotate_drawing(self):
        """Abort any in-progress annotation drawing."""
        self._annotate_creating = False
        self._annotate_start = None
        self._annotate_page = -1
        self._annotate_freehand_points = []
        if self._annotate_preview_rect and shiboken6.isValid(self._annotate_preview_rect):
            self._scene.removeItem(self._annotate_preview_rect)
        self._annotate_preview_rect = None
        if self._annotate_freehand_path_item and shiboken6.isValid(self._annotate_freehand_path_item):
            self._scene.removeItem(self._annotate_freehand_path_item)
        self._annotate_freehand_path_item = None

    def _ensure_annotate_preview(self) -> QGraphicsRectItem:
        if self._annotate_preview_rect and shiboken6.isValid(self._annotate_preview_rect):
            return self._annotate_preview_rect
        item = QGraphicsRectItem()
        pen = QPen(QColor(91, 141, 246, 200))
        pen.setWidthF(1.0)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(QBrush(QColor(91, 141, 246, 30)))
        item.setZValue(950)
        self._scene.addItem(item)
        self._annotate_preview_rect = item
        return item

    def _commit_annotate_rect(self, rect: QRectF):
        """Create an AnnotationRecord from a drawn rect and emit annotation_created."""
        from uuid import uuid4
        from neoview.models.view_state import AnnotationRecord
        t = self._annotate_type
        contents = ""
        if t in ("note", "text-box"):
            label = "Note text:" if t == "note" else "Text:"
            text, ok = QInputDialog.getMultiLineText(self, "Add Annotation", label)
            if not ok:
                return
            contents = text

        record = AnnotationRecord(
            id=uuid4().hex,
            type=t,
            page=self._annotate_page,
            rect=(float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height())),
            color=self._annotate_color,
            opacity=self._annotate_opacity,
            contents=contents,
            border_color="",
            border_width=self._annotate_border_width,
            font_size=self._annotate_font_size,
        )
        self.annotation_created.emit(record)

    def _commit_annotate_freehand(self):
        """Commit accumulated freehand points as an annotation."""
        from uuid import uuid4
        from neoview.models.view_state import AnnotationRecord
        pts = self._annotate_freehand_points
        if len(pts) < 2:
            return
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        rx, ry = min(xs), min(ys)
        rw = max(xs) - rx
        rh = max(ys) - ry
        record = AnnotationRecord(
            id=uuid4().hex,
            type="freehand",
            page=self._annotate_page,
            rect=(rx, ry, max(1.0, rw), max(1.0, rh)),
            color=self._annotate_color,
            opacity=self._annotate_opacity,
            border_width=self._annotate_border_width,
            points=list(pts),
        )
        self.annotation_created.emit(record)

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

    def select_all_text_on_page(self, page_idx: int = -1):
        """Select and copy all text on the given page (or current page)."""
        if page_idx < 0:
            page_idx = self.current_page
        if not (0 <= page_idx < len(self._pages)):
            return
        page_item = self._pages[page_idx]
        page_rect = QRectF(0, 0, page_item.page_rect.width(), page_item.page_rect.height())
        text = self.extract_text_in_rect(page_idx, page_rect)
        if text:
            self.clear_text_selection()
            self._highlight_text_in_rect(page_idx, page_rect)
            self.text_selected.emit(text)

    def contextMenuEvent(self, event):
        """Right-click context menu for text operations."""
        scene_pos = self.mapToScene(event.pos())
        page_idx = self._get_page_at(scene_pos)

        # Check if right-click is on an annotation
        if self._selected_annotation_id:
            self._show_annotation_context_menu(self._selected_annotation_id, event.globalPos())
            event.accept()
            return

        menu = QMenu(self)

        # "Copy Text" — enabled when text highlights exist
        has_selection = bool(self._text_highlight_items)
        copy_action = menu.addAction("Copy Text")
        copy_action.setEnabled(has_selection)

        menu.addSeparator()

        # "Select All on Page" — enabled when a page is visible
        select_all_action = menu.addAction("Select All on Page")
        select_all_action.setEnabled(page_idx >= 0 or len(self._pages) > 0)

        chosen = menu.exec(event.globalPos())
        if chosen == copy_action and has_selection:
            # Gather text from highlighted spans
            first_page = self._text_highlight_items[0][0] if self._text_highlight_items else -1
            rects = [
                item.rect() for pi, item in self._text_highlight_items
                if shiboken6.isValid(item)
            ]
            if rects and first_page >= 0:
                union = rects[0]
                for r in rects[1:]:
                    union = union.united(r)
                text = self.extract_text_in_rect(first_page, union)
                if text:
                    QApplication.clipboard().setText(text)
                    self.text_selected.emit(text)
        elif chosen == select_all_action:
            target = page_idx if page_idx >= 0 else self.current_page
            self.select_all_text_on_page(target)

        event.accept()

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

    def _page_height(self, page_idx: int) -> Optional[float]:
        if not (0 <= page_idx < len(self._pages)):
            return None
        page = self._pages[page_idx]
        rect = getattr(page, "page_rect", None)
        if rect is not None:
            height_attr = getattr(rect, "height", None)
            if callable(height_attr):
                try:
                    return float(height_attr())
                except Exception:
                    pass
            if height_attr is not None:
                try:
                    return float(height_attr)
                except Exception:
                    pass
            try:
                return float(rect[3] - rect[1])
            except Exception:
                pass
        fitz_page = getattr(page, "_fitz_page", None)
        if fitz_page is not None:
            try:
                return float(fitz_page.rect.height)
            except Exception:
                pass
        return None

    def _scroll_to_destination(self, page_idx: int, target_y: Optional[float], *, y_is_pdf_coords: bool = False):
        if not isinstance(page_idx, int) or not (0 <= page_idx < self.page_count):
            return
        self.go_to_page(page_idx)
        if target_y is None or not (0 <= page_idx < len(self._pages)):
            return

        y_value = float(target_y)
        if y_is_pdf_coords:
            page_height = self._page_height(page_idx)
            if page_height is not None:
                y_value = page_height - y_value

        if y_value < 0:
            y_value = 0.0
        page_height = self._page_height(page_idx)
        if page_height is not None:
            y_value = min(y_value, page_height)

        page = self._pages[page_idx]
        dest_y = page.pos().y() + y_value * self._zoom - 30
        self.verticalScrollBar().setValue(int(max(0, dest_y)))

    def _parse_dest_string_y(self, dest: str) -> Optional[float]:
        if not isinstance(dest, str):
            return None
        # PDF destination strings commonly look like "/XYZ left top zoom".
        match = re.search(r"/XYZ\s+[-+]?\d*\.?\d+\s+([-+]?\d*\.?\d+)", dest)
        if not match:
            return None
        try:
            return float(match.group(1))
        except (TypeError, ValueError):
            return None

    def _resolve_named_destination(self, name: str) -> Tuple[Optional[int], Optional[float]]:
        if not self._doc:
            return (None, None)
        key = str(name or "").strip()
        if not key:
            return (None, None)
        if key.startswith("#"):
            key = key[1:]
        if key.lower().startswith("nameddest="):
            key = key.split("=", 1)[1]
        key = unquote(key).strip()
        if not key:
            return (None, None)

        try:
            names = self._doc.resolve_names()
        except Exception:
            return (None, None)
        if not isinstance(names, dict):
            return (None, None)

        target = names.get(key)
        if not isinstance(target, dict):
            return (None, None)

        page_idx = target.get("page")
        if not isinstance(page_idx, int) or page_idx < 0:
            return (None, None)

        target_y = self._extract_target_y(target.get("to"))
        if target_y is None:
            target_y = self._parse_dest_string_y(str(target.get("dest", "")))
        return (page_idx, target_y)

    def _resolve_uri_destination(self, uri: str) -> Tuple[Optional[int], Optional[float]]:
        if not self._doc:
            return (None, None)
        try:
            page_id, _x, y = self._doc.resolve_link(uri)
        except Exception:
            return (None, None)
        if isinstance(page_id, int) and 0 <= page_id < self.page_count:
            return (page_id, y)
        return (None, None)

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

        name = str(link.get("nameddest") or link.get("name") or "").strip()
        if name:
            return f"Navigate to destination #{name}"

        page_idx = link.get("page")
        if isinstance(page_idx, int) and page_idx >= 0:
            target_y = self._extract_target_y(link.get("to"))
            if target_y is not None:
                return f"Go to page {page_idx + 1} at y={target_y:.0f}"
            return f"Go to page {page_idx + 1}"

        return "Follow link"

    def _update_link_hover(self, scene_pos: QPointF, viewport_pos: QPoint):
        if self._tool != ToolMode.HAND:
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

        _ALLOWED_URI_SCHEMES = {"http", "https", "mailto"}
        kind = link.get("kind")
        uri = link.get("uri")
        if uri:
            if kind == fitz.LINK_URI and not str(uri).startswith("#"):
                parsed = QUrl(uri)
                if parsed.scheme().lower() in _ALLOWED_URI_SCHEMES:
                    QDesktopServices.openUrl(parsed)
                return
            page_id, y = self._resolve_uri_destination(str(uri))
            if isinstance(page_id, int):
                # resolve_link() already returns coordinates in viewer-space.
                self._scroll_to_destination(page_id, y, y_is_pdf_coords=False)
                return
            if str(uri).startswith("#"):
                page_idx, target_y = self._resolve_named_destination(str(uri))
                if isinstance(page_idx, int):
                    # resolve_names() reports PDF-space Y.
                    self._scroll_to_destination(page_idx, target_y, y_is_pdf_coords=True)
                    return

        if kind == fitz.LINK_NAMED:
            named_key = str(link.get("nameddest") or link.get("name") or "").strip()
            if named_key:
                named_lower = named_key.lower()
                if named_lower == "nextpage":
                    self.next_page()
                    return
                if named_lower == "prevpage":
                    self.prev_page()
                    return
                if named_lower == "firstpage":
                    self.first_page()
                    return
                if named_lower == "lastpage":
                    self.last_page()
                    return

                page_idx, target_y = self._resolve_uri_destination(f"#nameddest={named_key}")
                if isinstance(page_idx, int):
                    self._scroll_to_destination(page_idx, target_y, y_is_pdf_coords=False)
                    return

            page_idx, target_y = self._resolve_named_destination(named_key)
            if isinstance(page_idx, int):
                self._scroll_to_destination(page_idx, target_y, y_is_pdf_coords=True)
                return

        page_idx = link.get("page")
        if isinstance(page_idx, int) and 0 <= page_idx < self.page_count:
            target_y = self._extract_target_y(link.get("to"))
            self._scroll_to_destination(page_idx, target_y, y_is_pdf_coords=False)

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
        scene_pos = self.mapToScene(e.position().toPoint())

        if e.button() == Qt.MouseButton.RightButton:
            ann_id = self._annotation_hit_at_scene_pos(scene_pos)
            if ann_id:
                self._show_annotation_context_menu(ann_id, e.globalPosition().toPoint())
                e.accept()
                return
            super().mousePressEvent(e)
            return

        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            return

        self._clear_link_press()
        self._update_link_hover(scene_pos, e.position().toPoint())

        # In ANNOTATE mode: left-click starts drawing (don't intercept for annotation click)
        if self._tool == ToolMode.ANNOTATE:
            page_idx = self._get_page_at(scene_pos)
            if page_idx >= 0:
                local_pos = self._scene_to_page(scene_pos, page_idx)
                self._annotate_creating = True
                self._annotate_page = page_idx
                self._annotate_start = local_pos
                if self._annotate_type == "freehand":
                    self._annotate_freehand_points = [[local_pos.x(), local_pos.y()]]
                e.accept()
                return
            e.accept()
            return

        ann_id = self._annotation_hit_at_scene_pos(scene_pos)
        if ann_id:
            self.annotation_clicked.emit(ann_id)
            self.select_annotation(ann_id)
            e.accept()
            return

        # Click on empty space deselects annotation
        if self._selected_annotation_id:
            self.select_annotation(None)

        if self._hover_link and self._tool == ToolMode.HAND:
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

        if self._tool == ToolMode.ANNOTATE and self._annotate_creating and self._annotate_page >= 0:
            local_pos = self._scene_to_page(scene_pos, self._annotate_page)
            page = self._pages[self._annotate_page] if 0 <= self._annotate_page < len(self._pages) else None
            if page:
                local_pos = QPointF(
                    max(0, min(local_pos.x(), page.page_rect.width())),
                    max(0, min(local_pos.y(), page.page_rect.height())),
                )
            if self._annotate_type == "freehand":
                if len(self._annotate_freehand_points) < 50_000:
                    self._annotate_freehand_points.append([local_pos.x(), local_pos.y()])
                pts = self._annotate_freehand_points
                if len(pts) >= 2:
                    path = QPainterPath()
                    path.moveTo(QPointF(pts[0][0], pts[0][1]))
                    for pt in pts[1:]:
                        path.lineTo(QPointF(pt[0], pt[1]))
                    if self._annotate_freehand_path_item and shiboken6.isValid(self._annotate_freehand_path_item):
                        self._annotate_freehand_path_item.setPath(path)
                    else:
                        path_item = QGraphicsPathItem(path)
                        pen = QPen(QColor(self._annotate_color))
                        pen.setWidthF(self._annotate_border_width)
                        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                        pen.setCosmetic(True)
                        path_item.setPen(pen)
                        path_item.setBrush(Qt.BrushStyle.NoBrush)
                        path_item.setZValue(950)
                        if page:
                            path_item.setPos(page.pos())
                            path_item.setScale(self._zoom)
                        self._scene.addItem(path_item)
                        self._annotate_freehand_path_item = path_item
            elif self._annotate_start is not None:
                rect = QRectF(self._annotate_start, local_pos).normalized()
                preview = self._ensure_annotate_preview()
                if page:
                    page_pos = page.pos()
                    scene_rect = QRectF(
                        page_pos.x() + rect.x() * self._zoom,
                        page_pos.y() + rect.y() * self._zoom,
                        rect.width() * self._zoom,
                        rect.height() * self._zoom,
                    )
                    preview.setRect(scene_rect)
            e.accept()
            return

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

    def mouseDoubleClickEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(e.position().toPoint())
            ann_id = self._annotation_hit_at_scene_pos(scene_pos)
            if ann_id:
                self.annotation_edit_requested.emit(ann_id)
                e.accept()
                return
        super().mouseDoubleClickEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._tool == ToolMode.ANNOTATE and self._annotate_creating:
                self._annotate_creating = False
                scene_pos = self.mapToScene(e.position().toPoint())
                local_pos = self._scene_to_page(scene_pos, self._annotate_page)
                page = self._pages[self._annotate_page] if 0 <= self._annotate_page < len(self._pages) else None
                if page:
                    local_pos = QPointF(
                        max(0, min(local_pos.x(), page.page_rect.width())),
                        max(0, min(local_pos.y(), page.page_rect.height())),
                    )
                if self._annotate_type == "freehand":
                    self._annotate_freehand_points.append([local_pos.x(), local_pos.y()])
                    if self._annotate_freehand_path_item and shiboken6.isValid(self._annotate_freehand_path_item):
                        self._scene.removeItem(self._annotate_freehand_path_item)
                    self._annotate_freehand_path_item = None
                    self._commit_annotate_freehand()
                    self._annotate_freehand_points = []
                elif self._annotate_start is not None:
                    rect = QRectF(self._annotate_start, local_pos).normalized()
                    if self._annotate_preview_rect and shiboken6.isValid(self._annotate_preview_rect):
                        self._scene.removeItem(self._annotate_preview_rect)
                    self._annotate_preview_rect = None
                    min_size = 3.0
                    if rect.width() >= min_size or rect.height() >= min_size:
                        self._commit_annotate_rect(rect)
                self._annotate_start = None
                self._annotate_page = -1
                e.accept()
                return

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
        key = e.key()
        mods = e.modifiers()

        # Ctrl+C — copy active text selection to clipboard
        if key == Qt.Key.Key_C and mods & Qt.KeyboardModifier.ControlModifier:
            if self._text_highlight_items:
                # Re-extract text from the highlighted region
                for page_idx, item in self._text_highlight_items:
                    break  # just need the page_idx
                # Gather bounding box of all highlights on that page
                rects = [
                    item.rect() for pi, item in self._text_highlight_items
                    if shiboken6.isValid(item)
                ]
                if rects:
                    union = rects[0]
                    for r in rects[1:]:
                        union = union.united(r)
                    text = self.extract_text_in_rect(page_idx, union)
                    if text:
                        QApplication.clipboard().setText(text)
                        self.text_selected.emit(text)
                        e.accept()
                        return
            super().keyPressEvent(e)
            return

        # Ctrl+A — select all text on the current page
        if key == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
            self.select_all_text_on_page()
            e.accept()
            return

        # Delete/Backspace removes selected annotation
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._selected_annotation_id:
                ann_id = self._selected_annotation_id
                self.select_annotation(None)
                self.annotation_deleted.emit(ann_id)
                e.accept()
                return

        # Escape cancels annotate drawing or deselects
        if key == Qt.Key.Key_Escape:
            if self._tool == ToolMode.ANNOTATE and self._annotate_creating:
                self._cancel_annotate_drawing()
                e.accept()
                return
            if self._selected_annotation_id:
                self.select_annotation(None)
                e.accept()
                return

        if self._selection:
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

    def _show_annotation_context_menu(self, ann_id: str, global_pos):
        ann = self._annotation_index.get(ann_id)
        if ann is None:
            return
        self.select_annotation(ann_id)
        menu = QMenu(self)
        edit_action = menu.addAction("Edit / Properties")
        menu.addSeparator()
        delete_action = menu.addAction("Delete Annotation")
        chosen = menu.exec(global_pos)
        if chosen == edit_action:
            self.annotation_edit_requested.emit(ann_id)
        elif chosen == delete_action:
            self.select_annotation(None)
            self.annotation_deleted.emit(ann_id)

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
