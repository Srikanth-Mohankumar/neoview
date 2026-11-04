import copy
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.ui.tools import import_annotations_json as tool


def payload():
    return {"version": 1, "annotations": [asdict(AnnotationRecord(
        "original", "freehand", 1, (1, 2, 30, 40), contents="Review note", points=[[1, 2], [3, 4]],
        extra={"tag": [True, None, 4]}, border_color="#abc", font_size=14,
    ))]}


def test_import_preserves_fields_and_assigns_fresh_ids():
    source = payload()
    before = copy.deepcopy(source)
    first = tool.parse_annotations(source, 3)[0]
    second = tool.parse_annotations(source, 3)[0]
    expected = copy.deepcopy(before["annotations"][0])
    actual = asdict(first)
    assert actual.pop("id") != expected.pop("id")
    assert actual == expected
    assert first.id != second.id
    assert source == before


@pytest.mark.parametrize(("key", "value"), [
    ("page", 3), ("page", -1), ("page", True), ("page", "1"),
    ("type", "unsupported"), ("type", []), ("rect", [0, 0, float("nan"), 1]),
    ("rect", [0, 0, -1, 1]), ("rect", [0, 0, 1]), ("rect", [0, 0, True, 1]),
    ("opacity", float("inf")), ("opacity", 2), ("font_size", 0),
    ("border_width", "2"), ("points", [[0, float("nan")]]),
    ("contents", 5), ("color", "red"), ("extra", {"bad": float("inf")}),
    ("extra", []), ("unexpected", 1),
])
def test_invalid_record_rejects_entire_payload(key, value):
    source = payload()
    source["annotations"].append(copy.deepcopy(source["annotations"][0]))
    source["annotations"][1][key] = value
    with pytest.raises(ValueError):
        tool.parse_annotations(source, 3)


@pytest.mark.parametrize("data", [
    {"version": True, "annotations": []}, {"version": 2, "annotations": []},
    {"version": 1, "annotations": {}}, {"version": 1},
    {"version": 1, "annotations": [], "unknown": 3},
])
def test_bad_export_structure(data):
    with pytest.raises(ValueError):
        tool.parse_annotations(data, 3)


def test_load_limits_and_duplicate_keys(tmp_path, monkeypatch):
    path = tmp_path / "notes.json"
    path.write_text('{"version":1,"version":1,"annotations":[]}')
    with pytest.raises(ValueError, match="Duplicate"):
        tool.load_annotations(path, 3)
    monkeypatch.setattr(tool, "MAX_FILE_BYTES", 5)
    with pytest.raises(ValueError, match="size limit"):
        tool.load_annotations(path, 3)


def fake_window():
    old = AnnotationRecord("old", "note", 0, (1, 1, 10, 10))
    bookmark = BookmarkRecord("b", "First", 0, 0)
    native = AnnotationRecord("native-0", "note", 0, (2, 2, 10, 10))
    context = SimpleNamespace(file_path="/tmp/source.pdf", sidecar_state=DocumentSidecarState(
        annotations=[old], bookmarks=[bookmark]), native_annotations=[native])
    calls = []
    view = SimpleNamespace(document=SimpleNamespace(page_count=3),
                           set_annotations=lambda records: calls.append(records))
    window = SimpleNamespace(current_context=lambda: context, current_view=lambda: view,
                             _status=SimpleNamespace(showMessage=lambda *_: None),
                             _populate_annotation_list=lambda: None, _populate_bookmarks=lambda: None,
                             _mark_sidecar_dirty=lambda _: calls.append("dirty"))
    return window, context, calls


def test_run_appends_atomically_preserving_native_and_bookmarks(tmp_path, monkeypatch):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(payload()))
    window, context, calls = fake_window()
    original = context.sidecar_state
    monkeypatch.setattr(tool.QFileDialog, "getOpenFileName", lambda *_: (str(path), ""))
    assert tool.run(window) is None
    assert len(context.sidecar_state.annotations) == 2
    assert context.sidecar_state.annotations[0].id == "old"
    assert context.sidecar_state.bookmarks == original.bookmarks
    assert context.native_annotations[0].id == "native-0"
    assert len(original.annotations) == 1
    assert calls[-1] == "dirty"
    assert calls[0][-1] is context.native_annotations[0]


def test_run_invalid_and_cancel_do_not_mutate(tmp_path, monkeypatch):
    path = tmp_path / "bad.json"
    data = payload()
    data["annotations"][0]["page"] = 99
    path.write_text(json.dumps(data))
    window, context, calls = fake_window()
    original = context.sidecar_state
    monkeypatch.setattr(tool.QFileDialog, "getOpenFileName", lambda *_: (str(path), ""))
    with pytest.raises(ValueError):
        tool.run(window)
    assert context.sidecar_state is original and not calls
    monkeypatch.setattr(tool.QFileDialog, "getOpenFileName", lambda *_: ("", ""))
    assert tool.run(window) is None
    assert context.sidecar_state is original and not calls
