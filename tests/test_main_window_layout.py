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
    for action in (win._open_action, win._zoom_in_action, win._inspector_action):
        button = win._main_toolbar.widgetForAction(action)
        assert button.width() >= 32 and button.height() >= 32, action.text()


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


# --------------------------------------------------------------------------- menus / shortcuts


def _menu(win: MainWindow, title: str):
    for action in win.menuBar().actions():
        if action.text().replace("&", "") == title:
            return action.menu()
    raise AssertionError(f"no {title} menu")


def _menu_texts(menu) -> list[str]:
    return [a.text().replace("&", "") for a in menu.actions() if not a.isSeparator()]


def test_menu_bar_has_standard_menus(qtbot):
    win = _window(qtbot)
    titles = [a.text().replace("&", "") for a in win.menuBar().actions()]
    assert titles == ["File", "Edit", "View", "Go", "Tools", "Help"]
    assert {"Open...", "Open Recent", "Close", "Print...", "Quit"} <= set(_menu_texts(_menu(win, "File")))
    assert {"Find...", "Find Next", "Find Previous"} <= set(_menu_texts(_menu(win, "Edit")))
    view_items = set(_menu_texts(_menu(win, "View")))
    assert {"Sidebar", "Inspector", "Zoom", "Page Layout", "Reading Mode", "Rotate", "Show Rulers",
            "Show Layout Grid", "Full Screen", "Presentation"} <= view_items
    assert {"First Page", "Previous Page", "Next Page", "Last Page", "Go to Page...", "Back",
            "Forward"} <= set(_menu_texts(_menu(win, "Go")))
    assert {"Select", "Hand", "Measure", "Annotate", "Measurement Units"} <= set(_menu_texts(_menu(win, "Tools")))
    assert any(t.startswith("About") for t in _menu_texts(_menu(win, "Help")))


@pytest.mark.parametrize(
    ("attr", "keys"),
    [
        ("_open_action", "Ctrl+O"),
        ("_close_tab_action", "Ctrl+W"),
        ("_print_action", "Ctrl+P"),
        ("_find_action", "Ctrl+F"),
        ("_find_next_action", "F3"),
        ("_find_prev_action", "Shift+F3"),
        ("_actual_size_action", "Ctrl+0"),
        ("_fit_width_action", "Ctrl+1"),
        ("_fit_page_action", "Ctrl+2"),
        ("_first_page_action", "Home"),
        ("_last_page_action", "End"),
        ("_back_action", "Alt+Left"),
        ("_forward_action", "Alt+Right"),
        ("_fullscreen_action", "F11"),
        ("_presentation_action", "F5"),
        ("_sidebar_action", "F9"),
        ("_next_tab_action", "Ctrl+Tab"),
        ("_reload_action", "Ctrl+Shift+R"),
    ],
)
def test_standard_shortcuts(qtbot, attr, keys):
    win = _window(qtbot)
    action = getattr(win, attr)
    assert keys in [s.toString() for s in action.shortcuts()]


def test_shortcuts_are_unique(qtbot):
    win = _window(qtbot)
    seen: dict[str, str] = {}
    for action in win.findChildren(type(win._open_action)):
        for seq in action.shortcuts():
            key = seq.toString()
            assert key not in seen, f"{key} bound to {seen.get(key)} and {action.text()}"
            seen[key] = action.text()


def test_units_menu_switches_measurement_unit(qtbot):
    win = _window(qtbot)
    win._unit_actions["mm"].trigger()
    assert win._unit == "mm"
    assert win._inspector.units_combo.currentData() == "mm"
    assert win._unit_actions["mm"].isChecked()


# --------------------------------------------------------------------------- capabilities


def test_print_action_calls_printing_module(two_pdfs, qtbot, monkeypatch):
    from neoview.ui import printing

    a, _b = two_pdfs
    calls = []
    monkeypatch.setattr(printing, "print_document", lambda *args: calls.append(args) or True)
    win = _window(qtbot)
    assert not win._print_action.isEnabled()  # nothing to print yet
    win._open_file(str(a))
    win.current_view().go_to_page(1)
    QApplication.processEvents()
    win._print_action.trigger()

    assert len(calls) == 1
    parent, path, page, pw = calls[0]
    assert parent is win
    assert path == str(a.resolve())
    assert page == win.current_view().current_page
    assert pw is None


def test_print_failure_is_reported_not_raised(two_pdfs, qtbot, monkeypatch):
    from neoview.ui import printing

    a, _b = two_pdfs

    def boom(*_args):
        raise RuntimeError("file truncated")

    monkeypatch.setattr(printing, "print_document", boom)
    win = _window(qtbot)
    win._open_file(str(a))
    win._print_action.trigger()
    assert "file truncated" in win._status.currentMessage()


