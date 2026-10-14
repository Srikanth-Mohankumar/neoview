"""MainWindow chrome: panel refreshes, toolbar, sidebar, inspector, menus, theme, capabilities."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QApplication, QToolButton, QWidgetAction

from neoview.ui import icons
from neoview.ui.main_window import MainWindow
from neoview.ui.pdf_view import PdfView, ToolMode


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


# --------------------------------------------------------------------------- toolbar


def _toolbar_actions(win: MainWindow):
    actions = [a for a in win._main_toolbar.actions() if not a.isSeparator() and a.isVisible()]
    # The segmented tool control is a widget; its buttons carry the tool actions.
    for btn in win._tool_segment.findChildren(QToolButton):
        actions.append(btn.defaultAction())
    return [a for a in actions if not isinstance(a, QWidgetAction)]


def test_toolbar_is_one_icon_only_row_with_shortcut_tooltips(qtbot):
    win = _window(qtbot)
    expected = {
        win._sidebar_action: "F9",
        win._open_action: "Ctrl+O",
        win._prev_page_action: "PgUp",
        win._next_page_action: "PgDown",
        win._zoom_out_action: "Ctrl+-",
        win._zoom_in_action: "Ctrl++",
        win._select_action: "1",
        win._hand_action: "2",
        win._measure_action: "3",
        win._annotate_action: "4",
        win._inspector_action: "Ctrl+Shift+I",
    }
    present = _toolbar_actions(win)
    for action, keys in expected.items():
        assert action in present, action.text()
        assert not action.icon().isNull(), action.text()
        assert action.shortcut().toString() == keys, action.text()
        assert f"({keys})" in action.toolTip(), action.toolTip()
    assert win._main_toolbar.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    # Search field, page field, zoom box and overflow live in the same row.
    for widget in (win._search_field, win._page_field, win._zoom_combo, win._overflow_btn):
        assert win._main_toolbar.isAncestorOf(widget)
    # 32 px hit targets for the icon buttons.
    button = win._main_toolbar.widgetForAction(win._open_action)
    assert button.sizeHint().height() >= 30


def test_toolbar_tool_segment_switches_view_tool(two_pdfs, qtbot):
    a, _b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    win._select_action.trigger()
    assert win.current_view().tool == ToolMode.SELECT
    win._hand_action.trigger()
    assert win.current_view().tool == ToolMode.HAND
    assert win._hand_action.isChecked() and not win._select_action.isChecked()


def test_zoom_box_fit_presets(two_pdfs, qtbot):
    a, _b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    view = win.current_view()
    view.set_zoom(3.0, immediate=True, zoom_mode=PdfView.ZOOM_MODE_CUSTOM)
    win._on_zoom_combo_changed("Fit Page")
    assert view.zoom_mode == PdfView.ZOOM_MODE_FIT_PAGE
    win._on_zoom_combo_changed("Fit Width")
    assert view.zoom_mode == PdfView.ZOOM_MODE_FIT_WIDTH
    win._on_zoom_combo_changed("150%")
    assert view.zoom == pytest.approx(1.5)


def test_doc_actions_disabled_without_document(two_pdfs, qtbot):
    a, _b = two_pdfs
    win = _window(qtbot)
    assert not win._zoom_in_action.isEnabled()
    assert not win._next_page_action.isEnabled()
    assert win._open_action.isEnabled()
    win._open_file(str(a))
    assert win._zoom_in_action.isEnabled()
    assert win._next_page_action.isEnabled()


# --------------------------------------------------------------------------- sidebar


def test_sidebar_hidden_by_default_and_toggles_with_f9_action(qtbot):
    win = _window(qtbot)
    assert win._sidebar_dock.isHidden()
    win._sidebar_action.trigger()
    assert win._sidebar_dock.isVisible()
    assert win._sidebar_action.isChecked()
    win._sidebar_action.trigger()
    assert win._sidebar_dock.isHidden()
    assert win._settings.value("window/show_sidebar", type=bool) is False


def test_sidebar_tabs_switch_panels(two_pdfs, qtbot):
    a, _b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    assert win._sidebar.keys() == ["thumbnails", "outline", "bookmarks", "annotations"]

    for key, widget in (
        ("outline", win._outline_tree),
        ("bookmarks", win._bookmarks_hint),  # no bookmarks yet: the hint shows
        ("annotations", win._annotations_hint),
        ("thumbnails", win._thumbs_list),
    ):
        win._sidebar.tab_button(key).click()
        QApplication.processEvents()
        assert win._sidebar.current_key() == key
        assert win._sidebar_dock.isHidden()  # clicking a tab does not open a closed sidebar
        win._show_sidebar_page(key)
        QApplication.processEvents()
        assert widget.isVisible(), key
        assert win._settings.value("window/sidebar_page") == key
        win._set_sidebar_visible(False)


def test_sidebar_panel_shortcuts_toggle_their_page(two_pdfs, qtbot):
    a, _b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    win._outline_panel_action.trigger()
    assert win._sidebar_dock.isVisible() and win._sidebar.current_key() == "outline"
    win._thumbs_panel_action.trigger()
    assert win._sidebar_dock.isVisible() and win._sidebar.current_key() == "thumbnails"
    win._thumbs_panel_action.trigger()
    assert win._sidebar_dock.isHidden()


def test_thumbnails_build_when_tab_is_selected(two_pdfs, qtbot):
    _a, b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(b))
    win._show_sidebar_page("outline")
    QApplication.processEvents()
    assert win._thumbs_list.count() == 0  # sidebar open, but another panel is showing
    win._sidebar.tab_button("thumbnails").click()
    QApplication.processEvents()
    assert win._thumbs_list.count() == 3


def test_outline_shows_hint_without_toc(tmp_path: Path, qtbot):
    pdf = tmp_path / "plain.pdf"
    _create_pdf(pdf, pages=1)
    win = _window(qtbot)
    win._open_file(str(pdf))
    win._show_sidebar_page("outline")
    QApplication.processEvents()
    assert win._outline_hint.isVisible()
    assert not win._outline_tree.isVisible()


# --------------------------------------------------------------------------- inspector


def test_inspector_hidden_by_default_and_toggle_action(qtbot):
    win = _window(qtbot)
    assert win._info_dock.isHidden()
    win._inspector_action.trigger()
    assert win._info_dock.isVisible() and win._inspector_action.isChecked()
    win._inspector.title_bar.close_button.click()
    assert win._info_dock.isHidden() and not win._inspector_action.isChecked()


def test_measure_tool_opens_inspector_and_readout_uses_unit(two_pdfs, qtbot):
    a, _b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    win._measure_action.trigger()
    assert win._info_dock.isVisible()

    win.current_view()._create_selection_on_page(0, QRectF(72, 72, 144, 72))
    QApplication.processEvents()
    assert win._measure_w.text() == "144.0 pt"
    assert win._measure_lbl.text() == "144.0 pt x 72.0 pt"

    win._set_unit("in")
    assert win._measure_w.text() == "2.000 in"
    assert win._measure_lbl.text() == "2.000 in x 1.000 in"
    assert win._settings.value("view/unit") == "in"


def test_every_bound_icon_is_bundled(qtbot):
    win = _window(qtbot)
    bundled = set(icons.available_icons())
    names = {name for _obj, name, _setter in win._icons._bindings}
    assert len(names) >= 20
    assert names <= bundled
