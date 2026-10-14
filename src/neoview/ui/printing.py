"""Printing: QPrintDialog front end plus testable page selection and rendering.

``print_document`` is the one call MainWindow needs. Everything it does is split into pure
or printer-only functions so tests can drive them against a PDF-format ``QPrinter``:

- ``selected_pages`` - which page indices a print range means.
- ``page_sequence`` - expand those pages for copies/collation when the print system will
  not do it itself.
- ``fit_page`` - where a page goes in the printable area, and whether to rotate it.
- ``render_pages`` - render each page with its own ``fitz.Document`` at up to
  ``MAX_PRINT_DPI`` and paint it onto the printer.

Printing reads the file from disk, never the viewer's open document, so it is safe while the
view keeps rendering.
"""

from __future__ import annotations

import os

import fitz
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QTransform
from PySide6.QtPrintSupport import QAbstractPrintDialog, QPrintDialog, QPrinter
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from neoview.ui.password import open_document

MAX_PRINT_DPI = 300

RANGE_ALL = "all"
RANGE_PAGES = "range"
RANGE_CURRENT = "current"


def selected_pages(
    range_mode: str,
    page_count: int,
    current_page: int = 0,
    from_page: int = 0,
    to_page: int = 0,
) -> list[int]:
    """Zero-based page indices to print.

    ``from_page``/``to_page`` are one-based and inclusive, as QPrinter reports them; 0 means
    "not set". They are clamped to the document and swapped if reversed. Unknown modes
    print everything.
    """
    if page_count <= 0:
        return []
    if range_mode == RANGE_CURRENT:
        return [min(max(current_page, 0), page_count - 1)]
    if range_mode == RANGE_PAGES and (from_page > 0 or to_page > 0):
        first = from_page if from_page > 0 else 1
        last = to_page if to_page > 0 else page_count
        if first > last:
            first, last = last, first
        first = max(first, 1)
        last = min(last, page_count)
        if first > page_count:
            return []
        return list(range(first - 1, last))
    return list(range(page_count))


def printer_pages(printer: QPrinter, page_count: int, current_page: int = 0) -> list[int]:
    """``selected_pages`` for the range the user chose in the print dialog."""
    rng = printer.printRange()
    if rng == QPrinter.PrintRange.CurrentPage:
        mode = RANGE_CURRENT
    elif rng == QPrinter.PrintRange.PageRange:
        mode = RANGE_PAGES
    else:
        mode = RANGE_ALL
    return selected_pages(mode, page_count, current_page, printer.fromPage(), printer.toPage())


def page_sequence(pages: list[int], copies: int = 1, collate: bool = True) -> list[int]:
    """Repeat ``pages`` for ``copies``: whole sets when collating, else each page in turn."""
    copies = max(1, copies)
    if collate:
        return pages * copies
    return [p for p in pages for _ in range(copies)]


def fit_page(page_w: float, page_h: float, target: QRectF) -> tuple[QRectF, bool]:
    """Largest rect with the page's aspect ratio centred in ``target``.

    Returns ``(rect, rotate)``. ``rotate`` is True when the page and the target have opposite
    orientations (landscape page on portrait paper or the reverse); the page should then be
    turned 90 degrees and ``rect`` already has the rotated aspect ratio.
    """
    if page_w <= 0 or page_h <= 0 or target.width() <= 0 or target.height() <= 0:
        return QRectF(target), False
    page_landscape = page_w > page_h
    target_landscape = target.width() > target.height()
    rotate = page_w != page_h and page_landscape != target_landscape
    w, h = (page_h, page_w) if rotate else (page_w, page_h)
    scale = min(target.width() / w, target.height() / h)
    out_w, out_h = w * scale, h * scale
    x = target.x() + (target.width() - out_w) / 2.0
    y = target.y() + (target.height() - out_h) / 2.0
    return QRectF(x, y, out_w, out_h), rotate


def render_dpi(printer: QPrinter) -> int:
    """Rendering resolution for ``printer``: its own resolution, capped at MAX_PRINT_DPI."""
    res = printer.resolution()
    if res <= 0:
        return MAX_PRINT_DPI
    return min(res, MAX_PRINT_DPI)


