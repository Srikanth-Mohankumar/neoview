#!/usr/bin/env python3
"""
PDF Viewer with Measure Tool
============================
A complete PDF viewer with measurement capabilities for Linux/GNOME.

FEATURES
--------
- Full PDF viewing with continuous page scrolling
- Three tool modes: Select (pointer), Hand (pan), Measure (rectangle)
- Auto-reload on file change (always enabled, perfect for LaTeX)
- High-quality rendering
- Keyboard shortcuts for all actions

KEYBOARD SHORTCUTS
------------------
Ctrl+O          Open PDF file
Ctrl+Q          Exit
Ctrl+C          Copy measurements
Ctrl+S          Export selection as PNG
PgUp/PgDn       Previous/Next page
Home/End        First/Last page
Ctrl+Wheel      Zoom in/out
1               Select tool (pointer)
2               Hand tool (pan)  
3               Measure tool
W               Fit width
F               Fit page
Arrow           Move selection 1pt (Shift=10pt)
Ctrl+Arrow      Resize selection
Escape          Clear selection
F5              Force reload

DEPENDENCIES
------------
- Python 3.10+
- PySide6
- PyMuPDF (fitz)

CONTAINER RUN (X11)
-------------------
xhost +local:docker
docker run -it --rm -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v /path/to/pdfs:/pdfs pdf-viewer /pdfs/document.pdf
"""

import sys
import os
from typing import Optional, List
from enum import Enum, auto
from pathlib import Path

import fitz  # PyMuPDF

from PySide6.QtCore import (
    Qt, QRectF, QPointF, QTimer, Signal, QFileSystemWatcher, QSize
)
from PySide6.QtGui import (
    QPixmap, QImage, QPainter, QPen, QBrush, QColor, QCursor,
    QAction, QKeySequence, QWheelEvent, QKeyEvent, QMouseEvent,
    QActionGroup
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QGraphicsView, QGraphicsScene,
    QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsItem,
    QFileDialog, QStatusBar, QToolBar, QLabel, QWidget,
    QMessageBox, QDialog, QVBoxLayout, QHBoxLayout,
    QComboBox, QPushButton, QScrollArea, QSizePolicy
)


# =============================================================================
# Dark Theme
# =============================================================================

DARK_STYLE = """
QMainWindow { background-color: #1e1e1e; }
QMenuBar { background-color: #2d2d2d; color: #e0e0e0; border-bottom: 1px solid #404040; padding: 2px; }
QMenuBar::item { padding: 4px 10px; border-radius: 3px; }
QMenuBar::item:selected { background-color: #0078d4; }
QMenu { background-color: #2d2d2d; color: #e0e0e0; border: 1px solid #404040; padding: 4px; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background-color: #0078d4; }
QMenu::separator { height: 1px; background: #404040; margin: 4px 8px; }
QToolBar { background-color: #252526; border: none; border-bottom: 1px solid #404040; spacing: 2px; padding: 4px; }
QToolBar::separator { width: 1px; background: #404040; margin: 2px 6px; }
QToolButton { background-color: #3c3c3c; color: #e0e0e0; border: 1px solid #4a4a4a; border-radius: 4px; padding: 6px 10px; font-size: 12px; min-width: 50px; }
QToolButton:hover { background-color: #4a4a4a; }
QToolButton:pressed, QToolButton:checked { background-color: #0078d4; border-color: #0078d4; }
QStatusBar { background-color: #007acc; color: white; font-size: 11px; }
QStatusBar QLabel { color: white; padding: 0 8px; }
QGraphicsView { background-color: #404040; border: none; }
QScrollBar:vertical { background: #2d2d2d; width: 10px; }
QScrollBar::handle:vertical { background: #5a5a5a; border-radius: 5px; min-height: 20px; }
QScrollBar::handle:vertical:hover { background: #6a6a6a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #2d2d2d; height: 10px; }
QScrollBar::handle:horizontal { background: #5a5a5a; border-radius: 5px; min-width: 20px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QDialog { background-color: #2d2d2d; color: #e0e0e0; }
QLabel { color: #e0e0e0; }
QComboBox { background-color: #3c3c3c; color: #e0e0e0; border: 1px solid #4a4a4a; border-radius: 4px; padding: 6px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView { background-color: #2d2d2d; color: #e0e0e0; selection-background-color: #0078d4; }
QPushButton { background-color: #0078d4; color: white; border: none; border-radius: 4px; padding: 8px 16px; font-weight: 500; }
QPushButton:hover { background-color: #1a88e0; }
QPushButton[secondary="true"] { background-color: #3c3c3c; border: 1px solid #4a4a4a; }
"""


