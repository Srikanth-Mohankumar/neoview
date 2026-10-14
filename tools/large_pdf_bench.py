"""Generate book-sized PDFs and measure how long NeoView takes to open them.

Reproduction harness for "opening a 600+ page book hangs the viewer". Nothing it
generates is committed; point it at a scratch directory.

Usage (from the repo root):
    .venv/bin/python tools/large_pdf_bench.py generate <dir> [--pages 650]
    .venv/bin/python tools/large_pdf_bench.py bench <dir> [--runs 3] [--timeout 120]
    .venv/bin/python tools/large_pdf_bench.py open <file.pdf> [--profile out.prof]

`bench` opens every PDF in <dir> in a fresh child process (so peak RSS is per file),
kills a child that exceeds --timeout, and prints one JSON line per run:
  open_s      time spent inside MainWindow._open_file
  responsive_s  time from _open_file returning until a QTimer.singleShot(0) probe runs
  max_stall_s   longest gap between 20 ms heartbeats during the following 3 s
  peak_rss_mb   ru_maxrss of the child
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud "
    "exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure "
    "dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
)
NEEDLE_PAGE = 600  # 0-based page that carries a unique search term
NEEDLE = "zebracrossing"
RSS_CAP_MB = 3000


def _text_page(doc, i: int, width: float = 595, height: float = 842):
    import fitz

    page = doc.new_page(width=width, height=height)
    page.insert_text((60, 70), f"Chapter {i // 10 + 1}, section {i % 10 + 1}", fontsize=18)
    body = (LOREM * 12)[: int(3200 * (width * height) / (595 * 842))]
    if i == NEEDLE_PAGE:
        body = f"{NEEDLE} " + body
    page.insert_textbox(fitz.Rect(60, 95, width - 60, height - 60), body, fontsize=10)
    page.insert_text((width / 2 - 10, height - 30), str(i + 1), fontsize=9)
    return page


def _photo_pixmaps(count: int) -> list:
    """Photo-like ~1500x1000 RGB pixmaps made by rendering random translucent shapes."""
    import fitz

    rng = random.Random(7)
    out = []
    for _ in range(count):
        src = fitz.open()
        page = src.new_page(width=300, height=200)
        for _ in range(120):
            x, y = rng.uniform(0, 300), rng.uniform(0, 200)
            r = rng.uniform(4, 60)
            color = (rng.random(), rng.random(), rng.random())
            page.draw_circle((x, y), r, color=None, fill=color, fill_opacity=rng.uniform(0.2, 0.8))
        out.append(page.get_pixmap(matrix=fitz.Matrix(5, 5), alpha=False))
        src.close()
    return out


def generate(out_dir: Path, pages: int) -> list[Path]:
    import fitz

    out_dir.mkdir(parents=True, exist_ok=True)
    made = []

    # (a) dense text with headings
    p = out_dir / "a_text.pdf"
    doc = fitz.open()
    for i in range(pages):
        _text_page(doc, i)
    doc.save(str(p), garbage=3, deflate=True)
    doc.close()
    made.append(p)

    # (b) same + ~200-entry outline + internal links on many pages
    p = out_dir / "b_toc_links.pdf"
    doc = fitz.open()
    for i in range(pages):
        _text_page(doc, i)
    toc = []
    for ch in range(pages // 10):
        toc.append([1, f"Chapter {ch + 1}", ch * 10 + 1])
        if ch % 3 == 0:
            toc.append([2, f"Section {ch + 1}.1", ch * 10 + 3])
    doc.set_toc(toc[:200])
    for i in range(0, pages, 2):
        page = doc[i]
        for k in range(4):
            target = (i * 7 + k * 97) % pages
            page.insert_link(
                {
                    "kind": fitz.LINK_GOTO,
                    "from": fitz.Rect(60, 700 + k * 20, 260, 715 + k * 20),
                    "page": target,
                    "to": fitz.Point(0, 0),
                }
            )
    doc.save(str(p), garbage=3, deflate=True)
    doc.close()
    made.append(p)

    # (c) one ~1500px raster photo per page. Each page gets a distinct JPEG (a few
    # pixels differ) so PyMuPDF cannot dedupe them into one shared image object.
    p = out_dir / "c_images.pdf"
    bases = _photo_pixmaps(12)
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((60, 70), f"Plate {i + 1}", fontsize=18)
        pix = bases[i % len(bases)]
        for k in range(8):
            pix.set_pixel((i * 13 + k) % pix.width, (i * 7) % pix.height, (i % 256, k * 30, 0))
        jpeg = pix.tobytes("jpg", jpg_quality=80)
        page.insert_image(fitz.Rect(60, 100, 535, 420), stream=jpeg)
        page.insert_textbox(fitz.Rect(60, 440, 535, 780), LOREM * 3, fontsize=10)
    doc.save(str(p), garbage=0, deflate=True)
    doc.close()
    made.append(p)

    # (d) mixed page sizes
    p = out_dir / "d_mixed_sizes.pdf"
    sizes = [(595, 842), (612, 792), (1191, 842), (420, 595), (842, 595), (500, 1400)]
    doc = fitz.open()
    for i in range(pages):
        w, h = sizes[i % len(sizes)]
        _text_page(doc, i, w, h)
    doc.save(str(p), garbage=3, deflate=True)
    doc.close()
    made.append(p)

    # (e) native annotations on ~100 pages
    p = out_dir / "e_annots.pdf"
    doc = fitz.open()
    for i in range(pages):
        _text_page(doc, i)
    for i in range(0, pages, max(1, pages // 100)):
        page = doc[i]
        page.add_highlight_annot(fitz.Rect(60, 95, 400, 130))
        page.add_text_annot(fitz.Point(520, 80), f"Note on page {i + 1}")
        page.add_underline_annot(fitz.Rect(60, 140, 300, 160))
    doc.save(str(p), garbage=3, deflate=True)
    doc.close()
    made.append(p)
    return made


def _peak_rss_mb() -> float:
    try:
        import resource  # Unix only; this harness is Linux-oriented but must import on Windows.
    except ImportError:
        return -1.0
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def _rss_mb() -> float:
    try:
        with open("/proc/self/statm") as fh:
            return round(int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20, 1)
    except OSError:
        return -1.0


def _stress(app, win, budget_s: float) -> list[dict]:
    """Drive what a reader does right after opening a book; time each step."""
    from PySide6.QtWidgets import QApplication

    view = win.current_view()
    steps: list[dict] = []

    def pump(n: int = 3) -> None:
        for _ in range(n):
            QApplication.processEvents()

    def step(name, fn):
        t = time.perf_counter()
        fn()
        pump()
        rec = {"step": name, "s": round(time.perf_counter() - t, 3), "rss_mb": _rss_mb()}
        steps.append(rec)
        print(json.dumps(rec), flush=True)

    def scroll_through():
        bar = view.verticalScrollBar()
        page_step = max(1, bar.pageStep())
        start = time.perf_counter()
        last_report = -1
        for value in range(0, bar.maximum() + page_step, page_step):
            bar.setValue(value)
            pump(2)
            # Let the debounced re-render timer fire like a reader pausing briefly.
            view._rerender_pages()
            page = view.current_page
            rss = _rss_mb()
            if page // 50 != last_report:
                last_report = page // 50
                print(json.dumps({"scroll_page": page, "t": round(time.perf_counter() - start, 2),
                                  "rss_mb": rss}), flush=True)
            # Abort before the OOM killer picks a victim on the host.
            if rss > RSS_CAP_MB or time.perf_counter() - start > budget_s:
                print(json.dumps({"scroll_ABORTED_at_page": page, "rss_mb": rss,
                                  "t": round(time.perf_counter() - start, 2)}), flush=True)
                return

    def search():
        win._search_input.setText(NEEDLE)
        win._execute_search_current()
        deadline = time.perf_counter() + 30
        while win._search_batch_timer.isActive() and time.perf_counter() < deadline:
            pump(1)

    step("last_page", view.last_page)
    step("first_page", view.first_page)
    step("scroll_through", scroll_through)
    step("search", search)
    step("zoom_200", lambda: view.set_zoom(2.0))
    step("fit_width", view.fit_width)
    path = win.current_context().file_path
    step("close_tab", lambda: win._close_tab_index(win._tabs.currentIndex()))
    step("reopen_session_restore", lambda: win._open_file(path))
    return steps


def open_and_measure(
    pdf: Path, profile: str | None, stress: bool = False, thumbs: bool = False
) -> dict:
    """Child-process body: open `pdf` in a real offscreen MainWindow and time it."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QElapsedTimer, QEventLoop, QSettings, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)
    import neoview.ui.main_window as mw

    work = Path(tempfile.mkdtemp(prefix="neoview-bench-"))
    ini = str(work / "settings.ini")
    mw.QSettings = lambda *_a, **_k: QSettings(ini, QSettings.Format.IniFormat)
    if thumbs:
        # A user who left the Thumbnails panel open last session.
        QSettings(ini, QSettings.Format.IniFormat).setValue("window/show_thumbnails", True)

    win = mw.MainWindow()
    win.resize(1400, 900)
    win.show()
    for _ in range(5):
        app.processEvents()

    prof = None
    if profile:
        import cProfile

        prof = cProfile.Profile()
        prof.enable()

    t0 = time.perf_counter()
    win._open_file(str(pdf))
    t1 = time.perf_counter()

    loop = QEventLoop()
    probe_at: list[float] = []

    def _probe():
        probe_at.append(time.perf_counter())
        loop.quit()

    QTimer.singleShot(0, _probe)
    loop.exec()
    t2 = probe_at[0]

    # Heartbeat: how long can the loop stall while deferred open work runs?
    beats: list[float] = []
    hb = QTimer()
    hb.setInterval(20)
    hb.timeout.connect(lambda: beats.append(time.perf_counter()))
    hb.start()
    elapsed = QElapsedTimer()
    elapsed.start()
    stop = QEventLoop()
    QTimer.singleShot(3000, stop.quit)
    stop.exec()
    hb.stop()
    gaps = [b - a for a, b in zip([t2] + beats[:-1], beats)]

    if prof is not None:
        prof.disable()
        prof.dump_stats(profile)

    view = win.current_view()
    pages = view.page_count
    result = {
        "file": pdf.name,
        "pages": pages,
        "thumbs_panel": win._thumbs_dock.isVisible(),
        "open_s": round(t1 - t0, 3),
        "responsive_s": round(t2 - t1, 3),
        "max_stall_s": round(max(gaps) if gaps else 0.0, 3),
        "peak_rss_mb": _peak_rss_mb(),
    }
    if stress:
        print(json.dumps(result), flush=True)
        _stress(app, win, budget_s=90)
        result["peak_rss_after_stress_mb"] = _peak_rss_mb()
    win.close()
    return result


