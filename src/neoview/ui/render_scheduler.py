"""Cooperative, cancellable page rendering.

Pages are rendered in horizontal bands from a MuPDF display list, a few milliseconds of work
per event-loop turn, so the GUI never stalls for a whole page render and a zoom or scroll can
cancel a render half way through.

Why this runs on the GUI thread and not in worker threads: PyMuPDF holds the GIL for every
MuPDF call (its SWIG bindings never release it), so render threads give no parallelism, and
each worker render would still freeze the GUI for the full call. PyMuPDF also runs MuPDF with
a single global context (``mupdf.reinit_singlethreaded()``) and reports warnings through
Python callbacks; Python code running inside such a callback can hand the GIL to another
thread in the middle of a MuPDF call, so two threads could use that context at once even
with separate ``Document`` objects. Driving short bands from the event loop gives the same
responsiveness as a thread would, with no thread-safety risk. True parallel rendering would
need worker processes.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field

import fitz
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage, QPainter

from neoview.ui.page_modes import apply_color_mode

# Pixels per band. Vector pages are cheap to rasterise per band; pages with images pay a
# (partial) image decode per band, so they get fewer, larger bands.
BAND_TARGET_PIXELS = 400_000
IMAGE_BAND_TARGET_PIXELS = 1_500_000
MAX_BANDS = 16
BAND_OVERLAP_PX = 3
# Pixels per step when recolouring a finished page for a reading mode (night/sepia).
COLOR_STRIP_PIXELS = 400_000
# Work done per event-loop turn before yielding back to input and painting.
TICK_BUDGET_S = 0.008


def band_clips(page_rect: fitz.Rect, scale: float, target_pixels: int) -> list[fitz.Rect]:
    """Split *page_rect* into horizontal clip rects of about *target_pixels* each at *scale*.

    Band edges fall on whole device-pixel rows, so anti-aliasing along an edge is computed
    the same way as in a single-pass render and the bands join without seams.
    """
    width = max(1.0, float(page_rect.width))
    height = max(1.0, float(page_rect.height))
    pixels = width * height * scale * scale
    count = max(1, min(MAX_BANDS, math.ceil(pixels / max(1, target_pixels))))
    row0 = math.floor(page_rect.y0 * scale)
    rows = max(1, math.ceil(page_rect.y1 * scale) - row0)
    count = min(count, rows)
    edges = [page_rect.y0]
    for i in range(1, count):
        edges.append((row0 + round(i * rows / count)) / scale)
    edges.append(page_rect.y1)
    return [fitz.Rect(page_rect.x0, a, page_rect.x1, b) for a, b in zip(edges, edges[1:])]


@dataclass
class RenderRequest:
    page_index: int
    page: fitz.Page
    zoom: float
    factor: float
    color_mode: str = "normal"  # page_modes.COLOR_MODES; applied before delivery

    def same_target(self, other: RenderRequest) -> bool:
        return (
            self.page_index == other.page_index
            and abs(self.zoom - other.zoom) < 1e-6
            and abs(self.factor - other.factor) < 1e-6
            and self.color_mode == other.color_mode
        )


@dataclass
class _Job:
    request: RenderRequest
    generation: int
    matrix: fitz.Matrix | None = None
    displaylist: fitz.DisplayList | None = None
    target: fitz.Pixmap | None = None
    clips: list[fitz.Rect] = field(default_factory=list)
    next_band: int = 0
    # Reading-mode recolouring runs after the bands, in strips of rows, on this image.
    colored: QImage | None = None
    strips: list[tuple[int, int]] = field(default_factory=list)
    next_strip: int = 0

    def step(self) -> bool:
        """Do one slice of work. Return True when the page image is complete."""
        if self.colored is not None:
            return self._color_step()
        if self.displaylist is None:
            req = self.request
            page = req.page
            scale = req.zoom * req.factor
            self.matrix = fitz.Matrix(scale, scale)
            self.displaylist = page.get_displaylist()
            rect = page.rect
            self.target = fitz.Pixmap(fitz.csRGB, (rect * self.matrix).irect, False)
            try:
                has_images = bool(page.get_images(full=False))
            except Exception:
                has_images = False
            target = IMAGE_BAND_TARGET_PIXELS if has_images else BAND_TARGET_PIXELS
            self.clips = band_clips(rect, scale, target)
            return False
        clip = self.clips[self.next_band]
        scale = self.matrix.a
        # MuPDF anti-aliases differently next to a clip edge, so render a few extra rows on
        # each side and copy only the band's own rows: the result is pixel-identical to a
        # single-pass render.
        margin = BAND_OVERLAP_PX / scale
        page_rect = self.request.page.rect
        rendered = fitz.Rect(clip.x0, max(page_rect.y0, clip.y0 - margin),
                             clip.x1, min(page_rect.y1, clip.y1 + margin))
        band = self.displaylist.get_pixmap(matrix=self.matrix, alpha=False, clip=rendered)
        full = fitz.IRect(self.target.irect)
        own_rows = fitz.IRect(full.x0, round(clip.y0 * scale), full.x1, round(clip.y1 * scale))
        if self.next_band == 0:
            own_rows.y0 = full.y0
        if self.next_band == len(self.clips) - 1:
            own_rows.y1 = full.y1
        self.target.copy(band, own_rows)
        self.next_band += 1
        if self.next_band < len(self.clips):
            return False
        if self.request.color_mode == "normal":
            return True
        # Recolour in strips, so a night/sepia page does not stall the GUI in one go (a
        # whole A4 page at 200% on a 2x screen takes ~100 ms).
        self.colored = self._raw_image()
        width = max(1, self.colored.width())
        rows = max(1, COLOR_STRIP_PIXELS // width)
        height = self.colored.height()
        self.strips = [(y, min(rows, height - y)) for y in range(0, height, rows)]
        self.next_strip = 0
        self.displaylist = None
        self.target = None
        return not self.strips

    def _color_step(self) -> bool:
        y, h = self.strips[self.next_strip]
        image = self.colored
        strip = apply_color_mode(image.copy(0, y, image.width(), h), self.request.color_mode)
        painter = QPainter(image)
        try:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawImage(0, y, strip)
        finally:
            painter.end()
        self.next_strip += 1
        return self.next_strip >= len(self.strips)

    def image(self) -> QImage:
        if self.colored is not None:
            return self.colored
        return self._raw_image()

    def _raw_image(self) -> QImage:
        pix = self.target
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        # convertToFormat returns an image that owns its pixels, so the fitz buffer can go.
        return img.convertToFormat(QImage.Format.Format_RGB32)

    def release(self) -> None:
        self.displaylist = None
        self.target = None
        self.matrix = None
        self.colored = None


class RenderScheduler(QObject):
    """Render queued pages band by band from the event loop, newest request set wins.

    ``page_rendered(page_index, generation, zoom, factor, image)`` fires on the GUI thread.
    ``schedule`` replaces the whole queue; a job already under way is kept only if the new
    request set still asks for exactly that page, zoom and render factor.
    """

    page_rendered = Signal(int, int, float, float, QImage)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._queue: deque[RenderRequest] = deque()
        self._job: _Job | None = None
        self._generation = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._tick)

    def pending_count(self) -> int:
        return len(self._queue) + (1 if self._job is not None else 0)

    def schedule(self, requests: list[RenderRequest], generation: int) -> None:
        if generation != self._generation:
            self.cancel_all()
            self._generation = generation
        keep = None
        if self._job is not None:
            for req in requests:
                if req.same_target(self._job.request):
                    keep = req
                    break
            if keep is None:
                self._job.release()
                self._job = None
        self._queue = deque(r for r in requests if r is not keep)
        if self.pending_count():
            self._timer.start()

    def cancel_all(self) -> None:
        """Drop every queued and in-flight render, releasing MuPDF objects immediately.

        Call this before closing the document the queued pages belong to.
        """
        self._timer.stop()
        self._queue.clear()
        if self._job is not None:
            self._job.release()
            self._job = None

    def _tick(self) -> None:
        deadline = time.perf_counter() + TICK_BUDGET_S
        while time.perf_counter() < deadline:
            if self._job is None:
                if not self._queue:
                    return
                self._job = _Job(self._queue.popleft(), self._generation)
            job = self._job
            try:
                done = job.step()
            except Exception:
                # A page MuPDF cannot render (or a closed document) must not wedge the queue.
                job.release()
                self._job = None
                continue
            if done:
                self._job = None
                image = job.image()
                job.release()
                req = job.request
                self.page_rendered.emit(req.page_index, job.generation, req.zoom, req.factor,
                                        image)
        if self.pending_count():
            self._timer.start()
