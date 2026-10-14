"""Drive a real NeoView MainWindow through the core user flows and save screenshots.

Usage (from the repo root):
    .venv/bin/python .claude/skills/smoke-test-ui/scripts/smoke.py --out <dir> [--pdf file.pdf]
        [--theme light|dark] [--size 1280x800] [--visible]

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
    doc.set_toc([[1, "Introduction", 1], [2, "Background", 1], [1, "Method", 2], [1, "Results", 3]])
    doc.save(str(path))
    doc.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="directory for screenshots")
    ap.add_argument("--pdf", help="PDF to open (default: a generated 3-page PDF)")
    ap.add_argument("--theme", choices=["light", "dark"], default="light")
    ap.add_argument("--size", default="1280x800", help="window size, WIDTHxHEIGHT")
    ap.add_argument("--visible", action="store_true", help="show a real window")
    args = ap.parse_args()
    width, height = (int(v) for v in args.size.lower().split("x"))

    if not args.visible:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["NEOVIEW_THEME"] = args.theme
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="neoview-smoke-"))

    from PySide6.QtCore import QPoint, QRectF, QSettings
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    import neoview.ui.main_window as main_window_mod
    from neoview.theme import apply_theme
    from neoview.ui.main_window import MainWindow
    from neoview.ui.pdf_view import ToolMode

    # MainWindow builds QSettings("NeoView", "NeoView"), which is NativeFormat: the
    # real ~/.config file on Linux, the registry on Windows. QSettings.setPath cannot
    # redirect the registry, so swap in an INI file under the temp dir instead.
    ini_path = str(work / "neoview-settings.ini")
    main_window_mod.QSettings = lambda *_a, **_k: QSettings(ini_path, QSettings.Format.IniFormat)

    apply_theme(app, args.theme)  # same setup as app.main: Fusion, palette, Inter, stylesheet

    pdf = Path(args.pdf).resolve() if args.pdf else work / "smoke.pdf"
    if not args.pdf:
        make_pdf(pdf)

    def pump(ms: int = 150) -> None:
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.01)

    win = MainWindow()
    win.resize(width, height)
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

    def step(name, fn, grab=None):
        try:
            detail = fn() or ""
            results.append({"step": name, "ok": True, "detail": detail, "shot": (grab or shot)(name)})
        except Exception as exc:  # report every failure, keep going
            results.append({
                "step": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc(limit=3), "shot": shot(name),
            })

    def empty_state():
        view = win.current_view()
        assert view.document is None, "a document is open before the first step"
        welcome = getattr(win, "_welcome", None)
        if welcome is not None:
            assert welcome.isVisible(), "welcome panel not shown without a document"
        return "no document"

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
        win._set_search_panel_visible(True)
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

    def inspector():
        win._set_search_panel_visible(False)
        win._set_inspector_visible(True)
        pump(300)
        assert win._info_dock.isVisible(), "inspector not visible"
        return f"W {win._measure_w.text()}, H {win._measure_h.text()}"

    def sidebar(key):
        def run():
            win._set_inspector_visible(False)
            win._show_sidebar_page(key)
            pump(400)
            assert win._sidebar_dock.isVisible(), "sidebar not visible"
            assert win._sidebar.current_key() == key, f"sidebar shows {win._sidebar.current_key()}"
            return key
        return run

    def menus():
        names = []
        for action in win.menuBar().actions():
            menu = action.menu()
            if menu is None:
                continue
            geo = win.menuBar().actionGeometry(action)
            menu.popup(win.menuBar().mapToGlobal(QPoint(geo.left(), geo.bottom())))
            pump(150)
            name = action.text().replace("&", "").lower()
            menu.grab().save(str(out / f"menu-{name}.png"))
            menu.hide()
            names.append(name)
        overflow = getattr(win, "_overflow_menu", None)
        if overflow is not None:
            overflow.popup(win.mapToGlobal(QPoint(width - 260, 60)))
            pump(150)
            overflow.grab().save(str(out / "menu-overflow.png"))
            overflow.hide()
            names.append("overflow")
        assert names, "no menus"
        return ", ".join(names)

    def annotate():
        win._set_inspector_visible(False)
        win._set_sidebar_visible(False)
        win._on_tool_action(ToolMode.ANNOTATE)
        pump(300)
        assert win._ann_toolbar.isVisible(), "annotation toolbar not shown"
        return "annotation toolbar shown"

    def layout_modes():
        win._on_tool_action(ToolMode.HAND)
        actions = getattr(win, "_page_mode_actions", {})
        if not actions or not actions["two-page"].isEnabled():
            return "page modes unavailable"
        actions["two-page"].trigger()
        win._color_mode_actions["night"].trigger()
        win.current_view().fit_page()
        pump(500)
        view = win.current_view()
        assert view.page_mode() == "two-page" and view.color_mode() == "night"
        return "two-page, night"

    def reset_modes():
        actions = getattr(win, "_page_mode_actions", {})
        if actions and actions["continuous"].isEnabled():
            actions["continuous"].trigger()
            win._color_mode_actions["normal"].trigger()
        pump(300)
        return "continuous, normal"

    def two_documents():
        import shutil

        second = work / "smoke-2.pdf"
        shutil.copyfile(pdf, second)
        win._open_file(str(second))
        pump(400)
        bar = win._tabs.tabBar()
        assert win._tabs.count() == 2, f"{win._tabs.count()} tabs"
        assert bar.isVisible(), "tab bar hidden with two documents"
        return "tab bar shown"

    def back_to_one():
        win._close_current_tab()
        pump(300)
        assert not win._tabs.tabBar().isVisible(), "tab bar still shown with one document"
        return "tab bar hidden"

    def reload_doc():
        view = win.current_view()
        assert view.reload_document(), "reload_document returned False"
        pump(300)
        return f"{view.page_count} pages after reload"

    step("empty", empty_state)
    for name, fn in [("open", open_doc), ("zoom", zoom), ("navigate", navigate),
                     ("search", search), ("measure", measure), ("inspector", inspector),
                     ("sidebar-thumbnails", sidebar("thumbnails")), ("sidebar-outline", sidebar("outline")),
                     ("sidebar-bookmarks", sidebar("bookmarks")),
                     ("sidebar-annotations", sidebar("annotations")), ("annotate", annotate),
                     ("two-page-night", layout_modes), ("reset-modes", reset_modes),
                     ("two-documents", two_documents), ("one-document", back_to_one),
                     ("reload", reload_doc)]:
        step(name, fn)
    step("menus", menus)

    def close_doc():
        win._close_current_tab()
        pump(300)
        assert win.current_view().document is None, "document still open"
        welcome = getattr(win, "_welcome", None)
        if welcome is not None:
            assert welcome.isVisible(), "welcome panel not shown after closing"
            return f"{len(welcome.recent_buttons)} recent file(s) offered"
        return "closed"

    step("close", close_doc)

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
