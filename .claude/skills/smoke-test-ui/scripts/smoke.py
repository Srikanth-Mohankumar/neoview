"""Drive a real NeoView MainWindow through the core user flows and save screenshots.

Usage (from the repo root):
    .venv/bin/python .claude/skills/smoke-test-ui/scripts/smoke.py --out <dir> [--pdf file.pdf]
        [--theme light|dark] [--visible]

Runs offscreen unless --visible. MainWindow's QSettings is replaced with a temp INI
file so the user's real recent files, session and window state are never touched.
Prints one JSON object per step and exits 1 if any step failed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

NEEDLE = "needle"


def make_pdf(path: Path) -> None:
    import fitz

    doc = fitz.open()
    for i in range(3):
        page = doc.new_page(width=595, height=842)  # A4 in pt
        page.insert_text((72, 100), f"NeoView smoke test - page {i + 1}", fontsize=18)
        page.insert_text((72, 140), f"The {NEEDLE} is on every page.", fontsize=12)
        page.draw_rect(fitz.Rect(72, 200, 272, 300), color=(0, 0, 1))
    doc.save(str(path))
    doc.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="directory for screenshots")
    ap.add_argument("--pdf", help="PDF to open (default: a generated 3-page PDF)")
    ap.add_argument("--theme", choices=["light", "dark"], default="light")
    ap.add_argument("--visible", action="store_true", help="show a real window")
    args = ap.parse_args()

    if not args.visible:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["NEOVIEW_THEME"] = args.theme
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="neoview-smoke-"))

    from PySide6.QtCore import QRectF, QSettings
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    import neoview.ui.main_window as main_window_mod
    from neoview.theme import DARK_STYLE, LIGHT_STYLE
    from neoview.ui.main_window import MainWindow
    from neoview.ui.pdf_view import ToolMode

    # MainWindow builds QSettings("NeoView", "NeoView"), which is NativeFormat: the
    # real ~/.config file on Linux, the registry on Windows. QSettings.setPath cannot
    # redirect the registry, so swap in an INI file under the temp dir instead.
    ini_path = str(work / "neoview-settings.ini")
    main_window_mod.QSettings = lambda *_a, **_k: QSettings(ini_path, QSettings.Format.IniFormat)

    app.setStyleSheet(DARK_STYLE if args.theme == "dark" else LIGHT_STYLE)

    pdf = Path(args.pdf).resolve() if args.pdf else work / "smoke.pdf"
    if not args.pdf:
        make_pdf(pdf)

    def pump(ms: int = 150) -> None:
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    pump()

    results = []
    shot_no = [0]

    def settle_renders(timeout_s: float = 10.0) -> None:
        """Pump until the current view has no queued page renders (pages render async)."""
        view = win.current_view()
        pending = getattr(view, "pending_render_count", None)
        if not callable(pending):
            return
        end = time.monotonic() + timeout_s
        while pending() and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()

    def shot(name: str) -> str:
        settle_renders()
        shot_no[0] += 1
        path = out / f"{shot_no[0]:02d}-{name}.png"
        win.grab().save(str(path))
        return str(path)

    def step(name, fn):
        try:
            detail = fn() or ""
            results.append({"step": name, "ok": True, "detail": detail, "shot": shot(name)})
        except Exception as exc:  # report every failure, keep going
            results.append({
                "step": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=3), "shot": shot(name),
            })

    def open_doc():
        win._open_file(str(pdf))
        pump(400)
        view = win.current_view()
        assert view.document is not None, "no document loaded"
        assert view.page_count > 0, "page_count is 0"
        return f"{view.page_count} pages"

    def zoom():
        view = win.current_view()
        view.fit_width()
        pump()
        before = view.zoom
        view.zoom_by(1.5)
        pump(300)
        assert view.zoom > before, f"zoom did not grow ({before} -> {view.zoom})"
        return f"{before:.3f} -> {view.zoom:.3f}"

    def navigate():
        view = win.current_view()
        view.last_page()
        pump(300)
        last = view.current_page
        view.first_page()
        pump(300)
        assert view.current_page == 0, f"first_page landed on {view.current_page}"
        return f"last={last}"

    def search():
        win._search_dock.show()
        win._search_input.setText(NEEDLE)
        win._execute_search_current()
        pump(300)
        hits = win._search_results_list.count()
        if not args.pdf:
            assert hits > 0, "no search results for the generated text"
        return f"{hits} result rows"

    def measure():
        view = win.current_view()
        view.fit_page()  # keep the rectangle on screen for the screenshot
        pump(300)
        view.tool = ToolMode.MEASURE
        view._create_selection_on_page(0, QRectF(72, 200, 200, 100))
        pump()
        assert view.selection_rect is not None, "selection_rect is None"
        r = view.selection_rect
        return f"{r.width():.1f} x {r.height():.1f} pt"

    def reload_doc():
        view = win.current_view()
        assert view.reload_document(), "reload_document returned False"
        pump(300)
        return f"{view.page_count} pages after reload"

    for name, fn in [("open", open_doc), ("zoom", zoom), ("navigate", navigate),
                     ("search", search), ("measure", measure), ("reload", reload_doc)]:
        step(name, fn)

    win.close()
    pump()
    for r in results:
        print(json.dumps(r))
    failed = [r["step"] for r in results if not r["ok"]]
    print(json.dumps({"summary": "FAIL" if failed else "PASS", "failed": failed,
                      "screenshots": str(out), "pdf": str(pdf), "theme": args.theme}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
