import os
from pathlib import Path
import time

import fitz
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QSlider, QTextEdit

from neoview.models.view_state import AnnotationRecord
from neoview.ui.main_window import MainWindow
from neoview.ui.pdf_view import ToolMode


def _create_pdf(path: Path, pages: int = 1, text_prefix: str = "Page"):
    doc = fitz.open()
    for idx in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 120), f"{text_prefix} {idx + 1} sample text search-target")
    doc.save(str(path))
    doc.close()


def _rewrite_pdf_for_reload(win: MainWindow, path: Path, pages: int = 1, text_prefix: str = "Page"):
    if os.name == "nt":
        view = win.current_view()
        if view._doc is not None:
            view._doc.close()
            view._doc = None
    _create_pdf(path, pages=pages, text_prefix=text_prefix)


def _create_pdf_with_toc(path: Path):
    doc = fitz.open()
    for idx, title in enumerate(["Intro", "Methods", "Results"]):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 120), f"{title} search-target")
    doc.set_toc([[1, "Intro", 1], [1, "Methods", 2], [1, "Results", 3]])
    doc.save(str(path))
    doc.close()


def _viewport_pos_for_pdf_point(view, page_idx: int, x: float, y: float) -> QPoint:
    page = view._pages[page_idx]
    scene = page.pos() + QPointF(x * view.zoom, y * view.zoom)
    return view.mapFromScene(scene)


def test_find_panel_live_search_via_qtbot(tmp_path: Path, qtbot):
    pdf = tmp_path / "find.pdf"
    _create_pdf(pdf, pages=2, text_prefix="Findable")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    win._find_action.trigger()
    assert win._search_dock.isVisible()

    win._search_input.clear()
    qtbot.keyClicks(win._search_input, "search-target")
    qtbot.waitUntil(lambda: len(win.current_context().search_results) >= 2, timeout=3000)

    assert win._search_results_list.count() >= 2

    before = win.current_context().search_index
    qtbot.mouseClick(win._search_next_btn, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: win.current_context().search_index != before, timeout=2000)


def test_explicit_single_char_search_via_return_key(tmp_path: Path, qtbot):
    pdf = tmp_path / "single-char.pdf"
    _create_pdf(pdf, pages=2, text_prefix="Alpha")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    win._find_action.trigger()
    win._search_input.clear()
    qtbot.keyClicks(win._search_input, "a")
    qtbot.waitUntil(lambda: win._search_count_lbl.text() == "Type 2+ chars", timeout=2000)
    assert win.current_context().search_results == []

    qtbot.keyPress(win._search_input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: len(win.current_context().search_results) >= 2, timeout=3000)


def test_outline_toc_navigation_via_qtbot(tmp_path: Path, qtbot, monkeypatch):
    pdf = tmp_path / "outline.pdf"
    _create_pdf_with_toc(pdf)

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))
    win._outline_dock.show()

    jumps = []
    monkeypatch.setattr(win.current_view(), "go_to_page", lambda idx: jumps.append(idx))

    root_toc = win._outline_tree.topLevelItem(0)
    toc_item = root_toc.child(1)
    win._outline_tree.scrollToItem(toc_item)
    rect = win._outline_tree.visualItemRect(toc_item)
    qtbot.mouseClick(win._outline_tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())

    assert jumps == [1]


def test_thumbnail_navigation_via_qtbot(tmp_path: Path, qtbot, monkeypatch):
    pdf = tmp_path / "thumbs.pdf"
    _create_pdf(pdf, pages=3, text_prefix="Thumb")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))
    win._thumbs_dock.show()
    win._render_thumbnail_batch()

    jumps = []
    monkeypatch.setattr(win.current_view(), "go_to_page", lambda idx: jumps.append(idx))

    item = win._thumbs_list.item(2)
    win._thumbs_list.scrollToItem(item)
    win._thumbs_list.setCurrentItem(item)
    qtbot.keyClick(win._thumbs_list, Qt.Key.Key_Return)

    assert jumps == [2]