def conditions() -> dict:
    import fitz
    import PySide6

    return {
        "machine": platform.processor() or platform.machine(),
        "nproc": os.cpu_count(),
        "python": platform.python_version(),
        "pymupdf": fitz.VersionBind,
        "pyside6": PySide6.__version__,
        "qpa": os.environ.get("QT_QPA_PLATFORM", "offscreen"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("dir")
    g.add_argument("--pages", type=int, default=650)
    b = sub.add_parser("bench")
    b.add_argument("dir")
    b.add_argument("--runs", type=int, default=3)
    b.add_argument("--timeout", type=float, default=120.0)
    o = sub.add_parser("open")
    o.add_argument("pdf")
    o.add_argument("--profile")
    o.add_argument("--stress", action="store_true", help="also scroll/search/zoom/reopen")
    o.add_argument("--thumbs", action="store_true", help="start with the Thumbnails panel open")
    b.add_argument("--thumbs", action="store_true", help="start with the Thumbnails panel open")
    args = ap.parse_args()

    if args.cmd == "generate":
        for p in generate(Path(args.dir), args.pages):
            print(f"{p}  {p.stat().st_size / 1e6:.1f} MB")
        return 0
    if args.cmd == "open":
        import faulthandler

        # If the child wedges, dump every thread's stack to stderr every 30 s.
        faulthandler.dump_traceback_later(30, repeat=True)
        print(json.dumps(open_and_measure(Path(args.pdf), args.profile, args.stress, args.thumbs)))
        return 0

    print(json.dumps({"conditions": conditions(), "runs": args.runs}))
    for pdf in sorted(Path(args.dir).glob("*.pdf")):
        for run in range(args.runs):
            cmd = [sys.executable, __file__, "open", str(pdf)] + (["--thumbs"] if args.thumbs else [])
            start = time.perf_counter()
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
                line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
                rec = json.loads(line) if line.startswith("{") else {"error": proc.stderr[-500:]}
            except subprocess.TimeoutExpired:
                rec = {"file": pdf.name, "error": f"TIMEOUT after {args.timeout}s"}
            rec["run"] = run + 1
            rec["wall_s"] = round(time.perf_counter() - start, 2)
            print(json.dumps(rec), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