# =============================================================================
# Tool Mode Enum
# =============================================================================

class ToolMode(Enum):
    SELECT = auto()   # Normal pointer cursor
    HAND = auto()     # Hand tool for panning
    MEASURE = auto()  # Rectangle measure tool


# =============================================================================
# Unit Conversion
# =============================================================================

def pt_to_mm(pt: float) -> float:
    return pt * 25.4 / 72.0

def pt_to_pica(pt: float) -> float:
    return pt / 12.0

def format_size(w: float, h: float) -> str:
    return f"W: {w:.1f}pt ({pt_to_mm(w):.2f}mm)  H: {h:.1f}pt ({pt_to_mm(h):.2f}mm)"


# =============================================================================
# Selection Rectangle
# =============================================================================

class SelectionRect(QGraphicsRectItem):
    """Measurement rectangle with thin border and resize handles."""
    
    HANDLE_SIZE = 5
    MIN_SIZE = 3
    
    def __init__(self, rect: QRectF, page_rect: QRectF, parent=None):
        super().__init__(parent)
        self._rect = rect.normalized()
        self._page_rect = page_rect
        
        # Thin 1px border
        self.setPen(QPen(QColor(0, 150, 255), 1))
        self.setBrush(QBrush(QColor(0, 150, 255, 25)))
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
        
        def near(a, b): return abs(a - b) < s
        
        on_left = near(pos.x(), r.left())
        on_right = near(pos.x(), r.right())
        on_top = near(pos.y(), r.top())
        on_bottom = near(pos.y(), r.bottom())
        
        if on_top and on_left: return 'tl'
        if on_top and on_right: return 'tr'
        if on_bottom and on_left: return 'bl'
        if on_bottom and on_right: return 'br'
        if on_top: return 't'
        if on_bottom: return 'b'
        if on_left: return 'l'
        if on_right: return 'r'
        if r.contains(pos): return 'move'
        return ''
    
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
        
        if m == 'move':
            r.translate(d)
        else:
            if 'l' in m: r.setLeft(r.left() + d.x())
            if 'r' in m: r.setRight(r.right() + d.x())
            if 't' in m: r.setTop(r.top() + d.y())
            if 'b' in m: r.setBottom(r.bottom() + d.y())
        
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
            'tl': Qt.CursorShape.SizeFDiagCursor,
            'br': Qt.CursorShape.SizeFDiagCursor,
            'tr': Qt.CursorShape.SizeBDiagCursor,
            'bl': Qt.CursorShape.SizeBDiagCursor,
            't': Qt.CursorShape.SizeVerCursor,
            'b': Qt.CursorShape.SizeVerCursor,
            'l': Qt.CursorShape.SizeHorCursor,
            'r': Qt.CursorShape.SizeHorCursor,
            'move': Qt.CursorShape.SizeAllCursor,
        }
        return cursors.get(mode, Qt.CursorShape.ArrowCursor)


# =============================================================================
# PDF Page Item (renders one page)
# =============================================================================

class PageItem(QGraphicsPixmapItem):
    """A single PDF page rendered at optimized quality."""
    
    # Rendering quality: 1.5x is good balance of quality vs performance
    RENDER_SCALE = 1.5
    
    def __init__(self, page: fitz.Page, scale: float, page_index: int):
        super().__init__()
        self.page_index = page_index
        self.page_rect = QRectF(0, 0, page.rect.width, page.rect.height)
        self._fitz_page = page  # Keep reference for text extraction
        self._render(page, scale)
    
    def _render(self, page: fitz.Page, scale: float):
        # Render at 1.5x for balance of quality and performance
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
            # Get text blocks with detailed info
            blocks = self._fitz_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            
            for block in blocks:
                if block.get("type") != 0:  # Only text blocks
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
                                "text": span.get("text", "")[:50],  # First 50 chars
                            }
        except Exception:
            pass
        return None


