"""Minimal repro: scrolling a long PDF in PdfView keeps every visited page's full-res pixmap.

Usage (repo root): .venv/bin/python tools/render_memory_repro.py <pdf> [max_pages]

Linux only (reads /proc/self/statm). Stops itself at 2.5 GB RSS.
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)
from neoview.ui.page_item import PageItem  # noqa: E402
from neoview.ui.pdf_view import PdfView  # noqa: E402


def rss_mb():
    with open("/proc/self/statm") as fh:
        return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


view = PdfView()
view.resize(1100, 850)
view.show()
app.processEvents()
view.open_document(sys.argv[1])
view.fit_width()
app.processEvents()
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 60
print(f"zoom={view.zoom:.3f} pages={view.page_count} rss={rss_mb():.0f}MB")
bar = view.verticalScrollBar()
for target in range(limit):
    view.go_to_page(target)
    app.processEvents()
    view._rerender_pages()  # what the 40 ms debounce timer does after a scroll pause
    if target % 10 == 9:
        held = [p for p in view._pages if p.render_scale_factor != 1.0]
        held_bytes = sum(p.pixmap().width() * p.pixmap().height() * 4 for p in held)
        cache_bytes = sum(px.width() * px.height() * 4 for px in PageItem._PIXMAP_CACHE.values())
        shadows = sum(1 for p in view._pages if p.graphicsEffect() is not None)
        p0 = held[0].pixmap()
        print(
            f"visited={target + 1:4d} items_with_fullres_pixmap={len(held):4d} "
            f"held={held_bytes / 2**20:7.0f}MB cache_entries={len(PageItem._PIXMAP_CACHE):3d} "
            f"cache={cache_bytes / 2**20:6.0f}MB shadow_effects={shadows:4d} "
            f"pixmap={p0.width()}x{p0.height()} rss={rss_mb():6.0f}MB"
        )
        if rss_mb() > 2500:
            print("stopping at 2.5 GB RSS")
            break
view.close_document()
app.processEvents()
print(f"after close_document: cache_entries={len(PageItem._PIXMAP_CACHE)} rss={rss_mb():.0f}MB")
