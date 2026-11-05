import csv
import io
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.models.view_state import SearchMatch
from neoview.ui.tools.search_results_csv import run, search_results_csv


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def make_window(source):
    context = SimpleNamespace(file_path=str(source), search_query="caf\u00e9",
                              search_results=[SearchMatch(1, (1, 2, 3, 4), 'a,"b"\n\u03bb')])
    return SimpleNamespace(current_context=lambda: context,
                           current_view=lambda: SimpleNamespace(document=SimpleNamespace(page_count=2)),
                           _search_operation=None, _active_search_text=lambda: "caf\u00e9",
                           _search_results_are_current=lambda: True)


def test_csv_quotes_unicode_and_escapes_spreadsheet_text():
    result = rows(search_results_csv(" \ufeff=SUM(A1)", [
        SearchMatch(1, (1, 2, 3, 4), '\t@formula,"\n\u03bb'),
    ], 2))[0]
    assert result == dict(page="2", query="' \ufeff=SUM(A1)", snippet="'\t@formula,\"\n\u03bb",
                          x_pt="1.0", y_pt="2.0", width_pt="3.0", height_pt="4.0")


@pytest.mark.parametrize("page", [-1, 2, True, 0.5])
def test_invalid_page_rejected(page):
    with pytest.raises(ValueError, match="page"):
        search_results_csv("q", [SearchMatch(page, (1, 2, 3, 4), "s")], 2)


@pytest.mark.parametrize("bounds", [(1, 2, -3, 4), (1, 2, 3, float("nan")),
                                         (1, 2, float("inf"), 4), (1, 2), (1, 2, "bad", 4)])
def test_invalid_bounds_rejected(bounds):
    with pytest.raises(ValueError, match="bounds"):
        search_results_csv("q", [SearchMatch(0, bounds, "s")], 1)


@pytest.mark.parametrize("state", ["active", "debouncing", "changed", "stale", "empty"])
def test_incomplete_or_empty_search_informs_without_dialog(tmp_path, monkeypatch, state):
    window = make_window(tmp_path / "source.pdf")
    if state == "active":
        window._search_operation = {}
    elif state == "debouncing":
        window._search_timer = SimpleNamespace(isActive=lambda: True)
    elif state == "changed":
        window._active_search_text = lambda: "different"
    elif state == "stale":
        window._search_results_are_current = lambda: False
    else:
        window.current_context().search_results = []
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("Unexpected dialog"))
    assert run(window) is None
    assert len(messages) == 1


def test_snapshot_survives_changes_during_dialog(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    sidecar = tmp_path / "source.pdf.neoview.json"
    source.write_bytes(b"PDF unchanged")
    sidecar.write_bytes(b"sidecar unchanged")
    target = tmp_path / "r\u00e9sults.csv"
    window = make_window(source)
    messages = []
    window._status = SimpleNamespace(showMessage=lambda *args: messages.append(args))

    def select(*_):
        context = window.current_context()
        context.search_query = "changed"
        context.search_results[0].snippet = "changed"
        context.search_results.clear()
        context.file_path = str(target)
        window.current_view = lambda: pytest.fail("Live document accessed after dialog")
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", select)
    assert run(window) is None
    result = rows(target.read_text(encoding="utf-8"))[0]
    assert result["query"] == "caf\u00e9"
    assert result["snippet"] == 'a,"b"\n\u03bb'
    assert result["page"] == "2"
    assert source.read_bytes() == b"PDF unchanged"
    assert sidecar.read_bytes() == b"sidecar unchanged"
    assert messages == [("Search results exported.", 3000)]


def test_cancel_leaves_existing_output(tmp_path, monkeypatch):
    target = tmp_path / "source-search-results.csv"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    run(make_window(tmp_path / "source.pdf"))
    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("kind", ["source", "sidecar", "hardlink"])
def test_source_aliases_rejected(tmp_path, monkeypatch, kind):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"source")
    sidecar = tmp_path / "source.pdf.neoview.json"
    sidecar.write_bytes(b"sidecar")
    target = source if kind == "source" else sidecar
    if kind == "hardlink":
        target = tmp_path / "alias.csv"
        try:
            target.hardlink_to(source)
        except OSError:
            pytest.skip("Hard links unavailable")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    with pytest.raises(ValueError, match="separate"):
        run(make_window(source))
    assert source.read_bytes() == b"source"
    assert sidecar.read_bytes() == b"sidecar"


def test_failed_write_keeps_existing_output_and_removes_temporary(tmp_path, monkeypatch):
    from neoview.ui import tool_support

    target = tmp_path / "report.csv"
    target.write_text("original", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))

    def fail(*_):
        raise OSError("Cannot replace")

    monkeypatch.setattr(tool_support.os, "replace", fail)
    with pytest.raises(OSError, match="Cannot replace"):
        run(make_window(tmp_path / "source.pdf"))
    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".neoview-export-*"))
