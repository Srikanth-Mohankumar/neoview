from contextlib import contextmanager
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog

from neoview.ui.tools import page_pngs


def document():
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page(width=144, height=72)
        page.insert_text((10, 30), f"Page {index + 1}")
    return doc


def test_real_png_dimensions_order_and_source_unchanged(tmp_path):
    output = tmp_path / "images"
    with document() as doc:
        before = doc.tobytes(no_new_id=True)
        result = page_pngs.export_pages_png(doc, "3, 1", 144, str(output))
        assert result == str(output)
        assert sorted(p.name for p in output.iterdir()) == ["page-0001.png", "page-0003.png"]
        for path in output.iterdir():
            pixmap = fitz.Pixmap(str(path))
            assert (pixmap.width, pixmap.height) == (288, 144)
            assert pixmap.n == 3
        assert doc.tobytes(no_new_id=True) == before


@pytest.mark.parametrize("ranges", ["0", "1-4", "1,1", "", "2-1"])
def test_invalid_ranges_write_nothing(tmp_path, ranges):
    with document() as doc, pytest.raises(ValueError):
        page_pngs.export_pages_png(doc, ranges, 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


@pytest.mark.parametrize("dpi", [0, 35, 301, 72.5, True])
def test_invalid_dpi(tmp_path, dpi):
    with document() as doc, pytest.raises(ValueError, match="DPI"):
        page_pngs.export_pages_png(doc, "1", dpi, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


def test_pixel_budget_checked_before_render(tmp_path, monkeypatch):
    monkeypatch.setattr(page_pngs, "MAX_TOTAL_PIXELS", 20_000)
    monkeypatch.setattr(fitz.Page, "get_pixmap", lambda *_a, **_k: pytest.fail("rendered early"))
    with document() as doc, pytest.raises(ValueError, match="lower DPI"):
        page_pngs.export_pages_png(doc, "1-3", 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


def test_existing_empty_directory_never_overwritten(tmp_path):
    output = tmp_path / "images"
    output.mkdir()
    with document() as doc, pytest.raises(FileExistsError):
        page_pngs.export_pages_png(doc, "1", 72, str(output))
    assert output.is_dir() and list(output.iterdir()) == []


def test_render_failure_cleans_partial_images(tmp_path, monkeypatch):
    original = fitz.Page.get_pixmap

    def fail_second(page, *args, **kwargs):
        if page.number == 1:
            raise OSError("render failed")
        return original(page, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_pixmap", fail_second)
    with document() as doc, pytest.raises(OSError, match="render failed"):
        page_pngs.export_pages_png(doc, "1-3", 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


def test_publish_failure_cleans_reserved_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(page_pngs.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("publish")))
    with document() as doc, pytest.raises(OSError, match="publish"):
        page_pngs.export_pages_png(doc, "1", 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


@pytest.mark.parametrize("cancel", ["range", "dpi", "folder", None])
def test_run_dialog_flow(tmp_path, monkeypatch, cancel):
    messages = []
    window = SimpleNamespace(_status=SimpleNamespace(showMessage=lambda *args: messages.append(args)))

    @contextmanager
    def snapshot(_window):
        with document() as doc:
            yield doc, None, str(tmp_path / "source.pdf")

    monkeypatch.setattr(page_pngs, "snapshot", snapshot)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("2", cancel != "range"))
    monkeypatch.setattr(QInputDialog, "getInt", lambda *_: (72, cancel != "dpi"))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: "" if cancel == "folder" else str(tmp_path))
    assert page_pngs.run(window) is None
    output = tmp_path / "source-pages"
    assert output.exists() == (cancel is None)
    assert bool(messages) == (cancel is None)
    if output.exists():
        assert [p.name for p in output.iterdir()] == ["page-0002.png"]


def test_mid_publish_failure_removes_all_published_files(tmp_path, monkeypatch):
    original = page_pngs.os.replace
    calls = 0

    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second publication failed")
        return original(*args)

    monkeypatch.setattr(page_pngs.os, "replace", fail_second)
    with document() as doc, pytest.raises(OSError, match="publication failed"):
        page_pngs.export_pages_png(doc, "1-3", 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []
