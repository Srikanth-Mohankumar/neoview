"""Page layout modes and reading colour modes, as pure functions for PdfView.

Geometry
--------
``layout_pages`` places every page of a document in scene coordinates for one of
``PAGE_MODES``:

- ``"continuous"``: one page per row, rows stacked vertically. With ``viewport_width=0``
  it reproduces ``PdfView._layout_pages`` exactly (first row at ``y=spacing``, each row
  advances ``height + spacing``, narrower pages centred on the widest one).
- ``"single"``: the same geometry as continuous; ``PageLayout.paged`` is True, telling the
  view to clamp its scene rect / scrolling to the current row (``PageLayout.row_bounds``).
- ``"two-page"``: rows of two, pages (0, 1), (2, 3), ...; an odd last page sits alone in
  the left slot.
- ``"two-page-cover"``: page 0 alone in the right slot (like a book cover), then
  (1, 2), (3, 4), ...; an even page count leaves the last page alone in the left slot.

Two-page rows are centred horizontally as a unit with ``spacing`` between the pages, so
mixed page sizes stay centred per row. A page alone in a slot is placed against the scene's
centre line (spine) so it lines up with the spreads around it. Within a row, pages are
centred vertically on the row's tallest page. All sizes are in PDF points and are
multiplied by ``zoom``; ``spacing`` is in scene units and is not zoomed. Pass page sizes
already swapped for 90/270 degree rotation.

Colour
------
``apply_color_mode(image, mode)`` returns a transformed copy of a rendered page image for
one of ``COLOR_MODES``. It uses only C-backed Qt operations (format conversion, byte
look-up tables, composition), so it is cheap enough for the render path.

- ``"normal"``: unchanged copy.
- ``"night"``: luminance inverted, hue kept: each pixel is shifted by ``255 - 2*Y`` on every
  channel, so white paper becomes black, black text becomes white, and a red figure stays
  red (lighter or darker) instead of turning cyan as a plain inversion would.
- ``"sepia"``: luminance mapped onto a warm paper-to-brown-ink ramp.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from PySide6.QtGui import QColor, QImage, QPainter

PAGE_MODES = ("single", "continuous", "two-page", "two-page-cover")
COLOR_MODES = ("normal", "night", "sepia")

DEFAULT_SPACING = 20.0


class Rect(NamedTuple):
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class PageLayout:
    mode: str
    rects: list[Rect]  # one per page, in page order
    rows: list[tuple[int, ...]]  # page indices per row, top to bottom
    scene_width: float
    scene_height: float

    @property
    def paged(self) -> bool:
        """True when the view should show one row at a time (``"single"`` mode)."""
        return self.mode == "single"

    def row_of(self, page_index: int) -> int:
        for row_index, row in enumerate(self.rows):
            if page_index in row:
                return row_index
        raise IndexError(f"page {page_index} not in layout")

    def row_bounds(self, row_index: int) -> Rect:
        """Bounding rect of the pages in ``row_index`` (no spacing included)."""
        rects = [self.rects[i] for i in self.rows[row_index]]
        left = min(r.x for r in rects)
        top = min(r.y for r in rects)
        right = max(r.x + r.w for r in rects)
        bottom = max(r.y + r.h for r in rects)
        return Rect(left, top, right - left, bottom - top)


def _check_mode(mode: str) -> None:
    if mode not in PAGE_MODES:
        raise ValueError(f"unknown page mode {mode!r}; expected one of {PAGE_MODES}")


def page_rows(mode: str, page_count: int) -> list[tuple[int, ...]]:
    """Group page indices into display rows for ``mode``."""
    _check_mode(mode)
    if page_count <= 0:
        return []
    if mode in ("single", "continuous"):
        return [(i,) for i in range(page_count)]
    rows: list[tuple[int, ...]] = []
    start = 0
    if mode == "two-page-cover":
        rows.append((0,))
        start = 1
    for i in range(start, page_count, 2):
        rows.append(tuple(range(i, min(i + 2, page_count))))
    return rows


def _solo_in_right_slot(mode: str, row_index: int) -> bool:
    return mode == "two-page-cover" and row_index == 0


def layout_pages(
    page_sizes: Sequence[tuple[float, float]],
    viewport_width: float = 0.0,
    zoom: float = 1.0,
    spacing: float = DEFAULT_SPACING,
    mode: str = "continuous",
) -> PageLayout:
    """Lay out pages of ``page_sizes`` (width, height in points) for ``mode``."""
    _check_mode(mode)
    if zoom <= 0:
        raise ValueError("zoom must be positive")
    sizes = [(float(w) * zoom, float(h) * zoom) for w, h in page_sizes]
    rows = page_rows(mode, len(sizes))
    if not rows:
        return PageLayout(mode, [], [], max(0.0, float(viewport_width)), 0.0)

    two_up = mode in ("two-page", "two-page-cover")

    # Half-width each row needs either side of the centre line.
    half_extent = 0.0
    for row_index, row in enumerate(rows):
        if len(row) == 2:
            half = (sizes[row[0]][0] + spacing + sizes[row[1]][0]) / 2.0
        elif two_up:
            half = sizes[row[0]][0] + spacing / 2.0
        else:
            half = sizes[row[0]][0] / 2.0
        half_extent = max(half_extent, half)
    scene_width = max(float(viewport_width), 2.0 * half_extent)
    centre = scene_width / 2.0

    rects: list[Rect | None] = [None] * len(sizes)
    y = float(spacing)
    for row_index, row in enumerate(rows):
        row_h = max(sizes[i][1] for i in row)
        if len(row) == 2:
            left, right = row
            pair_w = sizes[left][0] + spacing + sizes[right][0]
            x_left = centre - pair_w / 2.0
            xs = {left: x_left, right: x_left + sizes[left][0] + spacing}
        elif two_up:
            page = row[0]
            if _solo_in_right_slot(mode, row_index):
                xs = {page: centre + spacing / 2.0}
            else:
                xs = {page: centre - spacing / 2.0 - sizes[page][0]}
        else:
            page = row[0]
            xs = {page: centre - sizes[page][0] / 2.0}
        for page in row:
            w, h = sizes[page]
            rects[page] = Rect(xs[page], y + (row_h - h) / 2.0, w, h)
        y += row_h + spacing

    return PageLayout(mode, [r for r in rects if r is not None], rows, scene_width, y)


# -- colour modes ---------------------------------------------------------------------

_SEPIA_PAPER = QColor(244, 236, 216)
_SEPIA_INK = QColor(40, 28, 16)
_NIGHT_BACKGROUND = QColor(0, 0, 0)

_LUT_NIGHT_UP = bytes(max(0, 255 - 2 * y) for y in range(256))
_LUT_NIGHT_DOWN = bytes(max(0, 2 * y - 255) for y in range(256))


def page_background(mode: str) -> QColor:
    """Colour of an empty page area in ``mode`` (what white paper maps to)."""
    _check_color_mode(mode)
    if mode == "night":
        return QColor(_NIGHT_BACKGROUND)
    if mode == "sepia":
        return QColor(_SEPIA_PAPER)
    return QColor(255, 255, 255)


def _check_color_mode(mode: str) -> None:
    if mode not in COLOR_MODES:
        raise ValueError(f"unknown color mode {mode!r}; expected one of {COLOR_MODES}")


def _luminance(image: QImage) -> QImage:
    return image.convertToFormat(QImage.Format.Format_Grayscale8)


def _mapped_gray(gray: QImage, lut: bytes) -> QImage:
    """Apply a 256-entry byte LUT to a Grayscale8 image, returned as ARGB32 premultiplied."""
    data = bytes(gray.constBits())[: gray.sizeInBytes()].translate(lut)
    mapped = QImage(data, gray.width(), gray.height(), gray.bytesPerLine(),
                    QImage.Format.Format_Grayscale8)
    # convertToFormat copies, so the result no longer refers to ``data``.
    return mapped.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def _composite(target: QImage, source: QImage, mode: QPainter.CompositionMode) -> None:
    painter = QPainter(target)
    try:
        painter.setCompositionMode(mode)
        painter.drawImage(0, 0, source)
    finally:
        painter.end()


def _night(src: QImage) -> QImage:
    gray = _luminance(src)
    up = _mapped_gray(gray, _LUT_NIGHT_UP)  # 255 - 2Y where Y is dark
    down = _mapped_gray(gray, _LUT_NIGHT_DOWN)  # 2Y - 255 where Y is light
    out = src.copy()
    _composite(out, up, QPainter.CompositionMode.CompositionMode_Plus)
    # Saturating subtract: invert, add, invert back.
    out.invertPixels()
    _composite(out, down, QPainter.CompositionMode.CompositionMode_Plus)
    out.invertPixels()
    return out


def _sepia(src: QImage) -> QImage:
    gray = _luminance(src).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    out = QImage(src.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(_SEPIA_PAPER)
    _composite(out, gray, QPainter.CompositionMode.CompositionMode_Multiply)
    ink = QImage(src.size(), QImage.Format.Format_ARGB32_Premultiplied)
    ink.fill(_SEPIA_INK)
    _composite(out, ink, QPainter.CompositionMode.CompositionMode_Screen)
    return out


def apply_color_mode(image: QImage, mode: str) -> QImage:
    """Return a copy of ``image`` transformed for reading ``mode``.

    The result has the same size and device pixel ratio; its format is
    ``Format_ARGB32_Premultiplied`` for ``night``/``sepia`` and unchanged for ``normal``.
    Alpha is not preserved for transformed modes (page renders are opaque).
    """
    _check_color_mode(mode)
    if mode == "normal" or image.isNull():
        return image.copy()
    src = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    out = _night(src) if mode == "night" else _sepia(src)
    out.setDevicePixelRatio(image.devicePixelRatio())
    return out
