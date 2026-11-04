import copy
import json
import math

import fitz
import pytest

from neoview.models.view_state import AnnotationRecord, BookmarkRecord
from neoview.ui.main_window import MainWindow
from neoview.ui.tools import import_bookmarks_json as tool


def payload(**changes):
    bookmark = {"title": "A bookmark", "page": 2, "y": 12.5, "created_at": "2026-11-04"}
    bookmark.update(changes)
    return {"version": 1, "bookmarks": [bookmark]}


def test_parse_one_based_pages_all_fields_and_new_ids():
    data = payload(title="Unicode \u03bb", id="old-id")
    first = tool.parse_bookmarks(data, 3)[0]
    second = tool.parse_bookmarks(data, 3)[0]
    assert first.title == "Unicode \u03bb"
    assert first.page == 1 and first.y == 12.5 and first.created_at == "2026-11-04"
    assert first.id != "old-id" and first.id != second.id
    assert data == payload(title="Unicode \u03bb", id="old-id")


@pytest.mark.parametrize("bad", [
    {"page": 0}, {"page": 4}, {"page": True}, {"page": 1.5},
    {"y": -1}, {"y": math.nan}, {"y": math.inf}, {"y": True}, {"y": 10 ** 1000},
    {"title": 2}, {"created_at": None}, {"unknown": "value"}, {"id": 123},
])
def test_invalid_records_are_rejected(bad):
    with pytest.raises(ValueError):
        tool.parse_bookmarks(payload(**bad), 3)


@pytest.mark.parametrize("data", [
    {"version": True, "bookmarks": []}, {"version": 2, "bookmarks": []},
    {"version": 1, "bookmarks": {}}, [], {"version": 1},
    {"version": 1, "bookmarks": [], "other": 1},
])
def test_invalid_envelopes_are_rejected(data):
    with pytest.raises(ValueError):
        tool.parse_bookmarks(data, 3)


def test_limits_and_bom_file(tmp_path, monkeypatch):
    path = tmp_path / "bookmarks.json"
    path.write_text(json.dumps(payload()), encoding="utf-8-sig")
    assert tool.load_bookmarks(str(path), 3)[0].page == 1
    monkeypatch.setattr(tool, "MAX_FILE_BYTES", 10)
    with pytest.raises(ValueError, match="larger"):
        tool.load_bookmarks(str(path), 3)
    monkeypatch.setattr(tool, "MAX_BOOKMARKS", 0)
    with pytest.raises(ValueError, match="at most"):
        tool.parse_bookmarks(payload(), 3)


def window(tmp_path, qtbot):
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        doc.save(str(source))
    win = MainWindow()
    qtbot.addWidget(win)
    win._open_file(str(source))
    ctx = win.current_context()
    ctx.sidecar_state.bookmarks = [BookmarkRecord("original", "Original", 0, 0)]
    ctx.sidecar_state.annotations = [AnnotationRecord("note", "note", 0, (0, 0, 10, 10))]
    return win, source


def test_import_appends_and_refreshes_bookmark_sidebar(tmp_path, qtbot, monkeypatch):
    win, source = window(tmp_path, qtbot)
    original_bytes = source.read_bytes()
    path = tmp_path / "import.json"
    path.write_text(json.dumps(payload()), encoding="utf-8")
    monkeypatch.setattr(tool.QFileDialog, "getOpenFileName", lambda *_: (str(path), ""))
    tool.run(win)
    state = win.current_context().sidecar_state
    assert [b.title for b in state.bookmarks] == ["Original", "A bookmark"]
    assert state.bookmarks[1].page == 1
    assert len(state.annotations) == 1
    assert win._bookmarks_list.count() == 2
    assert win._sidecar_timers[win.current_view()].isActive()
    assert "Imported 1" in win._status.currentMessage()
    assert source.read_bytes() == original_bytes


def test_malformed_late_record_does_not_mutate_state(tmp_path, qtbot, monkeypatch):
    win, _ = window(tmp_path, qtbot)
    before = copy.deepcopy(win.current_context().sidecar_state)
    data = payload()
    data["bookmarks"].append(payload(page=99)["bookmarks"][0])
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(tool.QFileDialog, "getOpenFileName", lambda *_: (str(path), ""))
    with pytest.raises(ValueError):
        tool.run(win)
    assert win.current_context().sidecar_state == before


def test_cancel_leaves_state_alone(tmp_path, qtbot, monkeypatch):
    win, _ = window(tmp_path, qtbot)
    before = copy.deepcopy(win.current_context().sidecar_state)
    monkeypatch.setattr(tool.QFileDialog, "getOpenFileName", lambda *_: ("", ""))
    tool.run(win)
    assert win.current_context().sidecar_state == before


def test_document_switch_during_dialog_rejects_import(tmp_path, qtbot, monkeypatch):
    win, _ = window(tmp_path, qtbot)
    before = copy.deepcopy(win.current_context().sidecar_state)

    def choose(*_):
        win.current_context().file_path = str(tmp_path / "different.pdf")
        return "unused.json", ""

    monkeypatch.setattr(tool.QFileDialog, "getOpenFileName", choose)
    with pytest.raises(ValueError, match="changed"):
        tool.run(win)
    assert win.current_context().sidecar_state == before
