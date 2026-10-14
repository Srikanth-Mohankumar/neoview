"""Rendering benchmark for PdfView on large documents.

Not collected by pytest. Run from the repo root:

    .venv/bin/python scripts/bench_render.py --runs 5 [--json out.json]

Each trial runs in a fresh subprocess (offscreen Qt) so caches, RSS and import cost do not
leak between trials. Generated documents:

- ``vector``: 100 pages, text paragraphs and many vector shapes on every page;
- ``images``: the same, plus a large (2400x1800) photo-like image on every 10th page;
- ``book``: 650 pages of dense text with 20 internal links per page (a long book);
- ``book-images``: the same, plus a distinct 1500x1000 image on every page.

Metrics per trial (wall clock, seconds unless noted):

- ``open_responsive``: ``open_document`` call -> a ``QTimer.singleShot(0)`` posted right
  after it fires, i.e. how long the GUI is unresponsive when a document opens;
- ``open_first_paint``: ``open_document`` call -> page 1 shown sharp and painted;
- ``zoom_call``: time the ``set_zoom(2.0)`` call itself blocks the GUI thread;
- ``zoom_sharp``: fit-width -> 200% zoom until every visible page is sharp;
- ``zoom_max_stall``: longest GUI event-loop stall (ms) between the zoom and sharp pages;
- ``scroll_total``: scroll top -> end at 200% in viewport-height steps, pumping events for
  one 60 Hz frame per step (an idealised fast scroll); for the 650-page books only the
  first 100 pages are scrolled, to keep a trial short;
- ``scroll_max_stall``: longest GUI event-loop stall (ms) during that scroll;
- ``end_sharp``: after the scroll stops, time until the visible pages are sharp;
- ``wheel_total`` / ``wheel_max_stall``: 90 mouse-wheel-like steps of 120 px, one per frame;
  ``wheel_blank_pages_at_end``: visible pages still blank when the last step lands;
- ``read_max_stall``: page-by-page reading from the middle of the document: 12 steps of one
  viewport height with a 150 ms dwell each; longest GUI stall (ms) over all steps;
- ``read_sharp``: median time per reading step until the visible pages are sharp;
- ``peak_rss_mb``: ``ru_maxrss`` of the trial process (Linux reports KiB).

``--memory-scroll`` instead reads every page of the two books at fit width (go to page,
wait until it is sharp), reporting peak RSS while reading, RSS after ``close_document``,
pages reached and whether the trial stopped at the 3000 MB safety limit (Linux only).

"Sharp" means every visible PageItem shows an image rendered at the current zoom and the
view reports no pending renders (``PdfView.pending_render_count`` when it exists).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

VARIANTS = ("vector", "images", "book", "book-images")
SCROLL_PAGES = 100
METRICS = (
    "open_responsive",
    "open_first_paint",
    "zoom_call",
    "zoom_sharp",
    "zoom_max_stall",
    "scroll_total",
    "scroll_max_stall",
    "end_sharp",
    "wheel_total",
    "wheel_max_stall",
    "wheel_blank_pages_at_end",
    "read_max_stall",
    "read_sharp",
    "peak_rss_mb",
    "loadavg_1m",
)


def _photo(w: int, h: int):
    """Deterministic photo-like RGB pixmap (smooth gradients and a xor texture)."""
    import fitz

    rows = []
    for y in range(h):
        row = bytearray(w * 3)
        for x in range(0, w * 3, 3):
            px = x // 3
            row[x] = (px * 255 // w) & 0xFF
            row[x + 1] = (y * 255 // h) & 0xFF
            row[x + 2] = ((px ^ y) >> 2) & 0xFF
        rows.append(bytes(row))
    return fitz.Pixmap(fitz.csRGB, w, h, b"".join(rows), False)


def make_book(path: Path, with_images: bool, n_pages: int = 650) -> None:
    import fitz

    doc = fitz.open()
    base = _photo(1500, 1000) if with_images else None
    words = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor "
             "incididunt ut labore et dolore magna aliqua ut enim ad minim veniam").split()
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 56), f"Chapter {i // 20 + 1} - page {i + 1}", fontsize=11)
        y = 80.0
        n_lines = 30 if with_images else 62
        if with_images:
            pix = fitz.Pixmap(base, 0)  # copy without alpha
            # Make every page's image distinct so MuPDF cannot share one decode.
            pix.invert_irect(fitz.IRect(0, (i * 7) % 900, 1500, (i * 7) % 900 + 100))
            page.insert_image(fitz.Rect(72, 470, 523, 770), stream=pix.tobytes("jpeg",
                                                                              jpg_quality=85))
        for k in range(n_lines):
            line = " ".join(words[(i + k + j) % len(words)] for j in range(15))
            page.insert_text((72, y), line, fontsize=9.5)
            y += 12
    # A real book is full of cross-references (TOC, index, citations): 20 internal links per
    # page, so the cost of reading links at open time is exercised.
    for i, page in enumerate(doc):
        for k in range(20):
            rect = fitz.Rect(72 + (k % 5) * 90, 80 + (k // 5) * 12 - 9, 72 + (k % 5) * 90 + 60,
                             80 + (k // 5) * 12 + 2)
            page.insert_link({"kind": fitz.LINK_GOTO, "from": rect,
                              "page": (i * 7 + k * 31) % n_pages, "to": fitz.Point(72, 100)})
    doc.save(str(path), deflate=True, garbage=1)
    doc.close()


def make_pdf(path: Path, variant: str) -> None:
    import fitz

    if variant.startswith("book"):
        make_book(path, with_images=variant == "book-images")
        return
    doc = fitz.open()
    image_bytes = None
    if variant == "images":
        image_bytes = _photo(2400, 1800).tobytes("jpeg", jpg_quality=90)
    text = (
        "The quick brown fox jumps over the lazy dog. Pack my box with five dozen "
        "liquor jugs. Sphinx of black quartz, judge my vow. "
    ) * 3
    for i in range(100):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 60), f"Benchmark page {i + 1}", fontsize=18)
        y = 90
        for k in range(28):
            page.insert_text((72, y), text[(k * 7) % 60:][:95], fontsize=9)
            y += 12
        shape = page.new_shape()
        for k in range(300):
            cx = 72 + (k * 37) % 450
            cy = 450 + (k * 53) % 330
            shape.draw_circle((cx, cy), 4 + k % 9)
            shape.finish(color=(0, 0, (k % 5) / 5), fill=((k % 7) / 7, 0.3, 0.6), width=0.6)
        for k in range(120):
            shape.draw_line((72, 440 + k * 3), (523, 780 - k * 2.5))
        shape.finish(color=(0.2, 0.2, 0.2), width=0.3)
        shape.commit()
        if image_bytes is not None and i % 10 == 0:
            page.insert_image(fitz.Rect(72, 300, 523, 640), stream=image_bytes)
    doc.save(str(path), deflate=True)
    doc.close()


def _peak_rss_mb() -> float:
    try:
        import resource
    except ImportError:  # Windows
        return float("nan")
    kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return kb / 1024.0 if sys.platform != "darwin" else kb / (1024.0 * 1024.0)


def run_trial(pdf: Path) -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    from neoview.ui.pdf_view import PdfView

    view = PdfView()
    view.resize(1280, 800)
    view.show()
    app.processEvents()

    paints: list[float] = []

    class PaintSpy(QObject):
        def eventFilter(self, obj, event):  # noqa: N802 - Qt API
            if event.type() == QEvent.Type.Paint:
                paints.append(time.perf_counter())
            return False

    spy = PaintSpy()
    view.viewport().installEventFilter(spy)

    # Stall meter: a 1 ms timer; the largest gap between ticks is the longest time the GUI
    # thread could not service its event loop.
    ticks: list[float] = []
    clock = QElapsedTimer()
    clock.start()
    meter = QTimer()
    meter.setInterval(1)
    meter.timeout.connect(lambda: ticks.append(time.perf_counter()))

    def pending() -> int:
        fn = getattr(view, "pending_render_count", None)
        return int(fn()) if callable(fn) else 0

    def sharp() -> bool:
        idxs = view._visible_page_indices()
        if not idxs:
            return False
        for idx in idxs:
            p = view._pages[idx]
            if p.render_zoom <= 0 or abs(p.render_zoom - view.zoom) >= 0.01:
                return False
            if getattr(p, "is_preview", False):
                return False
        return pending() == 0

    def pump_until(pred, timeout: float = 300.0) -> float:
        t0 = time.perf_counter()
        while not pred():
            app.processEvents()
            if time.perf_counter() - t0 > timeout:
                state = [(i, round(view._pages[i].render_zoom, 3),
                          getattr(view._pages[i], "is_preview", None))
                         for i in view._visible_page_indices()]
                raise TimeoutError(f"condition not reached: zoom={view.zoom} visible={state} "
                                   f"pending={pending()} "
                                   f"timer={view._rerender_timer.isActive()}")
            time.sleep(0.0005)
        return time.perf_counter()

    def pump_for(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.0005)

    def max_stall_ms(t0: float, t1: float) -> float:
        pts = [t0] + [t for t in ticks if t0 <= t <= t1] + [t1]
        return max((b - a) for a, b in zip(pts, pts[1:])) * 1000.0

    res: dict = {}
    if hasattr(os, "getloadavg"):
        res["loadavg_1m"] = os.getloadavg()[0]  # conditions, not a result

    # 1. open -> event loop responsive again; open -> first page painted sharp.
    responsive: list[float] = []
    t0 = time.perf_counter()
    view.open_document(str(pdf))
    view.fit_width()
    QTimer.singleShot(0, lambda: responsive.append(time.perf_counter()))
    pump_until(lambda: bool(responsive))
    res["open_responsive"] = responsive[0] - t0
    pump_until(lambda: sharp() and paints and paints[-1] > t0)
    t_sharp = pump_until(lambda: paints[-1] > t0)
    res["open_first_paint"] = t_sharp - t0

    pump_for(0.3)
    meter.start()

    # 2. zoom fit-width -> 200%.
    ticks.clear()
    t0 = time.perf_counter()
    view.set_zoom(2.0)
    res["zoom_call"] = time.perf_counter() - t0
    t1 = pump_until(sharp)
    res["zoom_sharp"] = t1 - t0
    res["zoom_max_stall"] = max_stall_ms(t0, t1)

    pump_for(0.3)

    # 3. scroll top -> end, one viewport height per 60 Hz frame.
    bar = view.verticalScrollBar()
    bar.setValue(0)
    pump_for(0.2)
    ticks.clear()
    step = max(1, view.viewport().height())
    scroll_end = bar.maximum()
    if view.page_count > SCROLL_PAGES:
        scroll_end = min(scroll_end, int(view._page_positions[SCROLL_PAGES]))
    t0 = time.perf_counter()
    while bar.value() < scroll_end:
        bar.setValue(min(bar.maximum(), bar.value() + step))
        pump_for(1 / 60)
    t1 = time.perf_counter()
    res["scroll_total"] = t1 - t0
    res["scroll_max_stall"] = max_stall_ms(t0, t1)
    t2 = pump_until(sharp)
    res["end_sharp"] = t2 - t1

    # 4. wheel scroll: 90 frames of 120 px (about 6 pages at 200%), one step per 60 Hz frame.
    bar.setValue(bar.maximum() // 3)
    pump_until(sharp)
    pump_for(0.2)
    ticks.clear()
    t0 = time.perf_counter()
    for _ in range(90):
        bar.setValue(min(bar.maximum(), bar.value() + 120))
        pump_for(1 / 60)
    t1 = time.perf_counter()
    res["wheel_total"] = t1 - t0
    res["wheel_max_stall"] = max_stall_ms(t0, t1)
    blank = [i for i in view._visible_page_indices() if view._pages[i].render_zoom < 0.5]
    res["wheel_blank_pages_at_end"] = float(len(blank))

    # 5. page-by-page reading: the debounced re-render fires between steps.
    bar.setValue(bar.maximum() // 2)
    pump_until(sharp)
    pump_for(0.2)
    stalls = []
    sharp_times = []
    for _ in range(12):
        ticks.clear()
        t0 = time.perf_counter()
        bar.setValue(min(bar.maximum(), bar.value() + step))
        t1 = pump_until(sharp)
        sharp_times.append(t1 - t0)
        pump_for(max(0.0, 0.15 - (t1 - t0)))
        stalls.append(max_stall_ms(t0, time.perf_counter()))
    res["read_max_stall"] = max(stalls)
    res["read_sharp"] = statistics.median(sharp_times)

    meter.stop()
    view.close_document()
    view.close()
    app.processEvents()
    res["peak_rss_mb"] = _peak_rss_mb()
    return res


MEMORY_ABORT_MB = 3000
MEMORY_METRICS = ("pages_visited", "aborted", "peak_rss_scroll_mb", "rss_after_close_mb",
                  "seconds", "loadavg_1m")


def _current_rss_mb() -> float:
    try:
        with open("/proc/self/statm", encoding="ascii") as fh:
            return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    except (OSError, ValueError, AttributeError):  # not Linux
        return float("nan")


def run_memory_trial(pdf: Path) -> dict:
    """Read the whole book page by page at fit width, waiting for each page to be sharp.

    Stops early (``aborted`` = 1) once RSS passes MEMORY_ABORT_MB so a leaking build cannot
    take the machine down.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import gc

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    from neoview.ui.pdf_view import PdfView

    res: dict = {"loadavg_1m": os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0}
    view = PdfView()
    view.resize(1280, 800)
    view.show()
    app.processEvents()
    view.open_document(str(pdf))
    view.fit_width()

    def sharp(idx: int) -> bool:
        p = view._pages[idx]
        if abs(p.render_zoom - view.zoom) >= 0.01 or getattr(p, "is_preview", False):
            return False
        fn = getattr(view, "pending_render_count", None)
        return not callable(fn) or fn() == 0

    t0 = time.perf_counter()
    peak = 0.0
    visited = 0
    aborted = 0
    for target in range(view.page_count):
        view.go_to_page(target)
        end = time.perf_counter() + 30
        while not sharp(target) and time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.0005)
        visited = target + 1
        rss = _current_rss_mb()
        peak = max(peak, rss)
        if rss > MEMORY_ABORT_MB:
            aborted = 1
            break
    res["seconds"] = time.perf_counter() - t0
    view.close_document()
    for _ in range(5):
        app.processEvents()
    gc.collect()
    res["rss_after_close_mb"] = _current_rss_mb()
    res["peak_rss_scroll_mb"] = peak
    res["pages_visited"] = float(visited)
    res["aborted"] = float(aborted)
    view.close()
    return res