def test_presentation_action_opens_window_and_viewer_follows_on_close(two_pdfs, qtbot, monkeypatch):
    from PySide6.QtCore import QObject, Signal

    from neoview.ui import presentation

    created = []

    class FakePresentation(QObject):
        closed = Signal(int)

        def __init__(self, path, start_page=0, password=None, parent=None):
            super().__init__()
            self.args = (path, start_page, password)
            self.presented = False
            created.append(self)

        def present(self):
            self.presented = True

        def isVisible(self):
            return self.presented

        def raise_(self):
            self.raised = True

        def activateWindow(self):
            pass

    monkeypatch.setattr(presentation, "PresentationWindow", FakePresentation)
    _a, b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(b))
    win._presentation_action.trigger()

    assert len(created) == 1 and created[0].presented
    assert created[0].args == (str(b.resolve()), win.current_view().current_page, None)
    win._presentation_action.trigger()  # F5 while presenting focuses the open one
    assert len(created) == 1 and created[0].raised

    created[0].closed.emit(2)
    QApplication.processEvents()
    assert win._presentation is None
    qtbot.waitUntil(lambda: win.current_view().current_page == 2, timeout=2000)


def test_presentation_failure_is_reported(two_pdfs, qtbot, monkeypatch):
    from neoview.ui import presentation

    def boom(*_args, **_kwargs):
        raise PermissionError("Password required")

    monkeypatch.setattr(presentation, "PresentationWindow", boom)
    a, _b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    win._presentation_action.trigger()
    assert "Password required" in win._status.currentMessage()
    assert win._presentation is None


_PHASE_B_METHODS = (
    "set_page_mode", "page_mode", "set_color_mode", "color_mode",
    "go_back", "go_forward", "can_go_back", "can_go_forward",
)


def test_phase_b_actions_have_stable_names(qtbot):
    from PySide6.QtGui import QAction

    win = _window(qtbot)
    for name in (
        "action_page_mode_single", "action_page_mode_continuous", "action_page_mode_two_page",
        "action_page_mode_two_page_cover", "action_color_mode_normal", "action_color_mode_night",
        "action_color_mode_sepia", "action_go_back", "action_go_forward", "action_print",
        "action_presentation",
    ):
        assert win.findChild(QAction, name) is not None, name


def test_phase_b_actions_disabled_when_view_lacks_methods(two_pdfs, qtbot, monkeypatch):
    for name in _PHASE_B_METHODS:
        monkeypatch.delattr(PdfView, name, raising=False)
    a, _b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    actions = [*win._page_mode_actions.values(), *win._color_mode_actions.values(),
               win._back_action, win._forward_action]
    assert all(not act.isEnabled() for act in actions)
    # Triggering the slots directly is a harmless no-op.
    win._set_page_mode("two-page")
    win._set_color_mode("night")
    win._go_back()
    win._go_forward()
    assert all(not act.isEnabled() for act in actions)


def test_phase_b_actions_enable_and_route_when_view_has_methods(two_pdfs, qtbot):
    a, _b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    view = win.current_view()
    calls = []
    state = {"page": "continuous", "color": "normal", "back": True}
    view.set_page_mode = lambda m: (calls.append(("page", m)), state.update(page=m))
    view.page_mode = lambda: state["page"]
    view.set_color_mode = lambda m: (calls.append(("color", m)), state.update(color=m))
    view.color_mode = lambda: state["color"]
    view.go_back = lambda: calls.append(("back",)) or True
    view.go_forward = lambda: calls.append(("forward",)) or True
    view.can_go_back = lambda: state["back"]
    view.can_go_forward = lambda: False
    win._update_capability_actions()

    assert win._page_mode_actions["continuous"].isEnabled()
    assert win._page_mode_actions["continuous"].isChecked()
    assert win._color_mode_actions["normal"].isChecked()
    assert win._back_action.isEnabled() and not win._forward_action.isEnabled()

    win._page_mode_actions["two-page"].trigger()
    win._color_mode_actions["night"].trigger()
    win._back_action.trigger()
    assert calls == [("page", "two-page"), ("color", "night"), ("back",)]
    assert win._page_mode_actions["two-page"].isChecked()
    assert win._color_mode_actions["night"].isChecked()

    # Page and colour mode are remembered per document with the other view state.
    win._save_current_document_session()
    saved = win._document_sessions[str(a.resolve())]
    assert saved["page_mode"] == "two-page" and saved["color_mode"] == "night"