# =============================================================================
# PDF View (main viewer)
# =============================================================================

class PdfView(QGraphicsView):
    """Full-featured PDF viewer with tools."""
    
    selection_changed = Signal()
    zoom_changed = Signal(float)
    page_changed = Signal(int, int)  # current_page, total_pages
    text_info_changed = Signal(str)  # font info display
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Gestures
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.grabGesture(Qt.GestureType.PinchGesture)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        
        # View settings
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QBrush(QColor(64, 64, 64)))
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        
        # State
        self._doc: Optional[fitz.Document] = None
        self._doc_path: Optional[str] = None
        self._pages: List[PageItem] = []
        self._page_positions: List[float] = []  # Y position of each page
        self._zoom: float = 1.0
        self._tool: ToolMode = ToolMode.HAND
        
        # Selection
        self._selection: Optional[SelectionRect] = None
        self._selection_page: int = -1
        self._creating: bool = False
        self._create_start: Optional[QPointF] = None
        self._interacting: bool = False
        
        # Panning
        self._panning: bool = False
        self._pan_start: Optional[QPointF] = None
        
        # Pinch zoom
        self._pinch_start_zoom: float = 1.0
        
        # Scroll tracking for page number
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
        self._update_cursor()
    
    @property
    def page_count(self) -> int:
        return self._doc.page_count if self._doc else 0
    
    @property
    def current_page(self) -> int:
        """Get current visible page based on scroll position."""
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
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot open PDF:\n{e}")
            return False
    
    def reload_document(self) -> bool:
        """Reload current document with smooth transition (no black flash)."""
        if not self._doc_path:
            return False
        
        scroll_pos = self.verticalScrollBar().value()
        sel_rect = self.selection_rect
        sel_page = self._selection_page
        
        try:
            # Open new document first (keep old visible)
            new_doc = fitz.open(self._doc_path)
            
            # Render new pages to temporary list
            new_pages = []
            gap = 20
            y = gap
            
            for i in range(new_doc.page_count):
                page = new_doc.load_page(i)
                item = PageItem(page, self._zoom, i)
                item.setPos(0, y)
                new_pages.append((item, y))
                y += item.page_rect.height() * self._zoom + gap
            
            # NOW swap: close old doc and clear scene
            if self._doc:
                self._doc.close()
            self._doc = new_doc
            
            # Clear and add new pages
            self._scene.clear()
            self._pages.clear()
            self._page_positions.clear()
            self._selection = None
            
            for item, pos_y in new_pages:
                self._scene.addItem(item)
                self._pages.append(item)
                self._page_positions.append(pos_y)
            
            # Center pages
            if self._pages:
                max_width = max(p.page_rect.width() for p in self._pages) * self._zoom
                for p in self._pages:
                    offset = (max_width - p.page_rect.width() * self._zoom) / 2
                    p.setPos(offset, p.pos().y())
            
            # Update scene rect
            max_width = max((p.page_rect.width() for p in self._pages), default=600) * self._zoom
            self._scene.setSceneRect(0, 0, max_width, y)
            
            # Restore scroll
            self.verticalScrollBar().setValue(scroll_pos)
            
            # Restore selection
            if sel_rect and 0 <= sel_page < self.page_count:
                self._create_selection_on_page(sel_page, sel_rect)
            
            self._emit_page_info()
            return True
        except Exception as e:
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
    
    def _render_all_pages(self):
        """Render all pages in a continuous vertical layout."""
        self._scene.clear()
        self._pages.clear()
        self._page_positions.clear()
        self._selection = None
        
        if not self._doc:
            return
        
        gap = 20  # Gap between pages
        y = gap
        
        for i in range(self._doc.page_count):
            page = self._doc.load_page(i)
            item = PageItem(page, self._zoom, i)
            item.setPos(0, y)
            self._scene.addItem(item)
            self._pages.append(item)
            self._page_positions.append(y)
            y += item.page_rect.height() * self._zoom + gap
        
        # Center pages
        if self._pages:
            max_width = max(p.page_rect.width() for p in self._pages) * self._zoom
            for p in self._pages:
                offset = (max_width - p.page_rect.width() * self._zoom) / 2
                p.setPos(offset, p.pos().y())
        
        # Update scene rect
        total_height = y
        max_width = max((p.page_rect.width() for p in self._pages), default=600) * self._zoom
        self._scene.setSceneRect(0, 0, max_width, total_height)
        
        self._emit_page_info()
    
    def _emit_page_info(self):
        self.page_changed.emit(self.current_page + 1, self.page_count)
    
    def _on_scroll(self):
        self._emit_page_info()
    
    def set_zoom(self, z: float):
        z = max(0.25, min(z, 5.0))
        if abs(z - self._zoom) < 0.01:
            return
        self._zoom = z
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
        """Scroll to page (0-indexed)."""
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
            self._scene.removeItem(self._selection)
            self._selection = None
            self._selection_page = -1
            self.selection_changed.emit()
    
    def clear_selection(self):
        self._clear_selection()
    
    def _get_page_at(self, scene_pos: QPointF) -> int:
        """Get page index at scene position."""
        for i, page in enumerate(self._pages):
            rect = QRectF(page.pos(), page.page_rect.size() * self._zoom)
            if rect.contains(scene_pos):
                return i
        return -1
    
    def _scene_to_page(self, scene_pos: QPointF, page_idx: int) -> QPointF:
        """Convert scene coordinates to page coordinates."""
        if 0 <= page_idx < len(self._pages):
            page = self._pages[page_idx]
            local = scene_pos - page.pos()
            return QPointF(local.x() / self._zoom, local.y() / self._zoom)
        return QPointF()
    
    def _create_selection_on_page(self, page_idx: int, rect: QRectF):
        """Create selection on a specific page."""
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
    
    # -------------------------------------------------------------------------
    # Mouse Events
    # -------------------------------------------------------------------------
    
    def mousePressEvent(self, e: QMouseEvent):
        if e.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(e)
            return
        
        scene_pos = self.mapToScene(e.position().toPoint())
        
        # Hand tool = panning
        if self._tool == ToolMode.HAND:
            super().mousePressEvent(e)
            return
        
        # Select tool = inspect text (font info)
        if self._tool == ToolMode.SELECT:
            page_idx = self._get_page_at(scene_pos)
            if page_idx >= 0:
                page_pos = self._scene_to_page(scene_pos, page_idx)
                page_item = self._pages[page_idx]
                info = page_item.get_text_info_at(page_pos)
                if info:
                    text_info = f"Font: {info['font']} | Size: {info['size']:.1f}pt"
                    self.text_info_changed.emit(text_info)
                else:
                    self.text_info_changed.emit("")
            e.accept()
            return
        
        # Measure tool
        if self._tool == ToolMode.MEASURE:
            # Check if clicking on existing selection
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
            
            # Start new selection
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
        
        # Measure tool interaction
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
                    # Clamp to page
                    local_pos = QPointF(
                        max(0, min(local_pos.x(), page.page_rect.width())),
                        max(0, min(local_pos.y(), page.page_rect.height()))
                    )
                    rect = QRectF(self._create_start, local_pos).normalized()
                    
                    if not self._selection:
                        self._create_selection_on_page(page_idx, rect)
                    else:
                        self._selection.pdf_rect = rect
                    
                    self.selection_changed.emit()
                e.accept()
                return
            
            # Update cursor based on hover
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
            if self._interacting and self._selection:
                self._selection.end_drag()
                self._interacting = False
            
            if self._creating:
                self._creating = False
                self._create_start = None
                # Remove tiny selections
                if self._selection and (
                    self._selection.pdf_rect.width() < SelectionRect.MIN_SIZE or
                    self._selection.pdf_rect.height() < SelectionRect.MIN_SIZE
                ):
                    self._clear_selection()
        
        super().mouseReleaseEvent(e)
    
    def wheelEvent(self, e: QWheelEvent):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = e.angleDelta().y()
            if delta != 0:
                self.zoom_by(1.1 if delta > 0 else 1/1.1)
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
                if resize: self._selection.resize_by(-step, 0)
                else: self._selection.nudge(-step, 0)
                self.selection_changed.emit()
                e.accept()
                return
            elif key == Qt.Key.Key_Right:
                if resize: self._selection.resize_by(step, 0)
                else: self._selection.nudge(step, 0)
                self.selection_changed.emit()
                e.accept()
                return
            elif key == Qt.Key.Key_Up:
                if resize: self._selection.resize_by(0, -step)
                else: self._selection.nudge(0, -step)
                self.selection_changed.emit()
                e.accept()
                return
            elif key == Qt.Key.Key_Down:
                if resize: self._selection.resize_by(0, step)
                else: self._selection.nudge(0, step)
                self.selection_changed.emit()
                e.accept()
                return
            elif key == Qt.Key.Key_Escape:
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