def environment() -> dict:
    import fitz
    import PySide6

    import neoview

    cpu = platform.processor() or ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return {
        "cpu": cpu,
        "nproc": os.cpu_count(),
        "python": platform.python_version(),
        "pymupdf": fitz.VersionBind,
        "pyside6": PySide6.__version__,
        "platform": platform.platform(),
        "qpa": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
        "neoview": neoview.__file__,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--json", help="write raw trials + medians here")
    ap.add_argument("--memory-scroll", action="store_true",
                    help="instead: read every page of the books and measure memory")
    ap.add_argument("--child", help=argparse.SUPPRESS)
    ap.add_argument("--child-memory", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.child:
        print(json.dumps(run_trial(Path(args.child))))
        return 0
    if args.child_memory:
        print(json.dumps(run_memory_trial(Path(args.child_memory))))
        return 0

    metrics = METRICS
    child_flag = "--child"
    if args.memory_scroll:
        metrics = MEMORY_METRICS
        child_flag = "--child-memory"
        if args.variants == ",".join(VARIANTS):
            args.variants = "book,book-images"

    work = Path(tempfile.mkdtemp(prefix="neoview-bench-"))
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"))
    out: dict = {"env": environment(), "runs": args.runs, "variants": {}}
    for variant in args.variants.split(","):
        pdf = work / f"bench-{variant}.pdf"
        make_pdf(pdf, variant)
        trials = []
        for n in range(args.runs):
            proc = subprocess.run(
                [sys.executable, __file__, child_flag, str(pdf)],
                capture_output=True, text=True, env=env, timeout=1800,
            )
            if proc.returncode != 0:
                sys.stderr.write(proc.stdout + proc.stderr)
                return 1
            trial = json.loads(proc.stdout.strip().splitlines()[-1])
            trials.append(trial)
            print(f"{variant} run {n + 1}: " + ", ".join(f"{k}={v:.3f}" for k, v in trial.items()),
                  flush=True)
        med = {k: statistics.median(t[k] for t in trials) for k in metrics}
        out["variants"][variant] = {"trials": trials, "median": med,
                                    "pdf_bytes": pdf.stat().st_size}
    print(json.dumps(out["env"]))
    print(f"\nmedians over {args.runs} runs")
    print("metric".ljust(18) + "".join(v.rjust(12) for v in out["variants"]))
    for k in metrics:
        print(k.ljust(18) + "".join(f"{out['variants'][v]['median'][k]:12.3f}"
                                    for v in out["variants"]))
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