def test_password_prompt_retries_then_opens(qtbot, monkeypatch):
    from neoview.ui import password

    answers = iter(["wrong", "secret"])

    class FakeDialog:
        def __init__(self, parent, file_name):
            self.errors = []

        def exec(self):
            return 1  # Accepted

        def password(self):
            return next(answers)

        def set_error(self, message):
            self.errors.append(message)

    class FakeView:
        def __init__(self):
            self.tries = []

        def open_document(self, path, pw=None):
            self.tries.append(pw)
            return pw == "secret"

    monkeypatch.setattr(password, "PasswordDialog", FakeDialog)
    win = _window(qtbot)
    view = FakeView()
    assert win._unlock_and_open(view, "/tmp/locked.pdf")
    assert view.tries == ["wrong", "secret"]


def test_password_prompt_gives_up_after_max_attempts(qtbot, monkeypatch):
    from neoview.ui import password

    class FakeDialog:
        def __init__(self, parent, file_name):
            pass

        def exec(self):
            return 1

        def password(self):
            return "nope"

        def set_error(self, message):
            pass

    class FakeView:
        tries = 0

        def open_document(self, path, pw=None):
            FakeView.tries += 1
            return False

    monkeypatch.setattr(password, "PasswordDialog", FakeDialog)
    win = _window(qtbot)
    assert not win._unlock_and_open(FakeView(), "/tmp/locked.pdf")
    assert FakeView.tries == password.MAX_ATTEMPTS
    assert "Could not unlock" in win._status.currentMessage()


# --------------------------------------------------------------------------- empty state, tabs


def test_empty_state_shown_without_document(two_pdfs, qtbot):
    a, _b = two_pdfs
    win = _window(qtbot)
    assert win._welcome.isVisible()
    assert win._welcome.open_button.isVisible()
    win._open_file(str(a))
    QApplication.processEvents()
    assert not win._welcome.isVisible()
    win._close_current_tab()
    QApplication.processEvents()
    assert win._welcome.isVisible()
    # The file just closed is offered as a recent file.
    assert [b.toolTip() for b in win._welcome.recent_buttons] == [str(a.resolve())]


def test_empty_state_open_button_and_recent_entry(two_pdfs, qtbot, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    a, b = two_pdfs
    win = _window(qtbot)
    win._add_recent_file(str(b))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(a), "PDF (*.pdf)"))
    win._welcome.open_button.click()
    assert win.current_context().file_path == str(a.resolve())
    win._close_current_tab()

    # Most recent first: a (just closed), then b.
    assert [btn.toolTip() for btn in win._welcome.recent_buttons] == [str(a.resolve()), str(b.resolve())]
    win._welcome.recent_buttons[1].click()
    assert win.current_context().file_path == str(b.resolve())


def test_tab_bar_only_with_two_documents_and_middle_click_closes(two_pdfs, qtbot):
    a, b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    QApplication.processEvents()
    assert not win._tabs.tabBar().isVisible()
    win._open_file(str(b))
    QApplication.processEvents()
    assert win._tabs.tabBar().isVisible()

    bar = win._tabs.tabBar()
    qtbot.mouseClick(bar, Qt.MouseButton.MiddleButton, pos=bar.tabRect(0).center())
    QApplication.processEvents()
    assert win._tabs.count() == 1
    assert win.current_context().file_path == str(b.resolve())


# --------------------------------------------------------------------------- stylesheet


def test_chrome_rules_join_the_app_stylesheet_once(qtbot):
    from neoview.ui.chrome import install_chrome_stylesheet

    class FakeApp:
        sheet = "QWidget { }"

        def styleSheet(self):
            return self.sheet

        def setStyleSheet(self, sheet):
            self.sheet = sheet

    app = FakeApp()
    assert install_chrome_stylesheet(app, "light")
    assert install_chrome_stylesheet(app, "dark")  # a theme switch replaces, never stacks
    assert app.sheet.startswith("QWidget { }")
    assert app.sheet.count("QFrame#SearchField {") == 1

    empty = FakeApp()
    empty.sheet = ""
    assert not install_chrome_stylesheet(empty, "light")  # no theme applied: leave it alone
    assert empty.sheet == ""

    # No per-window sheet: one style-sheet style for the whole app keeps repolish cheap.
    assert _window(qtbot).styleSheet() == ""


# --------------------------------------------------------------------------- Phase B, real PdfView


def test_page_layout_actions_drive_real_view(two_pdfs, qtbot):
    _a, b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(b))
    view = win.current_view()
    assert win._page_mode_actions["continuous"].isEnabled()
    assert win._page_mode_actions["continuous"].isChecked()

    win._page_mode_actions["two-page"].trigger()
    assert view.page_mode() == "two-page"
    assert win._page_mode_actions["two-page"].isChecked()

    # A change made on the view (not through the menu) updates the checked action.
    view.set_page_mode("single")
    QApplication.processEvents()
    assert win._page_mode_actions["single"].isChecked()
    assert not win._page_mode_actions["two-page"].isChecked()