def test_reload_action_refreshes_same_path_pdf_via_qtbot(tmp_path: Path, qtbot):
    pdf = tmp_path / "reload.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Before")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    before_key = win.current_view()._pages[0].pixmap().cacheKey()
    assert "Before" in win.current_view().document.load_page(0).get_text("text")

    _rewrite_pdf_for_reload(win, pdf, pages=3, text_prefix="After")
    win._reload_action.trigger()

    qtbot.waitUntil(lambda: win.current_view().page_count == 3, timeout=3000)
    qtbot.waitUntil(
        lambda: "After" in win.current_view().document.load_page(0).get_text("text"),
        timeout=3000,
    )

    after_key = win.current_view()._pages[0].pixmap().cacheKey()
    assert before_key != after_key


def test_live_search_stays_responsive_with_tabs_and_annotations(tmp_path: Path, qtbot, monkeypatch):
    plain_pdf = tmp_path / "plain.pdf"
    annotated_pdf = tmp_path / "annotated.pdf"
    _create_pdf(plain_pdf, pages=1, text_prefix="Plain")
    _create_pdf(annotated_pdf, pages=36, text_prefix="Annotated")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(plain_pdf))
    win._open_file(str(annotated_pdf))
    annotated_view = win.current_view()
    annotated_ctx = win.current_context()
    annotated_ctx.sidecar_state.annotations = [
        AnnotationRecord(
            id=f"ann-{idx}",
            type="highlight",
            page=idx % annotated_view.page_count,
            rect=(72.0, 108.0, 180.0, 18.0),
            color="#f7c948",
            opacity=0.35,
        )
        for idx in range(24)
    ]
    annotated_view.set_annotations(annotated_ctx.sidecar_state.annotations)

    original_search_page_rects = win._search_page_rects

    def slow_search(page, query):
        time.sleep(0.03)
        return original_search_page_rects(page, query)

    monkeypatch.setattr(win, "_search_page_rects", slow_search)

    win._find_action.trigger()
    win._search_input.setText("search-target")
    QApplication.processEvents()

    heartbeat = []
    QTimer.singleShot(0, win._execute_live_search_current)
    QTimer.singleShot(50, lambda: heartbeat.append("tick"))

    qtbot.waitUntil(lambda: bool(heartbeat), timeout=1200)
    qtbot.waitUntil(lambda: len(annotated_ctx.search_results) >= 36, timeout=5000)

    assert win._search_operation is None
    assert win.current_view() is annotated_view

    win.close()
    qtbot.waitUntil(lambda: not win.isVisible(), timeout=2000)
    qtbot.wait(300)


def test_add_bookmark_action_via_qtbot(tmp_path: Path, qtbot, monkeypatch):
    pdf = tmp_path / "bookmark.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Bookmark")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("Mark A", True))
    win._add_bookmark_action.trigger()

    assert len(win.current_context().sidecar_state.bookmarks) == 1
    assert win.current_context().sidecar_state.bookmarks[0].title == "Mark A"


def test_edit_annotation_properties_via_qtbot(tmp_path: Path, qtbot, monkeypatch):
    pdf = tmp_path / "edit-annotation.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Edit")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *_args, **_kwargs: ("old note", True))
    view = win.current_view()
    view._create_selection_on_page(0, view._pages[0].page_rect.adjusted(40, 50, -430, -740))
    win._add_note()
    qtbot.waitUntil(lambda: len(win.current_context().sidecar_state.annotations) == 1, timeout=2000)

    win._annotation_list.setCurrentRow(0)

    def fake_exec(dialog):
        text_edit = dialog.findChild(QTextEdit)
        slider = dialog.findChild(QSlider)
        assert text_edit is not None
        assert slider is not None
        text_edit.setPlainText("updated note")
        slider.setValue(55)
        dialog.accept()
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    qtbot.mouseClick(win._annotation_edit_btn, Qt.MouseButton.LeftButton)

    ann = win.current_context().sidecar_state.annotations[0]
    assert ann.contents == "updated note"
    assert abs(ann.opacity - 0.55) < 0.001


