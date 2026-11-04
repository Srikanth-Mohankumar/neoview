"""Annotation reports preserve review text while neutralizing document markup."""
import copy

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.models.view_state import AnnotationRecord
from neoview.ui.main_window import MainWindow
from neoview.ui.tools import annotations_markdown as tool


def record(page=0, text="Review text", **kwargs):
    return AnnotationRecord("record", "note", page, (1, 2, 3, 4), contents=text, **kwargs)


def test_report_groups_sources_by_page_preserving_unicode():
    editable = [record(2, "Later"), record(0, "Unicode \u03bb\nSecond line", color="#abcdef")]
    native = [record(0, "Native comment")]
    original = copy.deepcopy(editable)
    text = tool.annotation_report(editable, native)
    assert text.index("## Page 1") < text.index("## Page 3")
    assert "## Page 0" not in text
    assert "Annotation 1 (NeoView)" in text and "Annotation 2 (Native PDF)" in text
    assert "Unicode \u03bb  \nSecond line" in text
    assert "Color: \\#abcdef" in text
    assert "Bounds (x, y, width, height): 1, 2, 3, 4" in text
    assert editable == original


def test_user_markup_is_plain_text_including_multiline_html_and_links():
    contents = '<script>alert("x")</script>\n![image](https://bad.example/x)\n# heading\n```html\n<b>bold</b>\n```'
    text = tool.annotation_report([record(text=contents)], [])
    assert "<script>" not in text and "<b>" not in text
    assert '&lt;script&gt;' in text
    assert '\\!\\[image\\]\\(https\\://bad\\.example/x\\)' in text
    assert "\\# heading" in text
    assert "```" not in text
    assert "\\`\\`\\`html" in text


def test_backslashes_and_html_entities_are_preserved_as_plain_review_text():
    assert tool.plain_markdown(r"\*[x]&amp;<a>") == r"\\\*\[x\]&amp;amp;&lt;a&gt;"


@pytest.fixture
def opened(tmp_path, qtbot):
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(source))
    sidecar = tmp_path / "source.pdf.neoview.json"
    sidecar.write_text('{"version":1,"annotations":[],"bookmarks":[]}')
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(source))
    window.current_context().sidecar_state.annotations = [record(text="Editable")]
    window.current_context().native_annotations = [record(text="Native")]
    return window, source, sidecar


def test_run_writes_both_sources_without_modifying_source(opened, tmp_path, monkeypatch):
    window, source, sidecar = opened
    before = source.read_bytes(), sidecar.read_bytes()
    target = tmp_path / "review.md"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    tool.run(window)
    report = target.read_text(encoding="utf-8")
    assert "Editable" in report and "Native" in report
    assert "NeoView" in report and "Native PDF" in report
    assert before == (source.read_bytes(), sidecar.read_bytes())


def test_dialog_mutation_does_not_change_export_snapshot(opened, tmp_path, monkeypatch):
    window, _, _ = opened
    target = tmp_path / "review.md"

    def destination(*_):
        window.current_context().sidecar_state.annotations[0].contents = "changed"
        window.current_context().native_annotations.clear()
        return str(target), ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", destination)
    tool.run(window)
    report = target.read_text()
    assert "Editable" in report and "Native" in report and "changed" not in report


def test_empty_annotations_do_not_open_save_dialog(opened, monkeypatch):
    window, _, _ = opened
    window.current_context().sidecar_state.annotations.clear()
    window.current_context().native_annotations.clear()
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: pytest.fail("unexpected dialog"))
    tool.run(window)
    assert messages == ["No annotations to export."]


def test_cancel_does_not_write(opened, tmp_path, monkeypatch):
    window, _, _ = opened
    before = set(tmp_path.iterdir())
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: ("", ""))
    tool.run(window)
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("which", ["pdf", "sidecar"])
def test_source_alias_is_rejected(opened, monkeypatch, which):
    window, source, sidecar = opened
    target = source if which == "pdf" else sidecar
    before = target.read_bytes()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))
    with pytest.raises(ValueError, match="separate"):
        tool.run(window)
    assert target.read_bytes() == before


def test_failed_atomic_replace_preserves_old_report_and_cleans_temp(opened, tmp_path, monkeypatch):
    from neoview.ui import tool_support

    window, _, _ = opened
    target = tmp_path / "review.md"
    target.write_text("Old report")
    before = set(tmp_path.iterdir())
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(target), ""))

    def fail(*_):
        raise OSError("simulated failure")

    monkeypatch.setattr(tool_support.os, "replace", fail)
    with pytest.raises(OSError, match="simulated"):
        tool.run(window)
    assert target.read_text() == "Old report"
    assert set(tmp_path.iterdir()) == before
