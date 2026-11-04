"""Render page ranges to PNGs; native PDF annotations are included.

NeoView sidecar annotations are not embedded in this image export. Export an
annotated PDF first when those annotations must appear in rendered images.
"""
from __future__ import annotations

import math
import os
import shutil
import tempfile
from pathlib import Path

import fitz
from PySide6.QtWidgets import QFileDialog, QInputDialog

from neoview.models.page_extraction import parse_page_ranges
from neoview.ui.tool_support import snapshot

MIN_DPI = 36
MAX_DPI = 300
MAX_PAGE_PIXELS = 20_000_000
MAX_TOTAL_PIXELS = 100_000_000
MAX_DIMENSION = 20_000


def validate_request(document, ranges: str, dpi: int):
    """Validate the entire allocation budget before rendering the first page."""
    if isinstance(dpi, bool) or not isinstance(dpi, int) or not MIN_DPI <= dpi <= MAX_DPI:
        raise ValueError(f"Choose a DPI between {MIN_DPI} and {MAX_DPI}.")
    pages = parse_page_ranges(ranges, document.page_count)
    scale = dpi / 72
    total = 0
    for index in pages:
        rect = document[index].rect
        # Conservatively allow for the integer rounding used by Qt/MuPDF pixmaps.
        width, height = math.ceil(rect.width * scale) + 2, math.ceil(rect.height * scale) + 2
        pixels = width * height
        total += pixels
        if (min(width, height) < 1 or max(width, height) > MAX_DIMENSION
                or pixels > MAX_PAGE_PIXELS or total > MAX_TOTAL_PIXELS):
            raise ValueError("Image export is too large. Choose fewer pages or a lower DPI.")
    return pages, scale


def export_pages_png(document, ranges: str, dpi: int, output_directory: str) -> str:
    """Synchronously render numbered PNGs, used in the isolated worker process."""
    pages, scale = validate_request(document, ranges, dpi)
    target = Path(output_directory).absolute()
    if os.path.lexists(target):
        raise FileExistsError("Choose a new output directory; existing folders are not overwritten.")
    if not target.parent.is_dir():
        raise ValueError("Choose an existing parent directory.")
    work = Path(tempfile.mkdtemp(prefix=".neoview-pngs-", dir=target.parent))
    reserved = False
    try:
        for index in pages:
            pixmap = document[index].get_pixmap(matrix=fitz.Matrix(scale, scale),
                                                 alpha=False, annots=True)
            pixmap.save(str(work / f"page-{index + 1:04d}.png"))
        # Reserve the destination exclusively so an existing empty directory is
        # never overwritten by a directory rename on platforms that permit it.
        target.mkdir()
        reserved = True
        # Publish only fully rendered files. Moving the files into our reserved
        # directory works on Windows too, where replacing an empty directory
        # with another directory is not supported by os.replace.
        for image in work.iterdir():
            os.replace(image, target / image.name)
        reserved = False
    finally:
        if work.exists():
            shutil.rmtree(work)
        if reserved:
            shutil.rmtree(target)
    return str(target)


def run(window) -> None:
    with snapshot(window) as (document, _state, source):
        ranges, accepted = QInputDialog.getText(
            window, "Export Pages as PNG", "Pages (for example 1-3, 5). Native PDF annotations "
            "are included; NeoView sidecar annotations are not embedded:",
        )
        if not accepted:
            return
        parse_page_ranges(ranges, document.page_count)
        dpi, accepted = QInputDialog.getInt(
            window, "Export Resolution", "DPI:", 144, MIN_DPI, MAX_DPI,
        )
        if not accepted:
            return
        parent = QFileDialog.getExistingDirectory(window, "Choose Parent Folder for PNG Export")
        if not parent:
            return
        destination = Path(parent) / (Path(source).stem + "-pages")
        validate_request(document, ranges, dpi)
        from neoview.ui.background_png_export import PngExportJob
        PngExportJob(window, document, ranges, dpi, str(destination)).start()
