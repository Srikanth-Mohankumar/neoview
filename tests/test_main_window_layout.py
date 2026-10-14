"""MainWindow chrome: panel refreshes, toolbar, sidebar, inspector, menus, theme, capabilities."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication

from neoview.ui.main_window import MainWindow


def _create_pdf(path: Path, pages: int = 2, text_prefix: str = "Page", toc: bool = False) -> None:
    doc = fitz.open()
    for idx in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 120), f"{text_prefix} {idx + 1} sample text search-target")
    if toc:
        doc.set_toc([[1, f"Chapter {i + 1}", i + 1] for i in range(pages)])
    doc.save(str(path))
    doc.close()


@pytest.fixture
def two_pdfs(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _create_pdf(a, pages=2, text_prefix="A", toc=True)
    _create_pdf(b, pages=3, text_prefix="B", toc=True)
    return a, b


def _window(qtbot) -> MainWindow:
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(1280, 800)
    win.show()
    QApplication.processEvents()
    return win


def _count_calls(monkeypatch, win: MainWindow, name: str) -> list[int]:
    calls: list[int] = []
    real = getattr(win, name)

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(win, name, counting)
    return calls


def test_tab_switch_refreshes_each_panel_once(two_pdfs, qtbot, monkeypatch):
    a, b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    win._open_file(str(b))
    QApplication.processEvents()

    outline = _count_calls(monkeypatch, win, "_populate_outline")
    thumbs = _count_calls(monkeypatch, win, "_populate_thumbnails")
    annots = _count_calls(monkeypatch, win, "_populate_annotation_list")

    win._tabs.setCurrentIndex(0)
    QApplication.processEvents()

    assert (len(outline), len(thumbs), len(annots)) == (1, 1, 1)
    # The refresh shows the newly selected document, not the previous one.
    root = win._outline_tree.topLevelItem(0)
    assert root.childCount() == 2