def render_page_image(
    page: fitz.Page, width_px: int, height_px: int, grayscale: bool = False
) -> QImage:
    """Render ``page`` to an image of about ``width_px`` x ``height_px`` (unrotated)."""
    rect = page.rect
    zoom = max(width_px / rect.width, height_px / rect.height, 0.01)
    colorspace = fitz.csGRAY if grayscale else fitz.csRGB
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=colorspace, alpha=False)
    fmt = QImage.Format.Format_Grayscale8 if grayscale else QImage.Format.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


def render_pages(
    printer: QPrinter,
    path: str,
    pages: list[int],
    password: str | None = None,
) -> int:
    """Paint ``pages`` of the PDF at ``path`` onto ``printer``. Returns pages printed.

    Opens its own ``fitz.Document`` (never shares the viewer's). Each page is fitted to the
    printable area, keeping its aspect ratio, and turned 90 degrees when its orientation
    differs from the paper's. Raises ``PermissionError`` for a wrong password.
    """
    if not pages:
        return 0
    doc = open_document(path, password)
    painter = QPainter()
    printed = 0
    try:
        if not painter.begin(printer):
            return 0
        printer_res = printer.resolution()
        dpi = render_dpi(printer)
        grayscale = printer.colorMode() == QPrinter.ColorMode.GrayScale
        target = QRectF(printer.pageLayout().paintRectPixels(printer_res))
        target.moveTo(0, 0)  # the painter's origin is the top-left of the paintable area
        for index in pages:
            if not 0 <= index < doc.page_count:
                continue
            if printed:
                printer.newPage()
            page = doc[index]
            dest, rotate = fit_page(page.rect.width, page.rect.height, target)
            # Image size in pixels at the render dpi, in the page's own orientation.
            scale = dpi / float(printer_res) if printer_res > 0 else 1.0
            img_w = max(1, round((dest.height() if rotate else dest.width()) * scale))
            img_h = max(1, round((dest.width() if rotate else dest.height()) * scale))
            image = render_page_image(page, img_w, img_h, grayscale)
            if rotate:
                image = image.transformed(QTransform().rotate(90))
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawImage(dest, image)
            printed += 1
    finally:
        if painter.isActive():
            painter.end()
        doc.close()
    return printed


def build_print_dialog(
    printer: QPrinter, parent: QWidget | None, page_count: int
) -> QPrintDialog:
    """Print dialog offering page range, current page, copies and print-to-file."""
    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle("Print")
    option = QAbstractPrintDialog.PrintDialogOption
    dialog.setOption(option.PrintPageRange, True)
    dialog.setOption(option.PrintCurrentPage, True)
    dialog.setOption(option.PrintCollateCopies, True)
    dialog.setOption(option.PrintToFile, True)
    dialog.setMinMax(1, max(1, page_count))
    printer.setFromTo(1, max(1, page_count))
    printer.setPrintRange(QPrinter.PrintRange.AllPages)
    return dialog


def print_document(
    parent: QWidget | None,
    path: str,
    current_page: int = 0,
    password: str | None = None,
) -> bool:
    """Show the print dialog for ``path`` and print it. True if anything was printed.

    ``current_page`` is the zero-based page the viewer shows (used for "Current page").
    ``password`` unlocks encrypted documents; pass the one the viewer opened it with.
    """
    probe = open_document(path, password)
    try:
        page_count = probe.page_count
    finally:
        probe.close()

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setDocName(os.path.basename(path))
    printer.setColorMode(QPrinter.ColorMode.Color)
    dialog = build_print_dialog(printer, parent, page_count)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False

    pages = printer_pages(printer, page_count, current_page)
    copies = printer.copyCount()
    if printer.supportsMultipleCopies():
        copies = 1  # the print system makes the copies
    sequence = page_sequence(pages, copies, printer.collateCopies())

    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        return render_pages(printer, path, sequence, password) > 0
    finally:
        QApplication.restoreOverrideCursor()