def test_delete_annotation_via_qtbot(tmp_path: Path, qtbot):
    pdf = tmp_path / "delete-annotation.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Delete")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    view = win.current_view()
    view._create_selection_on_page(0, view._pages[0].page_rect.adjusted(40, 50, -430, -740))
    win._add_highlight()
    qtbot.waitUntil(lambda: len(win.current_context().sidecar_state.annotations) == 1, timeout=2000)

    win._annotation_list.setCurrentRow(0)
    qtbot.mouseClick(win._annotation_delete_btn, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: len(win.current_context().sidecar_state.annotations) == 0, timeout=2000)
    assert win._annotation_list.count() == 0


def test_export_annotations_to_pdf_via_qtbot(tmp_path: Path, qtbot, monkeypatch):
    pdf = tmp_path / "export.pdf"
    out_pdf = tmp_path / "export_annotated.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Export")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    view = win.current_view()
    view._create_selection_on_page(0, view._pages[0].page_rect.adjusted(40, 50, -430, -740))
    win._add_highlight()
    qtbot.waitUntil(lambda: len(win.current_context().sidecar_state.annotations) == 1, timeout=2000)

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(out_pdf), "PDF Files (*.pdf)"))
    qtbot.mouseClick(win._annotation_export_btn, Qt.MouseButton.LeftButton)

    assert out_pdf.exists()
    exported = fitz.open(str(out_pdf))
    page = exported[0]
    annots = list(page.annots() or [])
    exported.close()
    assert len(annots) >= 1


def test_measure_drag_and_keyboard_nudge_via_qtbot(tmp_path: Path, qtbot):
    pdf = tmp_path / "measure.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Measure")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    view = win.current_view()
    win._set_tool(ToolMode.MEASURE)
    qtbot.waitUntil(lambda: view.tool == ToolMode.MEASURE, timeout=1000)

    start = _viewport_pos_for_pdf_point(view, 0, 80, 120)
    end = _viewport_pos_for_pdf_point(view, 0, 180, 220)

    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(view.viewport(), pos=end)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

    rect = view.selection_rect
    assert rect is not None
    before_x = rect.x()
    before_w = rect.width()

    view.setFocus()
    qtbot.keyClick(view, Qt.Key.Key_Right)
    assert view.selection_rect.x() > before_x

    qtbot.keyPress(view, Qt.Key.Key_Right, modifier=Qt.KeyboardModifier.ControlModifier)
    qtbot.keyRelease(view, Qt.Key.Key_Right, modifier=Qt.KeyboardModifier.ControlModifier)
    assert view.selection_rect.width() > before_w


def test_measure_drag_works_when_annotation_covers_page(tmp_path: Path, qtbot):
    pdf = tmp_path / "measure-watermark-like.pdf"
    _create_pdf(pdf, pages=1, text_prefix="MeasureWatermark")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    view = win.current_view()
    page_rect = view._pages[0].page_rect
    view.set_annotations(
        [
            AnnotationRecord(
                id="covering-ann",
                type="rectangle",
                page=0,
                rect=(0.0, 0.0, float(page_rect.width()), float(page_rect.height())),
                color="#cccccc",
                opacity=0.1,
            )
        ]
    )

    win._set_tool(ToolMode.MEASURE)
    qtbot.waitUntil(lambda: view.tool == ToolMode.MEASURE, timeout=1000)

    start = _viewport_pos_for_pdf_point(view, 0, 80, 120)
    end = _viewport_pos_for_pdf_point(view, 0, 180, 220)

    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(view.viewport(), pos=end)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

    rect = view.selection_rect
    assert rect is not None
    assert rect.width() > 0
    assert rect.height() > 0


