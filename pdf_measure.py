import sys
import math
import fitz  # PyMuPDF

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPixmap, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFileDialog, QScrollArea, QWidget
)


def pt_to_mm(pt: float) -> float:
    return pt * 25.4 / 72.0


def pt_to_pica(pt: float) -> float:
    return pt / 12.0


class PdfView(QWidget):
    """
    - Renders a single PDF page using PyMuPDF at current zoom scale.
    - Drag to select a rectangle; shows W/H in pt/pica/mm.
    - Zoom via:
        * pinch gesture (if available)
        * two-finger scroll (wheel) as fallback
    """
    def __init__(self, pdf_path: str, page_index: int = 0):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self.grabGesture(Qt.GestureType.PinchGesture)

        self.doc = fitz.open(pdf_path)
        self.page_index = page_index
        self.page = self.doc.load_page(self.page_index)

        # zoom factor: 1.0 => render at 72dpi-like scale in PyMuPDF terms
        self.zoom = 1.5

        # Selection state (in widget pixels)
        self.dragging = False
        self.sel_start = QPointF()
        self.sel_end = QPointF()

        self.image_qt = None
        self.pixmap = None

        self.setMouseTracking(True)
        self.render_page()

    def render_page(self):
        # Render page at zoom scale
        mat = fitz.Matrix(self.zoom, self.zoom)
        pix = self.page.get_pixmap(matrix=mat, alpha=False)

        # Convert to QImage (RGB)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        self.image_qt = img.copy()  # copy to own memory
        self.pixmap = QPixmap.fromImage(self.image_qt)

        self.setFixedSize(self.pixmap.size())
        self.update()

    def clamp_zoom(self):
        self.zoom = max(0.25, min(self.zoom, 8.0))

    def zoom_by(self, factor: float, anchor: QPointF | None = None):
        old_zoom = self.zoom
        self.zoom *= factor
        self.clamp_zoom()
        if abs(self.zoom - old_zoom) < 1e-6:
            return
        self.render_page()

        # Note: For simplicity we don't preserve the scroll anchor here.
        # You can add "keep anchor under cursor" behavior later if desired.

    def paintEvent(self, event):
        if not self.pixmap:
            return

        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.pixmap)

        # Draw selection rectangle overlay
        if self.dragging or (self.sel_start != self.sel_end):
            rect = QRectF(self.sel_start, self.sel_end).normalized()
            pen = QPen(Qt.GlobalColor.red, 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(rect)

            # Compute measurement in pt using zoom mapping
            w_px = rect.width()
            h_px = rect.height()

            # pixels_per_pt is zoom because we used Matrix(zoom, zoom)
            w_pt = w_px / self.zoom
            h_pt = h_px / self.zoom

            text = (
                f"W: {w_pt:.2f} pt ({pt_to_pica(w_pt):.2f} pc, {pt_to_mm(w_pt):.2f} mm)   "
                f"H: {h_pt:.2f} pt ({pt_to_pica(h_pt):.2f} pc, {pt_to_mm(h_pt):.2f} mm)"
            )

            # Draw a simple text background
            painter.setPen(Qt.GlobalColor.black)
            painter.drawText(10, 20, text)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.sel_start = QPointF(event.position())
            self.sel_end = QPointF(event.position())
            self.update()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.sel_end = QPointF(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.dragging:
            self.dragging = False
            self.sel_end = QPointF(event.position())
            self.update()

    def wheelEvent(self, event):
        """
        Two-finger scroll often arrives here.
        Choose behavior:
        - If you want zoom on two-finger scroll ALWAYS, keep as-is.
        - If you want zoom only with Ctrl, uncomment the Ctrl check.
        """
        # If you prefer Ctrl+scroll to zoom, enable this:
        # if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
        #     event.ignore()
        #     return

        delta = event.angleDelta().y()
        if delta == 0:
            return

        # Smooth-ish scaling
        factor = 1.1 if delta > 0 else 1 / 1.1
        self.zoom_by(factor, anchor=event.position())
        event.accept()

    def event(self, e):
        # Handle pinch gesture if available
        if e.type() == e.Type.Gesture:
            g = e.gesture(Qt.GestureType.PinchGesture)
            if g:
                # scaleFactor > 1 => zoom in
                sf = g.scaleFactor()
                # Avoid tiny jitter
                if sf and abs(sf - 1.0) > 0.01:
                    self.zoom_by(sf)
                return True
        return super().event(e)


class MainWindow(QMainWindow):
    def __init__(self, pdf_path: str):
        super().__init__()
        self.setWindowTitle("PDF Rectangle Measure (pt / pica / mm)")

        self.viewer = PdfView(pdf_path, page_index=0)

        scroll = QScrollArea()
        scroll.setWidget(self.viewer)
        scroll.setWidgetResizable(False)

        self.setCentralWidget(scroll)
        self.resize(1000, 800)


def main():
    if len(sys.argv) < 2:
        print("Usage: python pdf_measure.py /path/to/file.pdf")
        sys.exit(1)

    pdf_path = sys.argv[1]

    app = QApplication(sys.argv)
    w = MainWindow(pdf_path)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