# =============================================================================
# Export Dialog
# =============================================================================

class ExportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Selection")
        self.setFixedWidth(280)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        row = QHBoxLayout()
        row.addWidget(QLabel("DPI:"))
        self.dpi = QComboBox()
        self.dpi.addItems(["150", "300", "600"])
        self.dpi.setCurrentIndex(1)
        row.addWidget(self.dpi)
        row.addStretch()
        layout.addLayout(row)
        
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.setProperty("secondary", True)
        cancel.clicked.connect(self.reject)
        export = QPushButton("Export")
        export.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(cancel)
        btns.addWidget(export)
        layout.addLayout(btns)
    
    @property
    def selected_dpi(self) -> int:
        return int(self.dpi.currentText())


# =============================================================================
# Main Window
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self, pdf_path: Optional[str] = None):
        super().__init__()
        
        self.setWindowTitle("PDF Viewer")
        self.resize(1200, 900)
        
        self._current_file: Optional[str] = None
        self._last_mtime: float = 0
        
        # Auto-reload is ALWAYS ENABLED
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)
        
        # Reload timer (debounce)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self._do_reload)
        
        # Polling timer (every 500ms for aggressive LaTeX detection)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_check)
        self._poll_timer.start(500)
        
        self._setup_ui()
        
        if pdf_path:
            self._open_file(pdf_path)
    
    def _setup_ui(self):
        self._view = PdfView(self)
        self.setCentralWidget(self._view)
        
        self._view.selection_changed.connect(self._update_status)
        self._view.zoom_changed.connect(self._update_status)
        self._view.page_changed.connect(self._on_page_changed)
        self._view.text_info_changed.connect(self._on_text_info)
        
        self._setup_menus()
        self._setup_toolbar()
        self._setup_statusbar()
    
    def _setup_menus(self):
        # File
        file_m = self.menuBar().addMenu("&File")
        file_m.addAction(self._action("&Open...", self._open_dialog, QKeySequence.StandardKey.Open))
        file_m.addAction(self._action("&Reload", self._force_reload, "F5"))
        file_m.addSeparator()
        file_m.addAction(self._action("&Export Selection...", self._export, QKeySequence.StandardKey.Save))
        file_m.addSeparator()
        file_m.addAction(self._action("E&xit", self.close, QKeySequence.StandardKey.Quit))
        
        # Edit
        edit_m = self.menuBar().addMenu("&Edit")
        edit_m.addAction(self._action("&Copy Measurements", self._copy, QKeySequence.StandardKey.Copy))
        edit_m.addAction(self._action("C&lear Selection", self._view.clear_selection, "Escape"))
        
        # View
        view_m = self.menuBar().addMenu("&View")
        view_m.addAction(self._action("Zoom &In", lambda: self._view.zoom_by(1.25), QKeySequence.StandardKey.ZoomIn))
        view_m.addAction(self._action("Zoom &Out", lambda: self._view.zoom_by(0.8), QKeySequence.StandardKey.ZoomOut))
        view_m.addSeparator()
        view_m.addAction(self._action("Fit &Width", self._view.fit_width, "W"))
        view_m.addAction(self._action("Fit &Page", self._view.fit_page, "F"))
        
        # Go
        go_m = self.menuBar().addMenu("&Go")
        go_m.addAction(self._action("&Previous Page", self._view.prev_page, "PgUp"))
        go_m.addAction(self._action("&Next Page", self._view.next_page, "PgDown"))
        go_m.addAction(self._action("&First Page", self._view.first_page, "Home"))
        go_m.addAction(self._action("&Last Page", self._view.last_page, "End"))
        
        # Tools
        tools_m = self.menuBar().addMenu("&Tools")
        self._tool_group = QActionGroup(self)
        
        select_a = self._action("&Select", lambda: self._set_tool(ToolMode.SELECT), "1")
        select_a.setCheckable(True)
        self._tool_group.addAction(select_a)
        tools_m.addAction(select_a)
        
        hand_a = self._action("&Hand", lambda: self._set_tool(ToolMode.HAND), "2")
        hand_a.setCheckable(True)
        hand_a.setChecked(True)
        self._tool_group.addAction(hand_a)
        tools_m.addAction(hand_a)
        
        measure_a = self._action("&Measure", lambda: self._set_tool(ToolMode.MEASURE), "3")
        measure_a.setCheckable(True)
        self._tool_group.addAction(measure_a)
        tools_m.addAction(measure_a)
    
    def _setup_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        
        tb.addAction(self._action("📂 Open", self._open_dialog))
        tb.addSeparator()
        
        tb.addAction(self._action("◀", self._view.prev_page))
        tb.addAction(self._action("▶", self._view.next_page))
        tb.addSeparator()
        
        tb.addAction(self._action("➖", lambda: self._view.zoom_by(0.8)))
        tb.addAction(self._action("➕", lambda: self._view.zoom_by(1.25)))
        tb.addAction(self._action("Fit", self._view.fit_width))
        tb.addSeparator()
        
        # Tool buttons
        self._select_btn = self._action("☝ Select", lambda: self._set_tool(ToolMode.SELECT))
        self._select_btn.setCheckable(True)
        tb.addAction(self._select_btn)
        
        self._hand_btn = self._action("✋ Hand", lambda: self._set_tool(ToolMode.HAND))
        self._hand_btn.setCheckable(True)
        self._hand_btn.setChecked(True)
        tb.addAction(self._hand_btn)
        
        self._measure_btn = self._action("📐 Measure", lambda: self._set_tool(ToolMode.MEASURE))
        self._measure_btn.setCheckable(True)
        tb.addAction(self._measure_btn)
        
        tb.addSeparator()
        tb.addAction(self._action("📋 Copy", self._copy))
        tb.addAction(self._action("💾 Export", self._export))
    
    def _action(self, text: str, slot, shortcut=None) -> QAction:
        a = QAction(text, self)
        a.triggered.connect(slot)
        if shortcut:
            a.setShortcut(shortcut)
        return a
    
    def _set_tool(self, t: ToolMode):
        self._view.tool = t
        self._select_btn.setChecked(t == ToolMode.SELECT)
        self._hand_btn.setChecked(t == ToolMode.HAND)
        self._measure_btn.setChecked(t == ToolMode.MEASURE)
        self._update_status()
    
    def _setup_statusbar(self):
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        
        self._file_lbl = QLabel("No file")
        self._page_lbl = QLabel("")
        self._zoom_lbl = QLabel("")
        self._tool_lbl = QLabel("")
        self._font_lbl = QLabel("")  # Font info (Select tool)
        self._size_lbl = QLabel("")  # Measurements (Measure tool)
        
        self._status.addWidget(self._file_lbl)
        self._status.addWidget(self._page_lbl)
        self._status.addWidget(self._zoom_lbl)
        self._status.addWidget(self._tool_lbl)
        self._status.addWidget(self._font_lbl)
        self._status.addPermanentWidget(self._size_lbl)
    
    def _on_page_changed(self, current: int, total: int):
        self._page_lbl.setText(f"Page {current}/{total}")
    
    def _on_text_info(self, info: str):
        """Display font info when Select tool clicks on text."""
        if info:
            self._font_lbl.setText(f"🔤 {info}")
        else:
            self._font_lbl.setText("")
    
    def _update_status(self):
        if self._view.document:
            name = os.path.basename(self._current_file) if self._current_file else "Untitled"
            self._file_lbl.setText(f"📄 {name}")
            self._zoom_lbl.setText(f"🔍 {self._view.zoom * 100:.0f}%")
            
            tool_names = {ToolMode.SELECT: "Select", ToolMode.HAND: "Hand", ToolMode.MEASURE: "Measure"}
            self._tool_lbl.setText(f"🛠 {tool_names[self._view.tool]}")
            
            sel = self._view.selection_rect
            if sel:
                self._size_lbl.setText(f"📐 {format_size(sel.width(), sel.height())}")
            else:
                self._size_lbl.setText("")
        else:
            self._file_lbl.setText("No file")
            self._page_lbl.setText("")
            self._zoom_lbl.setText("")
            self._tool_lbl.setText("")
            self._size_lbl.setText("")
    
    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf);;All (*)")
        if path:
            self._open_file(path)
    
    def _open_file(self, path: str):
        # Stop watching old
        self._stop_watch()
        
        if self._view.open_document(path):
            self._current_file = os.path.abspath(path)
            self.setWindowTitle(f"PDF Viewer — {os.path.basename(path)}")
            self._view.fit_width()
            self._update_status()
            self._update_mtime()
            self._start_watch()
    
    def _stop_watch(self):
        if self._current_file:
            for f in self._watcher.files():
                self._watcher.removePath(f)
            for d in self._watcher.directories():
                self._watcher.removePath(d)
    
    def _start_watch(self):
        if self._current_file:
            self._watcher.addPath(self._current_file)
            self._watcher.addPath(os.path.dirname(self._current_file))
    
    def _update_mtime(self):
        try:
            if self._current_file and os.path.exists(self._current_file):
                self._last_mtime = os.path.getmtime(self._current_file)
        except OSError:
            pass
    
    def _on_change(self, path: str):
        self._reload_timer.start(200)
    
    def _poll_check(self):
        """Aggressive polling for LaTeX workflows."""
        if not self._current_file:
            return
        try:
            if os.path.exists(self._current_file):
                mtime = os.path.getmtime(self._current_file)
                if mtime != self._last_mtime:
                    self._reload_timer.start(200)
        except OSError:
            pass
    
    def _do_reload(self):
        if not self._current_file or not os.path.exists(self._current_file):
            return
        try:
            size = os.path.getsize(self._current_file)
            if size == 0:
                return
        except OSError:
            return
        
        if self._view.reload_document():
            self._update_mtime()
            self._status.showMessage("✓ Reloaded", 1000)
            # Re-add to watcher
            if self._current_file not in self._watcher.files():
                self._watcher.addPath(self._current_file)
    
    def _force_reload(self):
        self._do_reload()
    
    def _copy(self):
        sel = self._view.selection_rect
        if not sel:
            self._status.showMessage("No selection", 2000)
            return
        QApplication.clipboard().setText(format_size(sel.width(), sel.height()))
        self._status.showMessage("✓ Copied", 1500)
    
    def _export(self):
        sel = self._view.selection_rect
        if not sel:
            QMessageBox.information(self, "Export", "No selection. Use Measure tool to select an area.")
            return
        
        dlg = ExportDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        
        path, _ = QFileDialog.getSaveFileName(self, "Save PNG", "selection.png", "PNG (*.png)")
        if not path:
            return
        
        try:
            page_idx = self._view._selection_page
            if page_idx < 0:
                return
            page = self._view.document.load_page(page_idx)
            clip = fitz.Rect(sel.x(), sel.y(), sel.right(), sel.bottom())
            scale = dlg.selected_dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
            pix.save(path)
            self._status.showMessage(f"✓ Saved {os.path.basename(path)}", 2000)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))
    
    def closeEvent(self, e):
        self._view.close_document()
        super().closeEvent(e)


# =============================================================================
# Main
# =============================================================================

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Viewer")
    app.setStyleSheet(DARK_STYLE)
    
    pdf = None
    if len(sys.argv) > 1:
        pdf = sys.argv[1]
        if not os.path.isfile(pdf):
            print(f"Error: {pdf} not found")
            sys.exit(1)
    
    win = MainWindow(pdf)
    win.show()
    
    if not pdf:
        win._open_dialog()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