def test_reading_mode_actions_drive_real_view_and_thumbnails(two_pdfs, qtbot):
    a, _b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(a))
    view = win.current_view()
    win._show_sidebar_page("thumbnails")
    win._render_thumbnail_batch()

    def thumb_center_lightness() -> int:
        icon = win._thumbs_list.item(0).icon()
        image = icon.pixmap(win.THUMB_BOX).toImage()
        return image.pixelColor(image.width() // 2, image.height() * 3 // 4).lightness()

    assert thumb_center_lightness() > 200  # white paper

    win._color_mode_actions["night"].trigger()
    assert view.color_mode() == "night"
    assert win._color_mode_actions["night"].isChecked()
    win._render_thumbnail_batch()
    assert thumb_center_lightness() < 60  # thumbnails follow the reading colours

    view.set_color_mode("sepia")
    QApplication.processEvents()
    assert win._color_mode_actions["sepia"].isChecked()


def test_back_forward_actions_drive_real_view_history(tmp_path: Path, qtbot):
    pdf = tmp_path / "long.pdf"
    _create_pdf(pdf, pages=6)
    win = _window(qtbot)
    win._open_file(str(pdf))
    view = win.current_view()
    QApplication.processEvents()
    assert not win._back_action.isEnabled()

    view.go_to_page(4)  # a jump records history
    QApplication.processEvents()
    assert view.current_page == 4
    assert win._back_action.isEnabled() and not win._forward_action.isEnabled()

    win._back_action.trigger()
    QApplication.processEvents()
    assert view.current_page == 0
    assert win._forward_action.isEnabled()

    win._forward_action.trigger()
    QApplication.processEvents()
    assert view.current_page == 4
    assert [s.toString() for s in win._back_action.shortcuts()] == ["Alt+Left"]
    assert [s.toString() for s in win._forward_action.shortcuts()] == ["Alt+Right"]


def test_page_and_color_mode_persist_per_document(two_pdfs, qtbot):
    _a, b = two_pdfs
    win = _window(qtbot)
    win._open_file(str(b))
    win._page_mode_actions["two-page"].trigger()
    win._color_mode_actions["sepia"].trigger()
    win.close()

    again = _window(qtbot)  # same isolated settings store
    if again.current_view().document is None:
        again._open_file(str(b))
    view = again.current_view()
    assert view.page_mode() == "two-page"
    assert view.color_mode() == "sepia"
    assert again._page_mode_actions["two-page"].isChecked()


def _encrypted_pdf(path: Path) -> None:
    doc = fitz.open()
    for i in range(2):
        doc.new_page(width=595, height=842).insert_text((72, 120), f"Secret page {i + 1}")
    doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="owner")
    doc.close()


def _fake_password_dialog(monkeypatch, answers: list[str | None]):
    from neoview.ui import password

    replies = iter(answers)
    shown = []

    class FakeDialog:
        def __init__(self, parent, file_name):
            shown.append(file_name)
            self._answer = None

        def exec(self):
            self._answer = next(replies)
            return 0 if self._answer is None else 1

        def password(self):
            return self._answer

        def set_error(self, message):
            pass

    monkeypatch.setattr(password, "PasswordDialog", FakeDialog)
    return shown


def test_encrypted_pdf_prompts_and_opens_in_real_view(tmp_path: Path, qtbot, monkeypatch):
    from neoview.ui import printing

    pdf = tmp_path / "locked.pdf"
    _encrypted_pdf(pdf)
    shown = _fake_password_dialog(monkeypatch, ["wrong", "secret"])
    win = _window(qtbot)
    win._open_file(str(pdf))

    view = win.current_view()
    assert shown == ["locked.pdf"]
    assert view.document is not None and view.page_count == 2
    assert view.document_password() == "secret"
    assert not win._welcome.isVisible()

    calls = []
    monkeypatch.setattr(printing, "print_document", lambda *args: calls.append(args) or True)
    win._print_action.trigger()
    assert calls[0][3] == "secret"  # the password reaches the print job


def test_encrypted_pdf_cancel_leaves_window_empty(tmp_path: Path, two_pdfs, qtbot, monkeypatch):
    a, _b = two_pdfs
    pdf = tmp_path / "locked.pdf"
    _encrypted_pdf(pdf)
    _fake_password_dialog(monkeypatch, [None])
    win = _window(qtbot)
    win._open_file(str(a))
    win._open_file(str(pdf))
    # The tab created for the locked file is closed again; the open document stays.
    assert win._tabs.count() == 1
    assert win.current_context().file_path == str(a.resolve())

