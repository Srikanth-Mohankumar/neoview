import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.models.view_state import BookmarkRecord, DocumentSidecarState
from neoview.ui.tools.export_bookmarks_json import render_bookmarks, run


def records():
    return [BookmarkRecord("original-id", "Caf\u00e9 \"quoted\"\nsecond line", 2, 23.5,
                           "2026-11-04T00:00:00Z")]


def window_for(source, bookmarks=None):
    context = SimpleNamespace(file_path=str(source), sidecar_state=DocumentSidecarState(
        bookmarks=records() if bookmarks is None else bookmarks,
    ))
    return SimpleNamespace(current_context=lambda: context), context


def test_transfer_format_uses_one_based_pages_and_preserves_fields():
    bookmarks = records()
    before = copy.deepcopy(bookmarks)
    text = render_bookmarks(bookmarks)
    assert json.loads(text) == {
        "version": 1, "bookmarks": [{
            "title": "Caf\u00e9 \"quoted\"\nsecond line", "page": 3, "y": 23.5,
            "created_at": "2026-11-04T00:00:00Z",
        }],
    }
    assert "Caf\u00e9" in text
    assert bookmarks == before


@pytest.mark.parametrize("field,value", [
    ("page", -1), ("page", True), ("page", 1.2),
    ("y", float("nan")), ("y", float("inf")), ("y", -1), ("y", True),
    ("title", None), ("created_at", 12),
])
def test_invalid_records_are_not_serialized(field, value):
    bookmark = records()[0]
    setattr(bookmark, field, value)
    with pytest.raises(ValueError):
        render_bookmarks([bookmark])


def test_run_writes_portable_utf8_and_leaves_originals_unchanged(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    sidecar = Path(str(source) + ".neoview.json")
    target = tmp_path / "bookmarks.json"
    source.write_bytes(b"original PDF")
    sidecar.write_text("original sidecar", encoding="utf-8")
    window, context = window_for(source)
    original = copy.deepcopy(context.sidecar_state)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    assert run(window) is None
    assert json.loads(target.read_text(encoding="utf-8"))["bookmarks"][0]["page"] == 3
    assert source.read_bytes() == b"original PDF"
    assert sidecar.read_text(encoding="utf-8") == "original sidecar"
    assert context.sidecar_state == original


def test_run_snapshot_survives_state_changes_during_dialog(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    target = tmp_path / "bookmarks.json"
    source.write_bytes(b"pdf")
    window, context = window_for(source)

    def choose(*_):
        context.sidecar_state.bookmarks[0].title = "Changed while choosing"
        context.sidecar_state.bookmarks.clear()
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    run(window)
    assert json.loads(target.read_text(encoding="utf-8"))["bookmarks"][0]["title"].startswith("Caf")


def test_empty_bookmarks_do_not_prompt_or_write(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    window, _ = window_for(source, [])
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("No save dialog"))
    run(window)
    assert messages == ["No bookmarks to export."]
    assert not [path for path in tmp_path.iterdir() if path.is_file()]


def test_cancel_preserves_existing_output(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    target = tmp_path / "bookmarks.json"
    target.write_text("existing", encoding="utf-8")
    window, _ = window_for(source)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    run(window)
    assert target.read_text(encoding="utf-8") == "existing"


@pytest.mark.parametrize("kind", ["pdf", "sidecar", "hardlink"])
def test_source_aliases_are_protected(tmp_path, monkeypatch, kind):
    source = tmp_path / "source.pdf"
    sidecar = Path(str(source) + ".neoview.json")
    source.write_bytes(b"PDF")
    sidecar.write_text("sidecar", encoding="utf-8")
    target = source if kind == "pdf" else sidecar
    if kind == "hardlink":
        target = tmp_path / "alias.json"
        try:
            target.hardlink_to(source)
        except OSError:
            pytest.skip("Hard links unavailable")
    window, _ = window_for(source)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    with pytest.raises(ValueError, match="separate"):
        run(window)
    assert source.read_bytes() == b"PDF"
    assert sidecar.read_text(encoding="utf-8") == "sidecar"


def test_atomic_failure_preserves_output_and_removes_temporary_file(tmp_path, monkeypatch):
    import neoview.ui.tool_support as support

    source = tmp_path / "source.pdf"
    target = tmp_path / "bookmarks.json"
    source.write_bytes(b"PDF")
    target.write_text("existing", encoding="utf-8")
    window, _ = window_for(source)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))

    def fail_replace(*_):
        raise OSError("simulated failure")

    monkeypatch.setattr(support.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        run(window)
    assert target.read_text(encoding="utf-8") == "existing"
    assert not list(tmp_path.glob(".neoview-export-*"))


def test_export_import_round_trip_preserves_values_and_replaces_ids():
    from neoview.ui.tools.import_bookmarks_json import parse_bookmarks

    original = records()[0]
    restored = parse_bookmarks(json.loads(render_bookmarks([original])), 3)[0]
    assert restored.id != original.id
    assert (restored.title, restored.page, restored.y, restored.created_at) == (
        original.title, original.page, original.y, original.created_at,
    )