def test_canvas_annotation_drag_create_via_qtbot(tmp_path: Path, qtbot):
    pdf = tmp_path / "annotate-drag.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Annotate")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    view = win.current_view()
    win._set_tool(ToolMode.ANNOTATE)
    view.annotate_type = "highlight"

    start = _viewport_pos_for_pdf_point(view, 0, 100, 140)
    end = _viewport_pos_for_pdf_point(view, 0, 220, 190)

    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(view.viewport(), pos=end)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

    qtbot.waitUntil(lambda: len(win.current_context().sidecar_state.annotations) == 1, timeout=2000)
    ann = win.current_context().sidecar_state.annotations[0]
    assert ann.type == "highlight"
    assert ann.rect[2] > 0
    assert ann.rect[3] > 0


def test_canvas_freehand_annotation_drag_via_qtbot(tmp_path: Path, qtbot):
    pdf = tmp_path / "annotate-freehand.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Freehand")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    view = win.current_view()
    win._set_tool(ToolMode.ANNOTATE)
    view.annotate_type = "freehand"

    start = _viewport_pos_for_pdf_point(view, 0, 110, 150)
    mid = _viewport_pos_for_pdf_point(view, 0, 160, 180)
    end = _viewport_pos_for_pdf_point(view, 0, 230, 210)

    qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(view.viewport(), pos=mid)
    qtbot.mouseMove(view.viewport(), pos=end)
    qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

    qtbot.waitUntil(lambda: len(win.current_context().sidecar_state.annotations) == 1, timeout=2000)
    ann = win.current_context().sidecar_state.annotations[0]
    assert ann.type == "freehand"
    assert len(ann.points) >= 2


def test_bookmark_context_menu_rename_and_delete_via_qtbot(tmp_path: Path, qtbot, monkeypatch):
    pdf = tmp_path / "bookmark-context.pdf"
    _create_pdf(pdf, pages=1, text_prefix="BookmarkCtx")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))
    win._outline_dock.show()

    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("Original Mark", True))
    win._add_bookmark_action.trigger()
    assert len(win.current_context().sidecar_state.bookmarks) == 1

    bookmark_root = win._outline_tree.topLevelItem(1)
    item = bookmark_root.child(0)
    rect = win._outline_tree.visualItemRect(item)
    pos = rect.center()

    monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("Renamed Mark", True))

    class _FakeAction:
        def __init__(self, text: str):
            self._text = text

        def text(self):
            return self._text

    class _FakeMenu:
        choice_text = ""

        def __init__(self, *_args, **_kwargs):
            self._actions = []

        def addAction(self, text):
            action = _FakeAction(text)
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec(self, *_args, **_kwargs):
            for action in self._actions:
                if action.text() == self.choice_text:
                    return action
            return None

    monkeypatch.setattr("neoview.ui.main_window.QMenu", _FakeMenu)
    _FakeMenu.choice_text = "Rename Bookmark"
    win._on_outline_context_menu(pos)

    assert win.current_context().sidecar_state.bookmarks[0].title == "Renamed Mark"
    bookmark_root = win._outline_tree.topLevelItem(1)
    item = bookmark_root.child(0)
    assert "Renamed Mark" in bookmark_root.child(0).text(0)

    _FakeMenu.choice_text = "Delete Bookmark"
    rect = win._outline_tree.visualItemRect(item)
    pos = rect.center()
    win._on_outline_context_menu(pos)

    assert win.current_context().sidecar_state.bookmarks == []
    bookmark_root = win._outline_tree.topLevelItem(1)
    assert bookmark_root.childCount() == 0


