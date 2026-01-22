"""PDF viewer widget and interaction logic."""

from __future__ import annotations

import os
from enum import Enum, auto
from typing import Optional, List

import fitz
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, Signal
from PySide6.QtGui import QPainter, QPen, QBrush, QColor, QWheelEvent, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QMessageBox
import shiboken6

from neoview.ui.selection import SelectionRect
from neoview.ui.page_item import PageItem


class ToolMode(Enum):
    SELECT = auto()
    HAND = auto()
    MEASURE = auto()


class PdfView(QGraphicsView):
    """Full-featured PDF viewer with tools."""

    selection_changed = Signal()
    zoom_changed = Signal(float)
    page_changed = Signal(int, int)
    text_info_changed = Signal(str)
    text_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.grabGesture(Qt.GestureType.PinchGesture)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QBrush(QColor(64, 64, 64)))
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._doc: Optional[fitz.Document] = None
        self._doc_path: Optional[str] = None
        self._pages: List[PageItem] = []
        self._page_positions: List[float] = []
        self._zoom: float = 1.0
        self._render_zoom: float = self._zoom
        self._tool: ToolMode = ToolMode.HAND

        self._rerender_timer = QTimer(self)
        self._rerender_timer.setSingleShot(True)
        self._rerender_timer.timeout.connect(self._rerender_pages)

        self._text_selecting = False
        self._text_select_start: Optional[QPointF] = None
        self._text_select_page: int = -1
        self._text_select_item: Optional[QGraphicsRectItem] = None

        self._search_highlights: List[tuple] = []
        self._search_items: List[QGraphicsRectItem] = []

        self._selection: Optional[SelectionRect] = None
        self._selection_page: int = -1
        self._creating = False
        self._create_start: Optional[QPointF] = None
        self._interacting = False

        self._panning = False
        self._pan_start: Optional[QPointF] = None

        self._pinch_start_zoom: float = 1.0

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

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

    def _update_cursor(self):
        if self._tool == ToolMode.SELECT:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        elif self._tool == ToolMode.HAND:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
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
            self._selection = None
            self.clear_text_selection()
            self._clear_search_items()

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

            self._render_zoom = self._zoom
            self._rebuild_search_highlights()
            self._emit_page_info()
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
        self._selection = None
        self.clear_text_selection()
        self._clear_search_items()

    def _render_all_pages(self):
        self._scene.clear()
        self._pages.clear()
        self._page_positions.clear()
        self._selection = None
        self.clear_text_selection()
        self._clear_search_items()

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

        self._render_zoom = self._zoom
        self._rebuild_search_highlights()
        self._emit_page_info()

    def _layout_pages(self):
        if not self._pages:
            self._scene.setSceneRect(0, 0, 600, 0)
            return

        gap = 20
        y = gap
        scale_factor = self._zoom / self._render_zoom if self._render_zoom else 1.0

        for p in self._pages:
            p.setScale(scale_factor / PageItem.RENDER_SCALE)
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

        self._rebuild_search_highlights()

    def _rerender_pages(self):
        if not self._doc:
            return

        scroll_pos = self.verticalScrollBar().value()
        self._render_all_pages()
        self.verticalScrollBar().setValue(scroll_pos)

    def _emit_page_info(self):
        self.page_changed.emit(self.current_page + 1, self.page_count)

    def _on_scroll(self):
        self._emit_page_info()

    def set_zoom(self, z: float):
        z = max(0.25, min(z, 5.0))
        if abs(z - self._zoom) < 0.01:
            return
        self._zoom = z
        if self._pages:
            self._layout_pages()
            self._rerender_timer.start(150)
        else:
            self._render_all_pages()
        self.zoom_changed.emit(z)

    def zoom_by(self, factor: float):
        self.set_zoom(self._zoom * factor)

    def fit_width(self):
        if not self._pages:
            return
        page_width = self._pages[0].page_rect.width()
        view_width = self.viewport().width() - 40
        self.set_zoom(view_width / page_width)

    def fit_page(self):
        if not self._pages:
            return
        page = self._pages[0].page_rect
        view_w = self.viewport().width() - 40
        view_h = self.viewport().height() - 40
        scale_w = view_w / page.width()
        scale_h = view_h / page.height()
        self.set_zoom(min(scale_w, scale_h))

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
            self.selection_changed.emit()

    def clear_selection(self):
        self._clear_selection()

    def clear_text_selection(self):
        if self._text_select_item and shiboken6.isValid(self._text_select_item):
            self._scene.removeItem(self._text_select_item)
        self._text_select_item = None
        self._text_select_page = -1
        self._text_select_start = None

    def clear_all_selection(self):
        self._clear_selection()
        self.clear_text_selection()

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
        self.selection_changed.emit()

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            return

        scene_pos = self.mapToScene(e.position().toPoint())

        if self._tool == ToolMode.HAND:
            super().mousePressEvent(e)
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
                pen = QPen(QColor(0, 0, 0, 180))
                pen.setWidthF(0.5)
                pen.setStyle(Qt.PenStyle.DotLine)
                pen.setCosmetic(True)
                self._text_select_item.setPen(pen)
                self._text_select_item.setBrush(QBrush(QColor(0, 0, 0, 25)))
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
                                self.text_info_changed.emit(text_info)
                            else:
                                self.text_info_changed.emit("")
                        self.clear_text_selection()
                    else:
                        text = self.extract_text_in_rect(self._text_select_page, rect)
                        self.text_selected.emit(text)
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
            if delta != 0:
                self.zoom_by(1.1 if delta > 0 else 1 / 1.1)
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
                self.selection_changed.emit()
                e.accept()
                return
            if key == Qt.Key.Key_Right:
                if resize:
                    self._selection.resize_by(step, 0)
                else:
                    self._selection.nudge(step, 0)
                self.selection_changed.emit()
                e.accept()
                return
            if key == Qt.Key.Key_Up:
                if resize:
                    self._selection.resize_by(0, -step)
                else:
                    self._selection.nudge(0, -step)
                self.selection_changed.emit()
                e.accept()
                return
            if key == Qt.Key.Key_Down:
                if resize:
                    self._selection.resize_by(0, step)
                else:
                    self._selection.nudge(0, step)
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
                        self.set_zoom(self._pinch_start_zoom * total)
                return True
        return super().event(e)
