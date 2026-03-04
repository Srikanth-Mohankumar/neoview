"""Tests for PdfView performance mode toggle and pausing behavior."""

import fitz
from PySide6.QtWidgets import QApplication

from neoview.ui.pdf_view import PdfView


def _make_pdf(tmp_path):
    """Create a minimal 1-page PDF and return its path."""
    path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_performance_mode_default_off(tmp_path):
    view = PdfView()
    assert view.is_performance_mode() is False
    view.close()


def test_set_performance_mode_on():
    view = PdfView()
    view.set_performance_mode(True)
    assert view.is_performance_mode() is True
    view.close()


def test_set_performance_mode_emits_signal():
    view = PdfView()
    received = []
    view.performance_mode_toggled.connect(lambda v: received.append(v))
    view.set_performance_mode(True)
    view.set_performance_mode(False)
    assert received == [True, False]
    view.close()


def test_perf_mode_blocks_scroll_rerender(tmp_path, monkeypatch):
    view = PdfView()
    view.open_document(_make_pdf(tmp_path))
    QApplication.processEvents()

    view.set_performance_mode(True)

    monkeypatch.setattr(view, "_visible_page_needs_rerender", lambda: True)
    starts = []
    monkeypatch.setattr(view._rerender_timer, "start", lambda ms=0: starts.append(ms))

    view._on_scroll()
    assert starts == [], f"Expected no timer starts, got {starts}"
    view.close()


def test_perf_mode_allows_scroll_rerender_when_off(tmp_path, monkeypatch):
    view = PdfView()
    view.open_document(_make_pdf(tmp_path))
    QApplication.processEvents()

    # perf mode is off by default
    monkeypatch.setattr(view, "_visible_page_needs_rerender", lambda: True)
    starts = []
    monkeypatch.setattr(view._rerender_timer, "start", lambda ms=0: starts.append(ms))

    view._on_scroll()
    assert 40 in starts, f"Expected timer start(40), got {starts}"
    view.close()


def test_perf_mode_blocks_zoom_rerender(tmp_path, monkeypatch):
    view = PdfView()
    view.open_document(_make_pdf(tmp_path))
    QApplication.processEvents()

    view.set_performance_mode(True)

    starts = []
    monkeypatch.setattr(view._rerender_timer, "start", lambda ms=0: starts.append(ms))

    view.set_zoom(1.5)
    assert 55 not in starts, f"Expected no timer start(55), got {starts}"
    view.close()


def test_perf_mode_off_resumes_rerender_if_needed(tmp_path, monkeypatch):
    view = PdfView()
    view.open_document(_make_pdf(tmp_path))
    QApplication.processEvents()

    view.set_performance_mode(True)

    monkeypatch.setattr(view, "_visible_page_needs_rerender", lambda: True)
    starts = []
    monkeypatch.setattr(view._rerender_timer, "start", lambda ms=0: starts.append(ms))

    view.set_performance_mode(False)
    assert 40 in starts, f"Expected timer start(40), got {starts}"
    view.close()


def test_perf_mode_off_no_rerender_if_not_needed(tmp_path, monkeypatch):
    view = PdfView()
    view.open_document(_make_pdf(tmp_path))
    QApplication.processEvents()

    view.set_performance_mode(True)

    monkeypatch.setattr(view, "_visible_page_needs_rerender", lambda: False)
    starts = []
    monkeypatch.setattr(view._rerender_timer, "start", lambda ms=0: starts.append(ms))

    view.set_performance_mode(False)
    assert starts == [], f"Expected no timer starts, got {starts}"
    view.close()