def test_annotation_context_menu_edit_and_delete_via_qtbot(tmp_path: Path, qtbot, monkeypatch):
    pdf = tmp_path / "annotation-context.pdf"
    _create_pdf(pdf, pages=1, text_prefix="AnnotCtx")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    view = win.current_view()
    view._create_selection_on_page(0, view._pages[0].page_rect.adjusted(50, 60, -420, -720))
    win._add_highlight()
    qtbot.waitUntil(lambda: len(win.current_context().sidecar_state.annotations) == 1, timeout=2000)
    ann_id = win.current_context().sidecar_state.annotations[0].id

    class _FakeAction:
        def __init__(self, text: str):
            self._text = text

        def text(self):
            return self._text

    class _FakeMenu:
        choice_text = ""

        def __init__(self, *_args, **_kwargs):
            self._actions = []

        def addAction(self, text):
            action = _FakeAction(text)
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec(self, *_args, **_kwargs):
            for action in self._actions:
                if action.text() == self.choice_text:
                    return action
            return None

    edit_requests = []
    monkeypatch.setattr("neoview.ui.pdf_view.QMenu", _FakeMenu)
    monkeypatch.setattr(win, "_open_annotation_properties_dialog", lambda ann: edit_requests.append(("dialog", ann.id)))
    view.annotation_edit_requested.connect(lambda incoming: edit_requests.append(incoming))
    _FakeMenu.choice_text = "Edit / Properties"
    view._show_annotation_context_menu(ann_id, QPoint(0, 0))
    assert ann_id in edit_requests

    delete_requests = []
    view.annotation_deleted.connect(lambda incoming: delete_requests.append(incoming))
    _FakeMenu.choice_text = "Delete Annotation"
    view._show_annotation_context_menu(ann_id, QPoint(0, 0))
    assert delete_requests == [ann_id]


def test_select_all_and_copy_text_shortcuts_via_qtbot(tmp_path: Path, qtbot):
    pdf = tmp_path / "select-copy.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Clipboard")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    view = win.current_view()
    win._set_tool(ToolMode.SELECT)
    view.setFocus()

    clipboard = QApplication.clipboard()
    clipboard.clear()

    qtbot.keyClick(view, Qt.Key.Key_A, modifier=Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: bool(view._text_highlight_items), timeout=2000)
    qtbot.waitUntil(lambda: "search-target" in clipboard.text().lower(), timeout=2000)

    clipboard.clear()
    qtbot.keyClick(view, Qt.Key.Key_C, modifier=Qt.KeyboardModifier.ControlModifier)
    qtbot.waitUntil(lambda: "search-target" in clipboard.text().lower(), timeout=2000)


def test_text_context_menu_select_all_and_copy_via_qtbot(tmp_path: Path, qtbot, monkeypatch):
    pdf = tmp_path / "text-context.pdf"
    _create_pdf(pdf, pages=1, text_prefix="Context")

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    win._open_file(str(pdf))

    view = win.current_view()
    win._set_tool(ToolMode.SELECT)

    class _FakeAction:
        def __init__(self, text: str):
            self._text = text
            self.enabled = True

        def text(self):
            return self._text

        def setEnabled(self, enabled: bool):
            self.enabled = enabled

    class _FakeMenu:
        choice_text = ""

        def __init__(self, *_args, **_kwargs):
            self._actions = []

        def addAction(self, text):
            action = _FakeAction(text)
            self._actions.append(action)
            return action

        def addSeparator(self):
            return None

        def exec(self, *_args, **_kwargs):
            for action in self._actions:
                if action.text() == self.choice_text and action.enabled:
                    return action
            return None

    monkeypatch.setattr("neoview.ui.pdf_view.QMenu", _FakeMenu)
    clipboard = QApplication.clipboard()
    clipboard.clear()

    menu_pos = _viewport_pos_for_pdf_point(view, 0, 120, 160)
    global_pos = view.viewport().mapToGlobal(menu_pos)

    _FakeMenu.choice_text = "Select All on Page"
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, menu_pos, global_pos)
    view.contextMenuEvent(event)
    assert view._text_highlight_items

    clipboard.clear()
    _FakeMenu.choice_text = "Copy Text"
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, menu_pos, global_pos)
    view.contextMenuEvent(event)
    assert "search-target" in clipboard.text().lower()
