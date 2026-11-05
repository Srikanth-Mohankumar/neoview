import os
from copy import deepcopy

import fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QWidget

from neoview.models.view_state import AnnotationRecord
from neoview.ui.annotation_filter import annotation_matches, build_filter_controls


@pytest.mark.parametrize(
    "contents,kind,query,expected",
    [
        ("Review this paragraph", "all", "REVIEW", True),
        ("Review this paragraph", "note", " paragraph ", True),
        ("Review this paragraph", "highlight", "review", False),
        ("Review this paragraph", "all", "missing", False),
        ("Stra\u00dfe \u00c9tude", "all", "STRASSE", True),
        ("Stra\u00dfe \u00c9tude", "note", "\u00e9TUDE", True),
        ("", "all", "", True),
        ("", "note", " \t ", True),
        ("", "note", "review", False),
        ("", "highlight", "", False),
    ],
)
def test_annotation_matches(contents, kind, query, expected):
    record = AnnotationRecord("example", "note", 0, (1, 2, 3, 4), contents=contents)
    before = deepcopy(record)
    assert annotation_matches(record, kind, query) is expected
    assert record == before


def test_filter_controls_preserve_type_choice_and_expose_clearable_text(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    combo = QComboBox()
    combo.addItems(["All", "Note", "Highlight"])
    combo.setCurrentText("Note")
    container, text_filter = build_filter_controls(combo, parent)

    assert container.parent() is parent
    assert container.layout().itemAt(0).widget() is combo
    assert container.layout().itemAt(1).widget() is text_filter
    assert combo.currentText() == "Note"
    assert text_filter.objectName() == "annotation_text_filter"
    assert text_filter.accessibleName() == "Filter annotation text"
    assert text_filter.placeholderText() == "Filter annotation text"
    assert text_filter.isClearButtonEnabled()
    with qtbot.waitSignal(text_filter.textChanged):
        text_filter.setText("Review")
    with qtbot.waitSignal(text_filter.textChanged):
        text_filter.clear()
    assert text_filter.text() == ""


def _make_pdf(path, native_text=""):
    with fitz.open() as doc:
        page = doc.new_page()
        if native_text:
            page.add_text_annot((20, 20), native_text)
        doc.save(path)


def _row_ids(window):
    return [
        window._annotation_list.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(window._annotation_list.count())
    ]


def test_sidebar_combines_filters_for_native_and_editable_records(qtbot, tmp_path, monkeypatch):
    from neoview.ui.main_window import MainWindow

    path = tmp_path / "notes.pdf"
    _make_pdf(path, "Native REVIEW")
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(path))
    context = window.current_context()
    context.sidecar_state.annotations = [
        AnnotationRecord("editable", "highlight", 0, (1, 2, 30, 40), contents="Review"),
        AnnotationRecord("other", "note", 0, (1, 2, 30, 40), contents="Other"),
    ]
    before = deepcopy((context.sidecar_state, context.native_annotations))
    native_id = context.native_annotations[0].id
    monkeypatch.setattr(
        window.current_view(), "set_annotations",
        lambda *_: pytest.fail("filtering must not rebuild annotation scene"),
    )
    window._annotation_text_filter.setText("review")
    assert set(_row_ids(window)) == {"editable", native_id}
    window._annotation_filter.setCurrentText("Note")
    assert _row_ids(window) == [native_id]
    window._annotation_text_filter.setText("missing")
    assert _row_ids(window) == []
    assert "match" in window._annotations_hint.text().lower()
    window._annotation_text_filter.clear()
    assert set(_row_ids(window)) == {"other", native_id}
    assert (context.sidecar_state, context.native_annotations) == before


def test_filter_remains_applied_across_tabs_and_reload(qtbot, tmp_path):
    from neoview.ui.main_window import MainWindow

    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    _make_pdf(first, "Review first")
    _make_pdf(second, "Other second")
    window = MainWindow()
    qtbot.addWidget(window)
    window._open_file(str(first))
    first_index = window._tabs.currentIndex()
    window._annotation_text_filter.setText("review")
    assert window._annotation_list.count() == 1
    window._open_file(str(second))
    assert window._annotation_list.count() == 0
    window._tabs.setCurrentIndex(first_index)
    assert window._annotation_list.count() == 1

    replacement = tmp_path / "replacement.pdf"
    _make_pdf(replacement, "Changed native text")
    if os.name == "nt":
        # Windows keeps the source locked while PyMuPDF has an open reader.
        view = window.current_view()
        view._begin_render_generation()
        view._doc.close()
        view._doc = None
    replacement.replace(first)
    window._do_reload(force=True)
    assert window._annotation_text_filter.text() == "review"
    assert window._annotation_list.count() == 0
    window._annotation_text_filter.setText("changed")
    assert window._annotation_list.count() == 1
