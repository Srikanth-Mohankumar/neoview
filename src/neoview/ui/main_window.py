"""Main application window."""

from __future__ import annotations

import html
import json
import os
import sys
import time
from bisect import bisect_right
from collections import deque
from uuid import uuid4

import fitz
import shiboken6
from PySide6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QPoint,
    QRect,
    QRectF,
    QSettings,
    QSize,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPixmap,
    QWindowStateChangeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from neoview import theme
from neoview.models.view_state import AnnotationRecord, BookmarkRecord, SearchMatch, TabContext
from neoview.persistence.sidecar_store import (
    clamp_sidecar_for_page_count,
    load_sidecar,
    save_sidecar,
)
from neoview.resources import load_app_icon
from neoview.ui import icons, password, presentation, printing
from neoview.ui.annotation_io import export_annotated_pdf, load_native_annotations
from neoview.ui.annotation_toolbar import AnnotationToolbar
from neoview.ui.chrome import TOOLBAR_ICON, IconBinder, build_chrome_stylesheet
from neoview.ui.dialogs import AnnotationPropertiesDialog, ExportDialog, LayoutGridDialog
from neoview.ui.inspector import InspectorPanel, PanelTitleBar
from neoview.ui.pdf_view import PdfView, ToolMode
from neoview.ui.sidebar import Sidebar
from neoview.ui.statusbar import ViewerStatusBar
from neoview.ui.toolbar import (
    ZOOM_FIT_PAGE,
    ZOOM_FIT_WIDTH,
    PageField,
    SearchField,
    ToolSegment,
    ZoomBox,
)
from neoview.utils.units import UNIT_LABELS, UNITS, format_length, format_size, normalize_unit

APP_NAME = "NeoView"


class MainWindow(QMainWindow):
    ROLE_KIND = int(Qt.ItemDataRole.UserRole)
    ROLE_PAGE = int(Qt.ItemDataRole.UserRole) + 1
    ROLE_BOOKMARK_ID = int(Qt.ItemDataRole.UserRole) + 2
    ROLE_ANNOTATION_ID = int(Qt.ItemDataRole.UserRole) + 3
    MAX_SEARCH_RESULTS = 2000
    MAX_LIVE_SEARCH_RESULTS = 250
    MIN_LIVE_SEARCH_CHARS = 2
    SEARCH_SYNC_PAGE_THRESHOLD = 8
    SEARCH_BATCH_PAGES = 2
    SEARCH_BATCH_TIME_BUDGET_MS = 18.0
    THUMB_BOX = QSize(112, 148)  # thumbnail fits in this box, aspect preserved

    def __init__(self, pdf_path: str | None = None):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1280, 900)
        self.setAcceptDrops(True)

        self._current_file: str | None = None
        self._last_file_sig: tuple[int, int, int] | None = None
        self._settings = QSettings("NeoView", "NeoView")
        self._recent_files: list[str] = self._settings.value("recent_files", [], type=list)
        self._recent_menu: object | None = None
        self._document_sessions: dict[str, dict[str, object]] = self._load_json_setting("documents/session", {})
        self._startup_last_file = ""
        if not pdf_path:
            self._startup_last_file = self._settings.value("session/last_active_file", "", type=str)

        self._zoom_combo_updating = False
        self._search_input_updating = False
        self._unit = normalize_unit(self._settings.value("view/unit", "pt", type=str))
        self._auto_reload_enabled = self._settings.value("view/auto_reload", True, type=bool)
        self._show_rulers = self._settings.value("view/show_rulers", False, type=bool)
        self._layout_grid = {
            "enabled": self._settings.value("view/layout_grid_enabled", False, type=bool),
            "corner_marks": self._settings.value("view/layout_grid_corner_marks", False, type=bool),
            "width": self._settings.value("view/layout_grid_width", 72.0, type=float),
            "height": self._settings.value("view/layout_grid_height", 72.0, type=float),
            "offset_x": self._settings.value("view/layout_grid_offset_x", 0.0, type=float),
            "offset_y": self._settings.value("view/layout_grid_offset_y", 0.0, type=float),
            "subdivisions": self._settings.value("view/layout_grid_subdivisions", 0, type=int),
            "corner_length": self._settings.value("view/layout_grid_corner_length", 12.0, type=float),
            "color": self._settings.value("view/layout_grid_color", "#d92fd4", type=str),
        }

        self._view: PdfView | None = None
        self._tab_contexts: dict[PdfView, TabContext] = {}
        self._sidecar_timers: dict[PdfView, QTimer] = {}

        # Active-tab thumbnail state.
        self._thumb_source_key: str = ""
        self._thumb_icon_cache: dict[tuple, QIcon] = {}
        self._thumb_queue: deque[int] = deque()
        self._thumb_queued: set[int] = set()
        # (toc root item, sorted TOC pages, items in the same order) for bisecting
        # in _sync_outline_current_page; rebuilt by _populate_outline.
        self._outline_sync_index: tuple[QTreeWidgetItem, list[int], list[QTreeWidgetItem]] | None = None

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)

        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self._do_reload)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_check)
        self._poll_timer.start(500)

        self._session_save_timer = QTimer(self)
        self._session_save_timer.setSingleShot(True)
        self._session_save_timer.timeout.connect(self._save_current_document_session)

        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._render_thumbnail_batch)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._execute_live_search_current)
        self._search_batch_timer = QTimer(self)
        self._search_batch_timer.setSingleShot(True)
        self._search_batch_timer.timeout.connect(self._process_search_batch)
        self._search_operation: dict[str, object] | None = None
        self._reload_in_progress = False
        # True while _open_file runs: PdfView emits document_loaded from inside
        # open_document(), before the tab context knows its file, and _open_file
        # refreshes every panel itself afterwards. See _on_view_document_loaded.
        self._open_in_progress = False
        self._last_maximize_at: float = 0.0
        self._presentation: presentation.PresentationWindow | None = None

        self._setup_ui()
        self._restore_persistent_ui()

        if pdf_path:
            self._open_file(pdf_path)
        else:
            last_file = self._startup_last_file
            if last_file and os.path.exists(last_file):
                self._open_file(last_file)

    def current_view(self) -> PdfView:
        widget = self._tabs.currentWidget()
        if isinstance(widget, PdfView):
            return widget
        if self._view is not None:
            return self._view
        return self._create_tab()

    def current_context(self) -> TabContext:
        view = self.current_view()
        ctx = self._tab_contexts.get(view)
        if ctx is None:
            ctx = TabContext()
            self._tab_contexts[view] = ctx
        return ctx

    def _setup_ui(self):
        # Icons are tinted for the active theme; the binder re-tints them on a theme switch.
        self._icons = IconBinder()
        self.setStyleSheet(build_chrome_stylesheet())
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks)

        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("DocumentTabs")
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.setAcceptDrops(True)
        self._tabs.installEventFilter(self)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabCloseRequested.connect(self._close_tab_index)
        self.setCentralWidget(self._tabs)

        self._create_tab()

        self._setup_actions()
        self._setup_menus()
        self._setup_toolbar()
        self._setup_annotation_toolbar()
        self._setup_statusbar()
        self._setup_docks()
        self._update_status()

    def _create_tab(self) -> PdfView:
        view = PdfView(self)
        view.set_show_rulers(self._show_rulers)
        view.set_layout_grid_config(self._layout_grid)
        view.setAcceptDrops(True)
        view.viewport().setAcceptDrops(True)
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

        view.selection_changed.connect(lambda v=view: self._on_view_selection_changed(v))
        view.zoom_changed.connect(lambda _z, v=view: self._on_view_zoom_changed(v))
        view.page_changed.connect(lambda c, t, v=view: self._on_view_page_changed(v, c, t))
        view.text_info_changed.connect(lambda info, v=view: self._on_view_text_info(v, info))
        view.text_selected.connect(lambda text, v=view: self._on_view_text_selected(v, text))
        view.document_loaded.connect(lambda v=view: self._on_view_document_loaded(v))
        view.annotation_clicked.connect(lambda ann_id, v=view: self._on_view_annotation_clicked(v, ann_id))
        view.annotation_created.connect(lambda rec, v=view: self._on_view_annotation_created(v, rec))
        view.annotation_deleted.connect(lambda ann_id, v=view: self._on_view_annotation_deleted(v, ann_id))
        view.annotation_edit_requested.connect(lambda ann_id, v=view: self._on_view_annotation_edit_requested(v, ann_id))
        # Phase B viewer API (docs/dev/viewer-api.md): connect only what this PdfView has.
        for name in ("page_mode_changed", "color_mode_changed", "history_changed"):
            signal = getattr(view, name, None)
            if signal is not None:
                signal.connect(lambda *_args, v=view: self._on_view_capability_changed(v))
        password_signal = getattr(view, "password_required", None)
        if password_signal is not None:
            password_signal.connect(lambda path, v=view: self._on_view_password_required(v, path))

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda v=view: self._save_sidecar_for_view(v))
        self._sidecar_timers[view] = timer

        self._tab_contexts[view] = TabContext()

        index = self._tabs.addTab(view, "Untitled")
        self._tabs.setCurrentIndex(index)
        self._view = view
        return view

    def _is_current_view(self, view: PdfView) -> bool:
        return view is self.current_view()

    def _context_for_view(self, view: PdfView) -> TabContext:
        ctx = self._tab_contexts.get(view)
        if ctx is None:
            ctx = TabContext()
            self._tab_contexts[view] = ctx
        return ctx

    def _set_current_file(self, file_path: str | None):
        self._current_file = os.path.abspath(file_path) if file_path else None
        self._settings.setValue("session/last_active_file", self._current_file or "")

    def _on_tab_changed(self, _index: int):
        self._cancel_search_operation()
        view = self.current_view()
        self._view = view
        ctx = self._context_for_view(view)
        self._set_current_file(ctx.file_path)

        self._stop_watch()
        self._update_mtime()
        self._start_watch()

        # The first tab-change signal can fire during _setup_ui before docks exist.
        if not hasattr(self, "_search_input"):
            return

        self._load_search_from_context()
        # _refresh_document_info rebuilds the outline, thumbnails and annotation list
        # (or clears them for an empty tab); calling them here again did it twice.
        self._refresh_document_info()
        self._update_status()

        if isinstance(view, PdfView):
            view.set_performance_mode(self._perf_action.isChecked())
        self._update_perf_status()

    def _close_tab_index(self, index: int):
        widget = self._tabs.widget(index)
        if not isinstance(widget, PdfView):
            return

        if widget is self.current_view():
            self._search_timer.stop()
            self._cancel_search_operation()

        if self._tabs.count() == 1:
            self._save_sidecar_for_view(widget)
            # The view is reused for the next document, so keep its save timer.
            timer = self._sidecar_timers.get(widget)
            if timer is not None:
                timer.stop()
            widget.close_document()
            self._tab_contexts[widget] = TabContext()
            self._tabs.setTabText(0, "Untitled")
            self._set_current_file(None)
            self.setWindowTitle(APP_NAME)
            self._clear_search()
            self._refresh_document_info()
            self._update_status()
            return

        self._save_sidecar_for_view(widget)
        timer = self._sidecar_timers.pop(widget, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

        self._tab_contexts.pop(widget, None)
        # Avoid queued signals firing on a half-torn-down view.
        widget.blockSignals(True)
        widget.close_document()
        self._tabs.removeTab(index)
        widget.deleteLater()

    def _switch_tab_relative(self, step: int):
        count = self._tabs.count()
        if count <= 1:
            return
        current = self._tabs.currentIndex()
        if current < 0:
            current = 0
        target = (current + step) % count
        self._tabs.setCurrentIndex(target)

    def _switch_to_next_tab(self):
        self._switch_tab_relative(1)

    def _switch_to_previous_tab(self):
        self._switch_tab_relative(-1)

    def _find_open_view(self, path: str) -> PdfView | None:
        target = os.path.abspath(path)
        for idx in range(self._tabs.count()):
            widget = self._tabs.widget(idx)
            if not isinstance(widget, PdfView):
                continue
            ctx = self._tab_contexts.get(widget)
            if ctx and ctx.file_path and os.path.abspath(ctx.file_path) == target:
                return widget
        return None

    def _set_tab_title(self, view: PdfView):
        idx = self._tabs.indexOf(view)
        if idx < 0:
            return
        ctx = self._context_for_view(view)
        title = os.path.basename(ctx.file_path) if ctx.file_path else "Untitled"
        self._tabs.setTabText(idx, title)
        self._tabs.setTabToolTip(idx, ctx.file_path or "")

    # --------------------------- Actions, menus, toolbar ---------------------------
    def _action(
        self,
        text: str,
        slot,
        shortcut=None,
        *,
        icon: str | None = None,
        tip: str | None = None,
        name: str | None = None,
        checkable: bool = False,
    ) -> QAction:
        """Create a window-level action; the tooltip names its shortcut, e.g. "Zoom in (Ctrl++)"."""
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                action.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                action.setShortcut(shortcut)
        if icon:
            self._icons.bind(action, icon)
        if name:
            action.setObjectName(name)
        action.setCheckable(checkable)
        label = tip or text.replace("&", "").removesuffix("...")
        keys = action.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        action.setToolTip(f"{label} ({keys})" if keys else label)
        # Window-level so shortcuts work for actions that live only in the toolbar or
        # the overflow menu.
        self.addAction(action)
        return action

    def _setup_actions(self):
        view = self.current_view

        # File
        self._open_action = self._action(
            "&Open...", self._open_dialog, QKeySequence.StandardKey.Open, icon="folder-open", tip="Open"
        )
        self._close_tab_action = self._action("&Close", self._close_current_tab, "Ctrl+W", tip="Close document")
        self._reload_action = self._action("&Reload", self._force_reload, "Ctrl+Shift+R", icon="refresh-cw")
        self._export_action = self._action(
            "&Export Selection as PNG...", self._export, QKeySequence.StandardKey.Save, icon="image-down",
            tip="Export measured area as PNG",
        )
        self._export_annot_action = self._action(
            "Export PDF with &Annotations...", self._export_pdf_with_annotations, icon="file-down"
        )
        self._quit_action = self._action("&Quit", self.close, QKeySequence.StandardKey.Quit)
        self._print_action = self._action(
            "&Print...", self._print_document, QKeySequence.StandardKey.Print, icon="printer",
            name="action_print", tip="Print",
        )

        # Edit
        self._copy_action = self._action(
            "&Copy Measurements", self._copy, QKeySequence.StandardKey.Copy, icon="copy"
        )
        self._find_action = self._action("&Find...", self._show_find, "Ctrl+F", icon="search", tip="Find")
        self._find_next_action = self._action("Find &Next", self._find_next, "F3", tip="Next match")
        self._find_prev_action = self._action(
            "Find &Previous", self._find_prev, "Shift+F3", tip="Previous match"
        )
        self._clear_selection_action = self._action("C&lear Selection", self._on_escape, "Escape")

        # View: panels
        self._sidebar_action = self._action(
            "&Sidebar", self._toggle_sidebar, "F9", icon="panel-left", checkable=True, tip="Sidebar"
        )
        self._thumbs_panel_action = self._action(
            "&Thumbnails", lambda: self._toggle_sidebar_page("thumbnails"), "Ctrl+Shift+T", icon="layout-grid"
        )
        self._outline_panel_action = self._action(
            "&Outline", lambda: self._toggle_sidebar_page("outline"), "Ctrl+Shift+O", icon="list-tree"
        )
        self._bookmarks_panel_action = self._action(
            "&Bookmarks", lambda: self._toggle_sidebar_page("bookmarks"), "Ctrl+Shift+B", icon="bookmark"
        )
        self._annotations_panel_action = self._action(
            "&Annotations", lambda: self._toggle_sidebar_page("annotations"), "Ctrl+Shift+A",
            icon="message-square-text",
        )
        self._search_panel_action = self._action(
            "Search &Results", self._toggle_search_dock, "Ctrl+Shift+F", icon="list", checkable=True
        )
        self._inspector_action = self._action(
            "&Inspector", self._toggle_info_dock, "Ctrl+Shift+I", icon="panel-right", checkable=True
        )

        # View: zoom
        self._zoom_in_action = self._action(
            "Zoom &In", lambda: view().zoom_by(1.25), ["Ctrl++", "Ctrl+="], icon="zoom-in"
        )
        self._zoom_out_action = self._action("Zoom &Out", lambda: view().zoom_by(0.8), "Ctrl+-", icon="zoom-out")
        self._actual_size_action = self._action(
            "&Actual Size", lambda: view().actual_size(), "Ctrl+0", icon="scan"
        )
        self._fit_width_action = self._action(
            "Fit &Width", lambda: view().fit_width(), ["Ctrl+1", "W"], icon="move-horizontal"
        )
        self._fit_page_action = self._action(
            "Fit &Page", lambda: view().fit_page(), ["Ctrl+2", "F"], icon="expand"
        )

        # View: rotation, overlays, window
        self._rotate_left_action = self._action(
            "Rotate &Left", lambda: view().rotate_by(-90), "Ctrl+L", icon="rotate-ccw"
        )
        self._rotate_right_action = self._action(
            "Rotate &Right", lambda: view().rotate_by(90), "Ctrl+R", icon="rotate-cw"
        )
        self._reset_rotation_action = self._action("Reset R&otation", lambda: view().set_rotation(0))
        self._rulers_action = self._action("Show &Rulers", self._toggle_rulers, icon="ruler", checkable=True)
        self._rulers_action.setChecked(self._show_rulers)
        self._layout_grid_action = self._action(
            "Show Layout &Grid", self._toggle_layout_grid, icon="layout-grid", checkable=True
        )
        self._layout_grid_action.setChecked(bool(self._layout_grid.get("enabled", False)))
        self._layout_grid_settings_action = self._action("Layout Grid Settings...", self._show_layout_grid_dialog)
        self._perf_action = self._action("Performance Mode", self._on_performance_mode_toggled, checkable=True)
        self._perf_action.setStatusTip("Pause rendering during zoom/scroll - reduces CPU on large PDFs")
        self._fullscreen_action = self._action("&Full Screen", self._toggle_fullscreen, "F11", icon="fullscreen")
        self._presentation_action = self._action(
            "&Presentation", self._start_presentation, "F5", icon="presentation", name="action_presentation"
        )

        # View: page layout and reading colours (Phase B PdfView API; disabled until present)
        self._page_mode_group = QActionGroup(self)
        self._page_mode_group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        self._page_mode_actions: dict[str, QAction] = {}
        for mode, label in (
            ("single", "&Single Page"),
            ("continuous", "&Continuous"),
            ("two-page", "&Two Pages"),
            ("two-page-cover", "Two Pages with &Cover"),
        ):
            act = self._action(
                label, lambda _checked=False, m=mode: self._set_page_mode(m),
                name=f"action_page_mode_{mode.replace('-', '_')}", checkable=True,
            )
            self._page_mode_group.addAction(act)
            self._page_mode_actions[mode] = act
        self._color_mode_group = QActionGroup(self)
        self._color_mode_group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        self._color_mode_actions: dict[str, QAction] = {}
        for mode, label in (("normal", "&Normal"), ("night", "N&ight"), ("sepia", "&Sepia")):
            act = self._action(
                label, lambda _checked=False, m=mode: self._set_color_mode(m),
                name=f"action_color_mode_{mode}", checkable=True,
            )
            self._color_mode_group.addAction(act)
            self._color_mode_actions[mode] = act
        self._reset_layout_action = self._action("Reset Window &Layout", self._reset_window_layout)

        # Go
        self._prev_page_action = self._action(
            "&Previous Page", lambda: view().prev_page(), "PgUp", icon="chevron-up"
        )
        self._next_page_action = self._action(
            "&Next Page", lambda: view().next_page(), "PgDown", icon="chevron-down"
        )
        self._first_page_action = self._action(
            "&First Page", lambda: view().first_page(), "Home", icon="chevron-first"
        )
        self._last_page_action = self._action("&Last Page", lambda: view().last_page(), "End", icon="chevron-last")
        self._goto_page_action = self._action("&Go to Page...", self._focus_page_field, "Ctrl+G")
        self._back_action = self._action(
            "&Back", self._go_back, "Alt+Left", icon="arrow-left", name="action_go_back"
        )
        self._forward_action = self._action(
            "&Forward", self._go_forward, "Alt+Right", icon="arrow-right", name="action_go_forward"
        )
        self._next_tab_action = self._action("Next Ta&b", self._switch_to_next_tab, ["Ctrl+Tab", "Ctrl+PgDown"])
        self._prev_tab_action = self._action(
            "Previous T&ab", self._switch_to_previous_tab, ["Ctrl+Shift+Tab", "Ctrl+PgUp"]
        )
        self._next_tab_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self._prev_tab_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self._add_bookmark_action = self._action(
            "Add &Bookmark...", self._add_bookmark, "Ctrl+D", icon="bookmark-plus", tip="Bookmark this page"
        )

        # Tools
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)
        self._select_action = self._action(
            "&Select", lambda: self._on_tool_action(ToolMode.SELECT), "1", icon="mouse-pointer-2",
            checkable=True, tip="Select text",
        )
        self._hand_action = self._action(
            "&Hand", lambda: self._on_tool_action(ToolMode.HAND), "2", icon="hand", checkable=True,
            tip="Hand (pan)",
        )
        self._measure_action = self._action(
            "&Measure", lambda: self._on_tool_action(ToolMode.MEASURE), "3", icon="ruler-dimension-line",
            checkable=True,
        )
        self._annotate_action = self._action(
            "&Annotate", lambda: self._on_tool_action(ToolMode.ANNOTATE), "4", icon="pen-line",
            checkable=True,
        )
        for act in (self._select_action, self._hand_action, self._measure_action, self._annotate_action):
            self._tool_group.addAction(act)
        self._hand_action.setChecked(True)

        self._annot_highlight_action = self._action(
            "Add &Highlight (selection)", self._add_highlight, "Ctrl+Shift+H", icon="highlighter"
        )
        self._annot_underline_action = self._action(
            "Add &Underline (selection)", self._add_underline, "Ctrl+Shift+U", icon="underline"
        )
        self._annot_note_action = self._action(
            "Add &Note (selection)", self._add_note, "Ctrl+Shift+N", icon="sticky-note"
        )

        self._unit_group = QActionGroup(self)
        self._unit_group.setExclusive(True)
        self._unit_actions: dict[str, QAction] = {}
        for unit in UNITS:
            act = self._action(
                UNIT_LABELS[unit], lambda _checked=False, u=unit: self._set_unit(u),
                name=f"action_unit_{unit}", checkable=True,
            )
            act.setData(unit)
            act.setChecked(unit == self._unit)
            self._unit_group.addAction(act)
            self._unit_actions[unit] = act

        self._about_action = self._action(f"&About {APP_NAME}", self._show_about, icon="info")

        # Actions that need an open document; see _update_action_states.
        self._doc_actions = [
            self._close_tab_action, self._reload_action, self._export_action, self._export_annot_action,
            self._copy_action, self._find_next_action, self._find_prev_action,
            self._zoom_in_action, self._zoom_out_action, self._actual_size_action, self._fit_width_action,
            self._fit_page_action, self._rotate_left_action, self._rotate_right_action,
            self._reset_rotation_action, self._prev_page_action, self._next_page_action,
            self._first_page_action, self._last_page_action, self._goto_page_action,
            self._add_bookmark_action, self._annot_highlight_action, self._annot_underline_action,
            self._annot_note_action,
        ]

    def _setup_menus(self):
        bar = self.menuBar()

        file_m = bar.addMenu("&File")
        file_m.addAction(self._open_action)
        self._recent_menu = file_m.addMenu("Open &Recent")
        self._rebuild_recent_menu()
        file_m.addAction(self._close_tab_action)
        file_m.addAction(self._reload_action)
        file_m.addSeparator()
        file_m.addAction(self._print_action)
        file_m.addAction(self._export_action)
        file_m.addAction(self._export_annot_action)
        file_m.addSeparator()
        file_m.addAction(self._quit_action)
        self._file_menu = file_m

        edit_m = bar.addMenu("&Edit")
        edit_m.addAction(self._copy_action)
        edit_m.addAction(self._clear_selection_action)
        edit_m.addSeparator()
        edit_m.addAction(self._find_action)
        edit_m.addAction(self._find_next_action)
        edit_m.addAction(self._find_prev_action)
        self._edit_menu = edit_m

        view_m = bar.addMenu("&View")
        view_m.addAction(self._sidebar_action)
        panels_m = view_m.addMenu("Sidebar &Panel")
        for act in (
            self._thumbs_panel_action, self._outline_panel_action,
            self._bookmarks_panel_action, self._annotations_panel_action,
        ):
            panels_m.addAction(act)
        view_m.addAction(self._inspector_action)
        view_m.addAction(self._search_panel_action)
        view_m.addSeparator()
        zoom_m = view_m.addMenu("&Zoom")
        for act in (self._zoom_in_action, self._zoom_out_action):
            zoom_m.addAction(act)
        zoom_m.addSeparator()
        for act in (self._actual_size_action, self._fit_width_action, self._fit_page_action):
            zoom_m.addAction(act)
        self._page_layout_menu = view_m.addMenu("Page &Layout")
        for act in self._page_mode_actions.values():
            self._page_layout_menu.addAction(act)
        self._reading_mode_menu = view_m.addMenu("Reading &Mode")
        for act in self._color_mode_actions.values():
            self._reading_mode_menu.addAction(act)
        rotate_m = view_m.addMenu("R&otate")
        for act in (self._rotate_left_action, self._rotate_right_action, self._reset_rotation_action):
            rotate_m.addAction(act)
        view_m.addSeparator()
        view_m.addAction(self._rulers_action)
        view_m.addAction(self._layout_grid_action)
        view_m.addAction(self._layout_grid_settings_action)
        view_m.addAction(self._perf_action)
        view_m.addSeparator()
        view_m.addAction(self._fullscreen_action)
        view_m.addAction(self._presentation_action)
        view_m.addAction(self._reset_layout_action)
        self._view_menu = view_m

        go_m = bar.addMenu("&Go")
        for act in (self._first_page_action, self._prev_page_action, self._next_page_action, self._last_page_action):
            go_m.addAction(act)
        go_m.addAction(self._goto_page_action)
        go_m.addSeparator()
        go_m.addAction(self._back_action)
        go_m.addAction(self._forward_action)
        go_m.addSeparator()
        go_m.addAction(self._add_bookmark_action)
        go_m.addSeparator()
        go_m.addAction(self._next_tab_action)
        go_m.addAction(self._prev_tab_action)
        self._go_menu = go_m

        tools_m = bar.addMenu("&Tools")
        for act in (self._select_action, self._hand_action, self._measure_action, self._annotate_action):
            tools_m.addAction(act)
        tools_m.addSeparator()
        for act in (self._annot_highlight_action, self._annot_underline_action, self._annot_note_action):
            tools_m.addAction(act)
        tools_m.addSeparator()
        units_m = tools_m.addMenu("Measurement &Units")
        for act in self._unit_actions.values():
            units_m.addAction(act)
        self._tools_menu = tools_m

        help_m = bar.addMenu("&Help")
        help_m.addAction(self._about_action)
        self._help_menu = help_m

    def _setup_toolbar(self):
        tb = QToolBar("Main toolbar", self)
        tb.setObjectName("MainToolbar")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setIconSize(QSize(TOOLBAR_ICON, TOOLBAR_ICON))
        self.addToolBar(tb)
        self._main_toolbar = tb

        tb.addAction(self._sidebar_action)
        tb.addSeparator()
        tb.addAction(self._open_action)
        tb.addAction(self._print_action)
        tb.addSeparator()

        # -- Page navigation: [^] [ n ] / N [v]
        tb.addAction(self._prev_page_action)
        self._page_field = PageField(self)
        self._page_input = self._page_field.edit
        self._page_total_lbl = self._page_field.total_label
        # Commit on Enter or focus-out - typing "23" must not first jump to page 2.
        self._page_input.returnPressed.connect(lambda: self._on_page_nav_changed(self._page_input.text()))
        self._page_input.editingFinished.connect(self._on_page_field_editing_finished)
        tb.addWidget(self._page_field)
        tb.addAction(self._next_page_action)
        tb.addSeparator()

        # -- Zoom: [-] [125% v] [+]
        tb.addAction(self._zoom_out_action)
        self._zoom_combo = ZoomBox(self)
        # Apply only on commit (Enter / focus-out / preset pick) - not on every keystroke.
        self._zoom_combo.activated.connect(lambda _idx: self._on_zoom_combo_changed(self._zoom_combo.currentText()))
        zoom_line = self._zoom_combo.lineEdit()
        if zoom_line is not None:
            zoom_line.returnPressed.connect(lambda: self._on_zoom_combo_changed(self._zoom_combo.currentText()))
            zoom_line.editingFinished.connect(lambda: self._on_zoom_combo_changed(self._zoom_combo.currentText()))
        tb.addWidget(self._zoom_combo)
        tb.addAction(self._zoom_in_action)
        tb.addSeparator()

        # -- Tools: one segmented control
        self._tool_segment = ToolSegment(
            [self._select_action, self._hand_action, self._measure_action, self._annotate_action], self
        )
        tb.addWidget(self._tool_segment)

        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        # -- Inline search
        self._search_field = SearchField(self._icons, self)
        self._search_input = self._search_field.edit
        self._search_case_chk = self._search_field.case_button
        self._search_prev_btn = self._search_field.prev_button
        self._search_next_btn = self._search_field.next_button
        self._search_count_lbl = self._search_field.count_label
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_input.returnPressed.connect(self._find_next)
        self._search_field.previous_requested.connect(self._find_prev)
        self._search_case_chk.toggled.connect(self._on_search_options_changed)
        self._search_prev_btn.clicked.connect(self._find_prev)
        self._search_next_btn.clicked.connect(self._find_next)
        self._search_field.results_button.clicked.connect(self._toggle_search_dock)
        self._search_field.focus_changed.connect(self._on_search_focus_changed)
        self._find_engaged = False
        tb.addWidget(self._search_field)

        tb.addAction(self._inspector_action)

        # -- Overflow: less common actions
        self._overflow_menu = QMenu("More", self)
        self._overflow_menu.setObjectName("OverflowMenu")
        self._build_overflow_menu()
        self._overflow_btn = QToolButton(self)
        self._overflow_btn.setObjectName("OverflowButton")
        self._icons.bind(self._overflow_btn, "ellipsis")
        self._overflow_btn.setToolTip("More actions")
        self._overflow_btn.setAccessibleName("More actions")
        self._overflow_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._overflow_btn.setMenu(self._overflow_menu)
        tb.addWidget(self._overflow_btn)

    def _build_overflow_menu(self):
        m = self._overflow_menu
        m.clear()
        m.addMenu(self._recent_menu)
        m.addAction(self._reload_action)
        m.addSeparator()
        m.addMenu(self._page_layout_menu)
        m.addMenu(self._reading_mode_menu)
        m.addAction(self._rotate_left_action)
        m.addAction(self._rotate_right_action)
        m.addSeparator()
        m.addAction(self._back_action)
        m.addAction(self._forward_action)
        m.addAction(self._add_bookmark_action)
        m.addAction(self._copy_action)
        m.addAction(self._export_action)
        m.addAction(self._export_annot_action)
        m.addSeparator()
        m.addAction(self._rulers_action)
        m.addAction(self._layout_grid_action)
        m.addAction(self._fullscreen_action)
        m.addAction(self._presentation_action)

    def _setup_annotation_toolbar(self):
        """Create the contextual annotation toolbar (shown below the main toolbar)."""
        self.addToolBarBreak()
        self._ann_toolbar = AnnotationToolbar(self)
        self.addToolBar(self._ann_toolbar)
        self._ann_toolbar.setVisible(False)  # only visible when ANNOTATE tool is active

        self._ann_toolbar.type_changed.connect(self._on_ann_toolbar_type_changed)
        self._ann_toolbar.color_changed.connect(self._on_ann_toolbar_color_changed)
        self._ann_toolbar.opacity_changed.connect(self._on_ann_toolbar_opacity_changed)
        self._ann_toolbar.border_width_changed.connect(self._on_ann_toolbar_width_changed)

    def _setup_statusbar(self):
        self._status = ViewerStatusBar(self)
        self.setStatusBar(self._status)
        self._file_lbl = self._status.file_label
        self._page_count_lbl = self._status.page_label
        self._zoom_lbl = self._status.zoom_label
        self._perf_label = self._status.perf_label
        self._measure_lbl = self._status.measure_label

    # --------------------------- Panels ---------------------------
    def _hinted(self, widget: QWidget, hint: str, top: QWidget | None = None) -> tuple[QWidget, QLabel]:
        """Wrap ``widget`` with an optional ``top`` control and an empty-state hint label."""
        box = QWidget(self)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if top is not None:
            holder = QWidget(box)
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(8, 8, 8, 6)
            holder_layout.addWidget(top)
            layout.addWidget(holder)
        label = QLabel(hint, box)
        label.setObjectName("EmptyHint")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.hide()
        layout.addWidget(widget, 1)
        layout.addWidget(label)
        layout.addStretch(0)
        return box, label

    @staticmethod
    def _show_hint(widget: QWidget, hint: QLabel, empty: bool) -> None:
        hint.setVisible(empty)
        widget.setVisible(not empty)

    def _setup_docks(self):
        self._setup_sidebar()
        self._setup_inspector()
        self._setup_search_dock()

    def _setup_sidebar(self):
        self._sidebar = Sidebar(self._icons, self)

        # Thumbnails
        self._thumbs_list = QListWidget()
        self._thumbs_list.setObjectName("ThumbnailList")
        self._thumbs_list.setIconSize(self.THUMB_BOX)
        self._thumbs_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._thumbs_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._thumbs_list.setMovement(QListWidget.Movement.Static)
        # A fixed grid cell: the first item's (placeholder) icon must not decide the cell size.
        self._thumbs_list.setGridSize(QSize(self.THUMB_BOX.width() + 24, self.THUMB_BOX.height() + 30))
        self._thumbs_list.setWordWrap(False)
        # Every cell is the same fixed icon box, so let the view skip per-item size
        # queries; without this, laying out a 5000-page list took ~0.6 s.
        self._thumbs_list.setUniformItemSizes(True)
        self._thumbs_list.itemActivated.connect(self._jump_to_thumb)
        self._thumbs_list.itemClicked.connect(self._jump_to_thumb)
        self._thumbs_list.verticalScrollBar().valueChanged.connect(self._schedule_thumbnail_render)
        self._sidebar.add_page(
            "thumbnails", "layout-grid", "Thumbnails", self._thumbs_list, "Thumbnails (Ctrl+Shift+T)"
        )

        # Outline (document table of contents)
        self._outline_filter = QLineEdit()
        self._outline_filter.setPlaceholderText("Filter outline")
        self._outline_filter.setClearButtonEnabled(True)
        self._outline_filter.textChanged.connect(self._populate_outline)
        self._outline_tree = QTreeWidget()
        self._outline_tree.setObjectName("OutlineTree")
        self._outline_tree.setHeaderHidden(True)
        self._outline_tree.setRootIsDecorated(False)
        self._outline_tree.setUniformRowHeights(True)
        self._outline_tree.itemActivated.connect(self._jump_to_outline_item)
        self._outline_tree.itemClicked.connect(self._jump_to_outline_item)
        outline_page, self._outline_hint = self._hinted(
            self._outline_tree, "This document has no outline.", top=self._outline_filter
        )
        self._sidebar.add_page("outline", "list-tree", "Outline", outline_page, "Outline (Ctrl+Shift+O)")

        # Bookmarks (user bookmarks from the sidecar)
        self._bookmarks_list = QListWidget()
        self._bookmarks_list.setObjectName("BookmarksList")
        self._bookmarks_list.itemActivated.connect(self._jump_to_bookmark_item)
        self._bookmarks_list.itemClicked.connect(self._jump_to_bookmark_item)
        self._bookmarks_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bookmarks_list.customContextMenuRequested.connect(self._on_bookmarks_context_menu)
        bookmarks_page, self._bookmarks_hint = self._hinted(
            self._bookmarks_list, "No bookmarks yet.\nPress Ctrl+D to bookmark the current page."
        )
        add_bookmark_btn = QToolButton(self)
        add_bookmark_btn.setDefaultAction(self._add_bookmark_action)
        add_bookmark_btn.setAutoRaise(True)
        add_bookmark_btn.setIconSize(QSize(16, 16))
        self._sidebar.add_page(
            "bookmarks", "bookmark", "Bookmarks", bookmarks_page, "Bookmarks (Ctrl+Shift+B)",
            actions=add_bookmark_btn,
        )

        # Annotations
        self._annotation_filter = QComboBox()
        self._annotation_filter.addItems([
            "All", "Highlight", "Underline", "Strikethrough", "Note",
            "Text-box", "Rectangle", "Ellipse", "Line", "Arrow", "Freehand",
        ])
        self._annotation_filter.setToolTip("Show only one kind of annotation")
        self._annotation_filter.currentIndexChanged.connect(self._populate_annotation_list)
        self._annotation_list = QListWidget()
        self._annotation_list.setObjectName("annotation_list")
        self._annotation_list.itemActivated.connect(self._jump_to_annotation_item)
        self._annotation_list.itemClicked.connect(self._jump_to_annotation_item)
        annotations_box, self._annotations_hint = self._hinted(
            self._annotation_list,
            "No annotations.\nUse the Annotate tool (4), or measure an area and press Ctrl+Shift+H.",
            top=self._annotation_filter,
        )
        self._annotation_edit_btn = QPushButton("Properties")
        self._annotation_delete_btn = QPushButton("Delete")
        self._annotation_export_btn = QPushButton("Export PDF...")
        self._annotation_edit_btn.setToolTip("Edit annotation properties")
        self._annotation_delete_btn.setToolTip("Delete selected annotation (Delete key)")
        self._annotation_export_btn.setToolTip("Save a copy of the PDF with annotations embedded")
        for btn in (self._annotation_edit_btn, self._annotation_delete_btn, self._annotation_export_btn):
            btn.setProperty("secondary", True)
        self._annotation_edit_btn.clicked.connect(self._edit_selected_annotation)
        self._annotation_delete_btn.clicked.connect(self._delete_selected_annotation)
        self._annotation_export_btn.clicked.connect(self._export_pdf_with_annotations)
        ann_buttons = QHBoxLayout()
        ann_buttons.setContentsMargins(8, 6, 8, 8)
        ann_buttons.setSpacing(4)
        ann_buttons.addWidget(self._annotation_edit_btn)
        ann_buttons.addWidget(self._annotation_delete_btn)
        ann_buttons.addStretch(1)
        ann_buttons.addWidget(self._annotation_export_btn)
        annotations_box.layout().addLayout(ann_buttons)
        self._sidebar.add_page(
            "annotations", "message-square-text", "Annotations", annotations_box, "Annotations (Ctrl+Shift+A)"
        )

        self._sidebar_dock = QDockWidget("Sidebar", self)
        self._sidebar_dock.setObjectName("SidebarDock")
        self._sidebar_dock.setTitleBarWidget(QWidget(self._sidebar_dock))
        self._sidebar_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self._sidebar_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self._sidebar_dock.setWidget(self._sidebar)
        self._sidebar_dock.setMinimumWidth(200)
        self._sidebar_dock.setMaximumWidth(520)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._sidebar_dock)
        self._sidebar_dock.hide()
        self._sidebar_dock.visibilityChanged.connect(self._on_sidebar_visibility_changed)
        self._sidebar.current_changed.connect(self._on_sidebar_page_changed)

    def _setup_inspector(self):
        self._inspector = InspectorPanel(self._icons, self)
        panel = self._inspector
        self._measure_w = panel.measure_w
        self._measure_h = panel.measure_h
        self._measure_x = panel.measure_x
        self._measure_y = panel.measure_y
        self._font_name = panel.font_name
        self._font_size = panel.font_size
        self._font_style = panel.font_style
        self._doc_name = panel.doc_name
        self._doc_page = panel.doc_page
        self._doc_zoom = panel.doc_zoom
        self._doc_format = panel.doc_format
        self._doc_engine = panel.doc_engine
        self._doc_creator = panel.doc_creator
        self._doc_title = panel.doc_title
        self._doc_author = panel.doc_author
        self._doc_subject = panel.doc_subject
        self._doc_keywords = panel.doc_keywords
        self._doc_created = panel.doc_created
        self._doc_modified = panel.doc_modified
        self._doc_encryption = panel.doc_encryption
        self._doc_file_size = panel.doc_file_size
        self._reload_toggle = panel.reload_toggle
        self._reload_toggle.toggled.connect(self._toggle_auto_reload)
        panel.copy_button.clicked.connect(self._copy)
        panel.units_combo.currentIndexChanged.connect(
            lambda _i: self._set_unit(str(panel.units_combo.currentData()))
        )

        self._info_dock = QDockWidget("Inspector", self)
        self._info_dock.setObjectName("InspectorDock")
        self._info_dock.setTitleBarWidget(QWidget(self._info_dock))
        self._info_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self._info_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        container = QWidget(self._info_dock)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(panel.title_bar)
        layout.addWidget(panel, 1)
        panel.title_bar.close_requested.connect(lambda: self._set_inspector_visible(False))
        self._info_dock.setWidget(container)
        self._info_dock.setMinimumWidth(240)
        self._info_dock.setMaximumWidth(440)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._info_dock)
        self._info_dock.hide()
        self._info_dock.visibilityChanged.connect(
            lambda _v: self._inspector_action.setChecked(not self._info_dock.isHidden())
        )

    def _setup_search_dock(self):
        self._search_dock = QDockWidget("Search Results", self)
        self._search_dock.setObjectName("SearchDock")
        self._search_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self._search_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self._search_title = PanelTitleBar("Search Results", self._icons, self._search_dock)
        self._search_title.close_requested.connect(lambda: self._set_search_panel_visible(False))
        self._search_dock.setTitleBarWidget(self._search_title)

        self._search_results_list = QListWidget()
        self._search_results_list.setObjectName("SearchResultsList")
        self._search_results_list.itemActivated.connect(self._jump_to_search_item)
        self._search_results_list.itemClicked.connect(self._jump_to_search_item)
        search_panel = QWidget()
        search_panel.setObjectName("SearchPanel")
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.addWidget(self._search_results_list)
        self._search_dock.setWidget(search_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._search_dock)
        self._search_dock.hide()
        self._search_dock_sized = False
        self._search_dock.visibilityChanged.connect(lambda _v: self._sync_search_panel_buttons())

    # --------------------------- Panel toggles ---------------------------
    def _sync_search_panel_buttons(self):
        visible = not self._search_dock.isHidden()
        for widget in (self._search_panel_action, self._search_field.results_button):
            widget.blockSignals(True)
            widget.setChecked(visible)
            widget.blockSignals(False)

    def _set_search_panel_visible(self, visible: bool):
        first_show = visible and self._search_dock.isHidden() and not self._search_dock_sized
        self._search_dock.setVisible(visible)
        if first_show:
            # A results list needs a few rows, not half the window.
            self._search_dock_sized = True
            self.resizeDocks([self._search_dock], [170], Qt.Orientation.Vertical)
        self._settings.setValue("window/show_search", visible)
        self._sync_search_panel_buttons()

    def _toggle_search_dock(self):
        visible = self._search_dock.isHidden()
        self._set_search_panel_visible(visible)
        if visible:
            self._search_input.setFocus()
            self._search_input.selectAll()

    def _set_sidebar_visible(self, visible: bool):
        self._sidebar_dock.setVisible(visible)
        self._settings.setValue("window/show_sidebar", visible)
        self._sidebar_action.setChecked(visible)

    def _toggle_sidebar(self):
        self._set_sidebar_visible(self._sidebar_dock.isHidden())

    def _show_sidebar_page(self, key: str):
        self._sidebar.set_current(key)
        self._set_sidebar_visible(True)

    def _toggle_sidebar_page(self, key: str):
        if not self._sidebar_dock.isHidden() and self._sidebar.current_key() == key:
            self._set_sidebar_visible(False)
        else:
            self._show_sidebar_page(key)

    # Old names kept for callers and muscle memory (Ctrl+Shift+O / Ctrl+Shift+T).
    def _toggle_outline_dock(self):
        self._toggle_sidebar_page("outline")

    def _toggle_thumbs_dock(self):
        self._toggle_sidebar_page("thumbnails")

    def _on_sidebar_visibility_changed(self, _visible: bool):
        self._sidebar_action.setChecked(not self._sidebar_dock.isHidden())
        self._on_thumbs_visibility_changed(self._thumbs_list.isVisible())

    def _on_sidebar_page_changed(self, key: str):
        self._settings.setValue("window/sidebar_page", key)
        self._on_thumbs_visibility_changed(self._thumbs_list.isVisible())

    def _set_inspector_visible(self, visible: bool):
        self._info_dock.setVisible(visible)
        self._settings.setValue("window/show_inspector", visible)
        self._inspector_action.setChecked(visible)

    def _toggle_info_dock(self):
        self._set_inspector_visible(self._info_dock.isHidden())

    # --------------------------- Settings ---------------------------
    def _load_json_setting(self, key: str, default):
        raw = self._settings.value(key, "")
        if not raw:
            return default
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(str(raw))
        except (TypeError, ValueError):
            return default

    def _save_json_setting(self, key: str, value):
        self._settings.setValue(key, json.dumps(value))

    def _restore_persistent_ui(self):
        geometry = self._settings.value("window/geometry")
        restored_geometry = False
        if geometry:
            restored_geometry = self.restoreGeometry(geometry)
        if geometry and not restored_geometry:
            self._settings.remove("window/geometry")
        if not restored_geometry:
            self.resize(1280, 900)
        self._ensure_window_geometry()

        state = self._settings.value("window/state")
        restored_state = False
        if state:
            restored_state = self.restoreState(state)
        if state and not restored_state:
            self._settings.remove("window/state")
        # A restored state carries the user's own panel sizes.
        self._search_dock_sized = restored_state
        if not restored_state:
            show_sidebar = self._settings.value("window/show_sidebar", None)
            if show_sidebar is None:
                # Settings from before the sidebar existed: the outline and thumbnail
                # docks it replaces.
                show_sidebar = self._settings.value("window/show_outline", False, type=bool) or self._settings.value(
                    "window/show_thumbnails", False, type=bool
                )
            self._sidebar_dock.setVisible(str(show_sidebar).lower() in ("true", "1"))
            self._search_dock.setVisible(self._settings.value("window/show_search", False, type=bool))
            self._info_dock.setVisible(self._settings.value("window/show_inspector", False, type=bool))
        # The annotation toolbar's visibility follows the tool, not the saved state.
        self._ann_toolbar.setVisible(False)

        page = self._settings.value("window/sidebar_page", "", type=str)
        if page in self._sidebar.keys():
            self._sidebar.set_current(page)

        self._sidebar_action.setChecked(not self._sidebar_dock.isHidden())
        self._inspector_action.setChecked(not self._info_dock.isHidden())
        self._sync_search_panel_buttons()

        start_state = self._settings.value("window/start_state", "normal", type=str)
        if start_state == "fullscreen":
            QTimer.singleShot(0, self.showFullScreen)
        elif start_state == "maximized":
            # Use a small delay so the window is fully shown before maximizing,
            # which avoids some Linux WM glitches with dock widget state restore.
            QTimer.singleShot(100, self.showMaximized)

        self._auto_reload_enabled = self._settings.value("view/auto_reload", True, type=bool)
        self._reload_toggle.blockSignals(True)
        self._reload_toggle.setChecked(self._auto_reload_enabled)
        self._reload_toggle.blockSignals(False)
        self._rulers_action.blockSignals(True)
        self._rulers_action.setChecked(self._show_rulers)
        self._rulers_action.blockSignals(False)
        self._layout_grid_action.blockSignals(True)
        self._layout_grid_action.setChecked(bool(self._layout_grid.get("enabled", False)))
        self._layout_grid_action.blockSignals(False)
        self._set_unit(self._unit)

        saved_tool = self._settings.value("view/tool", ToolMode.HAND.name, type=str)
        if saved_tool in ToolMode.__members__:
            self._set_tool(ToolMode[saved_tool])

    def _save_persistent_ui(self):
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        if self.isFullScreen():
            self._settings.setValue("window/start_state", "fullscreen")
        elif self.isMaximized():
            self._settings.setValue("window/start_state", "maximized")
        else:
            self._settings.setValue("window/start_state", "normal")
        self._settings.setValue("window/show_search", not self._search_dock.isHidden())
        self._settings.setValue("window/show_sidebar", not self._sidebar_dock.isHidden())
        self._settings.setValue("window/sidebar_page", self._sidebar.current_key())
        self._settings.setValue("window/show_inspector", not self._info_dock.isHidden())
        self._settings.setValue("view/auto_reload", self._auto_reload_enabled)
        self._settings.setValue("view/show_rulers", self._show_rulers)
        self._settings.setValue("view/unit", self._unit)
        self._save_layout_grid_settings()
        self._settings.setValue("view/tool", self.current_view().tool.name)

    def _toggle_rulers(self, checked: bool):
        self._show_rulers = bool(checked)
        for idx in range(self._tabs.count()):
            widget = self._tabs.widget(idx)
            if isinstance(widget, PdfView):
                widget.set_show_rulers(self._show_rulers)
        self._settings.setValue("view/show_rulers", self._show_rulers)

    def _toggle_layout_grid(self, checked: bool):
        self._layout_grid["enabled"] = bool(checked)
        self._layout_grid_action.blockSignals(True)
        self._layout_grid_action.setChecked(bool(checked))
        self._layout_grid_action.blockSignals(False)
        self._apply_layout_grid_to_views()
        self._save_layout_grid_settings()

    def _show_layout_grid_dialog(self):
        dialog = LayoutGridDialog(self._layout_grid, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._layout_grid = dialog.grid_config
        self._layout_grid_action.blockSignals(True)
        self._layout_grid_action.setChecked(bool(self._layout_grid.get("enabled", False)))
        self._layout_grid_action.blockSignals(False)
        self._apply_layout_grid_to_views()
        self._save_layout_grid_settings()

    def _apply_layout_grid_to_views(self):
        for idx in range(self._tabs.count()):
            widget = self._tabs.widget(idx)
            if isinstance(widget, PdfView):
                widget.set_layout_grid_config(self._layout_grid)

    def _save_layout_grid_settings(self):
        self._settings.setValue("view/layout_grid_enabled", bool(self._layout_grid.get("enabled", False)))
        self._settings.setValue("view/layout_grid_corner_marks", bool(self._layout_grid.get("corner_marks", False)))
        self._settings.setValue("view/layout_grid_width", float(self._layout_grid.get("width", 72.0)))
        self._settings.setValue("view/layout_grid_height", float(self._layout_grid.get("height", 72.0)))
        self._settings.setValue("view/layout_grid_offset_x", float(self._layout_grid.get("offset_x", 0.0)))
        self._settings.setValue("view/layout_grid_offset_y", float(self._layout_grid.get("offset_y", 0.0)))
        self._settings.setValue("view/layout_grid_subdivisions", int(self._layout_grid.get("subdivisions", 0)))
        self._settings.setValue("view/layout_grid_corner_length", float(self._layout_grid.get("corner_length", 12.0)))
        self._settings.setValue("view/layout_grid_color", str(self._layout_grid.get("color", "#d92fd4")))

    def _ensure_window_geometry(self):
        available = self._best_available_geometry()
        if available.isEmpty():
            return

        frame = self.frameGeometry()
        visible = frame.intersected(available)

        too_small = frame.width() < 640 or frame.height() < 420
        mostly_offscreen = visible.width() < min(300, available.width()) or visible.height() < min(
            220, available.height()
        )
        if not too_small and not mostly_offscreen:
            return

        width = min(max(1100, int(available.width() * 0.88)), available.width())
        height = min(max(780, int(available.height() * 0.88)), available.height())
        x = available.left() + max(0, (available.width() - width) // 2)
        y = available.top() + max(0, (available.height() - height) // 2)
        self.setGeometry(x, y, width, height)

    def _best_available_geometry(self) -> QRect:
        screens = QGuiApplication.screens()
        if not screens:
            return QRect()

        frame = self.frameGeometry()
        if frame.isValid():
            center = frame.center()
            for screen in screens:
                if screen.geometry().contains(center):
                    return screen.availableGeometry()

        current_screen = self.screen() or QGuiApplication.primaryScreen()
        if current_screen is not None:
            return current_screen.availableGeometry()

        return max((screen.availableGeometry() for screen in screens), key=lambda rect: rect.width() * rect.height())

    def _center_window(self):
        available = self._best_available_geometry()
        if available.isEmpty():
            return
        frame = self.frameGeometry()
        self.move(
            available.left() + max(0, (available.width() - frame.width()) // 2),
            available.top() + max(0, (available.height() - frame.height()) // 2),
        )

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            if self._settings.value("window/start_state", "normal", type=str) == "maximized":
                self.showMaximized()
        else:
            self.showFullScreen()

    def _enforce_maximized_geometry(self):
        if self.isFullScreen() or self.isMaximized():
            return
        # On Linux some WMs bounce back from maximized; re-request maximize.
        self.showMaximized()

    def _reset_window_layout(self):
        self.showNormal()
        self.resize(1280, 900)
        self._center_window()

        self._set_search_panel_visible(False)
        self._set_sidebar_visible(False)
        self._set_inspector_visible(False)

        self._settings.remove("window/geometry")
        self._settings.remove("window/state")
        self._settings.setValue("window/start_state", "normal")
        self._status.showMessage("Window layout reset", 1500)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() != QEvent.Type.WindowStateChange:
            return

        now_maximized = self.isMaximized()
        if now_maximized:
            self._last_maximize_at = time.monotonic()
            return

        if self.isFullScreen():
            return

        old_maximized = False
        if isinstance(event, QWindowStateChangeEvent):
            old_maximized = bool(event.oldState() & Qt.WindowState.WindowMaximized)

        # Some Linux WMs briefly enter maximized then bounce back to normal.
        # Re-request showMaximized() — not needed on Windows where the WM behaves correctly.
        if sys.platform != "win32" and old_maximized and self._last_maximize_at > 0 and (time.monotonic() - self._last_maximize_at) < 1.5:
            QTimer.singleShot(50, self._enforce_maximized_geometry)

    def _schedule_session_save(self):
        view = self.current_view()
        ctx = self._context_for_view(view)
        if ctx.file_path and view.document:
            self._session_save_timer.start(300)

    def _save_document_session_for_view(self, view: PdfView):
        ctx = self._context_for_view(view)
        if not ctx.file_path or not view.document:
            return

        path = os.path.abspath(ctx.file_path)
        state: dict[str, object] = {
            "page": int(view.current_page),
            "zoom": float(view.zoom),
            "zoom_mode": view.zoom_mode,
        }
        # Page layout and reading colours are per document view state (viewer-api.md).
        for key in ("page_mode", "color_mode"):
            getter = getattr(view, key, None)
            if callable(getter):
                state[key] = str(getter())
        self._document_sessions[path] = state

    def _save_current_document_session(self):
        self._save_document_session_for_view(self.current_view())
        while len(self._document_sessions) > 50:
            first_key = next(iter(self._document_sessions))
            del self._document_sessions[first_key]
        self._save_json_setting("documents/session", self._document_sessions)

    def _restore_document_session(self, path: str) -> bool:
        if not path:
            return False
        abs_path = os.path.abspath(path)
        state = self._document_sessions.get(abs_path)
        if not state:
            state = self._document_sessions.get(path)
        if not state:
            target_norm = os.path.normcase(os.path.normpath(abs_path))
            for key, value in self._document_sessions.items():
                if not isinstance(key, str):
                    continue
                key_norm = os.path.normcase(os.path.normpath(os.path.abspath(key)))
                if key_norm == target_norm:
                    state = value
                    break
        if not state:
            return False

        view = self.current_view()

        try:
            zoom = float(state.get("zoom", 1.0))
            page = int(state.get("page", 0))
        except (TypeError, ValueError):
            return False

        for key, setter_name in (("page_mode", "set_page_mode"), ("color_mode", "set_color_mode")):
            setter = getattr(view, setter_name, None)
            if key in state and callable(setter):
                try:
                    setter(str(state[key]))
                except ValueError:
                    pass

        zoom_mode = str(state.get("zoom_mode", PdfView.ZOOM_MODE_CUSTOM))
        if zoom_mode == PdfView.ZOOM_MODE_FIT_WIDTH:
            view.fit_width()
        elif zoom_mode == PdfView.ZOOM_MODE_FIT_PAGE:
            view.fit_page()
        elif zoom_mode == PdfView.ZOOM_MODE_ACTUAL_SIZE:
            view.actual_size()
        else:
            view.set_zoom(zoom, immediate=True, zoom_mode=PdfView.ZOOM_MODE_CUSTOM)

        if 0 <= page < view.page_count:
            QTimer.singleShot(0, lambda p=page, v=view: v.go_to_page(p))
        return True

    # --------------------------- Recent files ---------------------------
    def _rebuild_recent_menu(self):
        if not self._recent_menu:
            return
        self._recent_menu.clear()
        if not self._recent_files:
            self._recent_menu.addAction("(Empty)").setEnabled(False)
            return
        for path in self._recent_files:
            act = self._recent_menu.addAction(path)
            act.triggered.connect(lambda _checked=False, p=path: self._open_file(p))

    def _add_recent_file(self, path: str):
        if not path:
            return
        path = os.path.abspath(path)
        if path in self._recent_files:
            self._recent_files.remove(path)
        self._recent_files.insert(0, path)
        self._recent_files = self._recent_files[:10]
        self._settings.setValue("recent_files", self._recent_files)
        self._rebuild_recent_menu()

    # --------------------------- File/document ---------------------------
    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf);;All (*)")
        if path:
            self._open_file(path)

    def _close_current_tab(self):
        self._close_tab_index(self._tabs.currentIndex())

    def _open_file(self, path: str):
        norm_path = os.path.abspath(path)
        if not os.path.exists(norm_path):
            self._status.showMessage("File not found", 1500)
            return

        existing = self._find_open_view(norm_path)
        if existing is not None:
            self._tabs.setCurrentWidget(existing)
            return

        current = self.current_view()
        ctx = self._context_for_view(current)
        create_new_tab = bool(current.document or ctx.file_path)

        target = self._create_tab() if create_new_tab else current
        target_ctx = self._context_for_view(target)

        self._save_current_document_session()
        self._stop_watch()
        self.setUpdatesEnabled(False)
        self._open_in_progress = True
        try:
            opened = target.open_document(norm_path)
            if not opened and self._view_can_unlock(target) and self._needs_password(norm_path):
                opened = self._unlock_and_open(target, norm_path)
            if not opened:
                if create_new_tab:
                    idx = self._tabs.indexOf(target)
                    if idx >= 0:
                        self._close_tab_index(idx)
                return

            target_ctx.file_path = norm_path
            target_ctx.search_query = ""
            target_ctx.search_results = []
            target_ctx.search_index = -1
            target_ctx.sidecar_error = ""

            loaded_state = load_sidecar(norm_path)
            target_ctx.sidecar_state = clamp_sidecar_for_page_count(loaded_state, target.page_count)
            self._load_native_pdf_annotations(target, target_ctx)
            target.set_annotations(target_ctx.sidecar_state.annotations + target_ctx.native_annotations)

            self._tabs.setCurrentWidget(target)
            self._set_tab_title(target)

            self._add_recent_file(norm_path)
            if not self._restore_document_session(norm_path):
                target.fit_width()

            self._set_current_file(norm_path)
            self.setWindowTitle(f"{APP_NAME} - {os.path.basename(norm_path)}")

            self._clear_search()
            # One full panel refresh (info, outline, thumbnails, annotation list)
            # now that the context is complete; document_loaded skipped it.
            self._refresh_document_info()
            self._update_status()
            self._update_mtime()
            self._start_watch()
            self._schedule_session_save()
        finally:
            self._open_in_progress = False
            self.setUpdatesEnabled(True)
            self.update()
            target.viewport().update()

    def _extract_pdf_paths_from_urls(self, urls: list[QUrl]) -> list[str]:
        paths: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if not url.isLocalFile():
                continue
            path = os.path.abspath(url.toLocalFile())
            if not path or not os.path.isfile(path):
                continue
            if not path.lower().endswith(".pdf"):
                continue
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
        return paths

    def _accept_drop_event(self, e) -> bool:
        mime = e.mimeData()
        paths = self._extract_pdf_paths_from_urls(mime.urls()) if mime and mime.hasUrls() else []
        if paths:
            e.acceptProposedAction()
            return True
        e.ignore()
        return False

    def _handle_drop_event(self, e) -> bool:
        mime = e.mimeData()
        paths = self._extract_pdf_paths_from_urls(mime.urls()) if mime and mime.hasUrls() else []
        if not paths:
            self._status.showMessage("Drop a local PDF file to open it", 2000)
            e.ignore()
            return False

        for path in paths:
            self._open_file(path)
        e.acceptProposedAction()
        return True

    def dragEnterEvent(self, e: QDragEnterEvent):
        self._accept_drop_event(e)

    def dragMoveEvent(self, e):
        self._accept_drop_event(e)

    def dropEvent(self, e: QDropEvent):
        self._handle_drop_event(e)

    def eventFilter(self, obj, e):
        is_drop_target = obj is self._tabs
        if not is_drop_target and isinstance(obj, PdfView):
            is_drop_target = True
        if not is_drop_target and isinstance(getattr(obj, "parent", lambda: None)(), PdfView):
            is_drop_target = True

        if is_drop_target:
            if e.type() == QEvent.Type.DragEnter or e.type() == QEvent.Type.DragMove:
                if self._accept_drop_event(e):
                    return True
            elif e.type() == QEvent.Type.Drop:
                if self._handle_drop_event(e):
                    return True
        return super().eventFilter(obj, e)

    def _refresh_document_info(self):
        view = self.current_view()
        ctx = self.current_context()
        doc = view.document

        if not doc:
            self._doc_name.setText("No file")
            self._doc_page.setText("0 / 0")
            self._doc_zoom.setText("--")
            self._doc_format.setText("--")
            self._doc_engine.setText("--")
            self._doc_creator.setText("--")
            self._doc_title.setText("--")
            self._doc_author.setText("--")
            self._doc_subject.setText("--")
            self._doc_keywords.setText("--")
            self._doc_created.setText("--")
            self._doc_modified.setText("--")
            self._doc_encryption.setText("--")
            self._doc_file_size.setText("--")
            self._page_field.set_pages(0, 0)
            self._status.set_page(0, 0)
            self._outline_tree.clear()
            self._outline_sync_index = None
            self._show_hint(self._outline_tree, self._outline_hint, True)
            self._populate_bookmarks()
            self._thumbs_list.clear()
            self._clear_thumbnail_queue()
            self._update_measurements_panel(None)
            self._populate_annotation_list()
            self.setWindowTitle(APP_NAME)
            return

        source_path = ctx.file_path or view.doc_path
        name = os.path.basename(source_path) if source_path else "Untitled"
        metadata = doc.metadata or {}
        self._doc_name.setText(name)
        self._doc_page.setText(f"{view.current_page + 1} / {doc.page_count}")
        self._doc_zoom.setText(f"{view.zoom * 100:.0f}%")
        self._doc_format.setText(self._metadata_text(metadata.get("format")))
        self._doc_engine.setText(self._metadata_text(metadata.get("producer")))
        self._doc_creator.setText(self._metadata_text(metadata.get("creator")))
        self._doc_title.setText(self._metadata_text(metadata.get("title")))
        self._doc_author.setText(self._metadata_text(metadata.get("author")))
        self._doc_subject.setText(self._metadata_text(metadata.get("subject")))
        self._doc_keywords.setText(self._metadata_text(metadata.get("keywords")))
        self._doc_created.setText(self._format_pdf_date(metadata.get("creationDate")))
        self._doc_modified.setText(self._format_pdf_date(metadata.get("modDate")))
        self._doc_encryption.setText(self._metadata_text(metadata.get("encryption"), empty="None"))
        self._doc_file_size.setText(self._format_file_size(source_path))
        self._page_field.set_pages(view.current_page + 1, doc.page_count)
        self._status.set_page(view.current_page + 1, doc.page_count)
        self.setWindowTitle(f"{APP_NAME} - {name}")

        self._populate_outline()
        self._populate_thumbnails()
        self._populate_annotation_list()

    # --------------------------- Navigation / TOC / bookmarks ---------------------------
    def _populate_outline(self):
        """Rebuild the outline (TOC) tree and the bookmarks list for the current tab."""
        self._outline_tree.clear()

        view = self.current_view()
        doc = view.document

        # One invisible root holds the flat, indented TOC; the tree shows its children.
        root_toc = QTreeWidgetItem(["Document TOC"])
        root_toc.setData(0, self.ROLE_KIND, "toc_root")
        self._outline_tree.addTopLevelItem(root_toc)
        root_toc.setExpanded(True)

        filt = self._outline_filter.text().strip().lower()

        toc_entries: list[tuple[int, int, QTreeWidgetItem]] = []
        has_toc = False
        if doc:
            for level, title, page in doc.get_toc(simple=True):
                has_toc = True
                page_idx = max(0, page - 1)
                if filt and filt not in title.lower() and filt not in str(page):
                    continue
                display = f"{'    ' * max(0, level - 1)}{title}"
                item = QTreeWidgetItem([display])
                item.setData(0, self.ROLE_KIND, "toc")
                item.setData(0, self.ROLE_PAGE, page_idx)
                item.setToolTip(0, f"{title.strip()} - page {page}")
                root_toc.addChild(item)
                toc_entries.append((page_idx, len(toc_entries), item))
        self._outline_tree.setRootIndex(self._outline_tree.indexFromItem(root_toc))
        self._show_hint(self._outline_tree, self._outline_hint, not has_toc)

        # Sorted by (page, outline order): bisecting for the last page <= current
        # lands on the same item the old linear scan picked (later entry wins ties).
        toc_entries.sort(key=lambda entry: (entry[0], entry[1]))
        self._outline_sync_index = (
            root_toc,
            [entry[0] for entry in toc_entries],
            [entry[2] for entry in toc_entries],
        )

        self._populate_bookmarks()
        self._sync_outline_current_page(view.current_page)

    def _populate_bookmarks(self):
        self._bookmarks_list.clear()
        ctx = self.current_context()
        for bookmark in ctx.sidecar_state.bookmarks:
            item = QListWidgetItem(f"{bookmark.title}  (p{bookmark.page + 1})")
            item.setData(self.ROLE_KIND, "bookmark")
            item.setData(self.ROLE_PAGE, bookmark.page)
            item.setData(self.ROLE_BOOKMARK_ID, bookmark.id)
            self._bookmarks_list.addItem(item)
        self._show_hint(self._bookmarks_list, self._bookmarks_hint, self._bookmarks_list.count() == 0)

    def _sync_outline_current_page(self, page_idx: int):
        nearest_item = None
        nearest_page = -1

        root_toc = self._outline_tree.topLevelItem(0)
        if root_toc is None:
            return

        # Runs on every scroll tick; a linear scan over the TOC cost ~4 ms per
        # tick with a 4963-entry outline. Use the index built by _populate_outline.
        index = self._outline_sync_index
        if index is not None and index[0] is root_toc:
            _root, pages, items = index
            pos = bisect_right(pages, page_idx) - 1
            if pos >= 0:
                self._outline_tree.blockSignals(True)
                self._outline_tree.setCurrentItem(items[pos])
                self._outline_tree.blockSignals(False)
            return

        for i in range(root_toc.childCount()):
            item = root_toc.child(i)
            if item.data(0, self.ROLE_KIND) != "toc":
                continue
            item_page = item.data(0, self.ROLE_PAGE)
            if not isinstance(item_page, int):
                continue
            if item_page <= page_idx and item_page >= nearest_page:
                nearest_page = item_page
                nearest_item = item

        if nearest_item is not None:
            self._outline_tree.blockSignals(True)
            self._outline_tree.setCurrentItem(nearest_item)
            self._outline_tree.blockSignals(False)

    def _jump_to_outline_item(self, item):
        if not isinstance(item, QTreeWidgetItem):
            return

        kind = item.data(0, self.ROLE_KIND)
        page_idx = item.data(0, self.ROLE_PAGE)
        if not isinstance(page_idx, int):
            return

        view = self.current_view()
        if kind == "toc":
            view.go_to_page(page_idx)
            return

        if kind == "bookmark":
            bookmark_id = item.data(0, self.ROLE_BOOKMARK_ID)
            bookmark = self._find_bookmark_by_id(str(bookmark_id)) if bookmark_id else None
            if bookmark:
                view.scroll_to_page_y(bookmark.page, bookmark.y)

    def _jump_to_bookmark_item(self, item):
        if not isinstance(item, QListWidgetItem):
            return
        bookmark_id = item.data(self.ROLE_BOOKMARK_ID)
        bookmark = self._find_bookmark_by_id(str(bookmark_id)) if bookmark_id else None
        if bookmark:
            self.current_view().scroll_to_page_y(bookmark.page, bookmark.y)

    def _on_bookmarks_context_menu(self, pos: QPoint):
        item = self._bookmarks_list.itemAt(pos)
        if item is None:
            return
        bookmark_id = item.data(self.ROLE_BOOKMARK_ID)
        if not bookmark_id:
            return

        menu = QMenu(self)
        rename_action = menu.addAction("Rename Bookmark")
        delete_action = menu.addAction("Delete Bookmark")
        chosen = menu.exec(self._bookmarks_list.viewport().mapToGlobal(pos))
        if chosen is rename_action:
            self._rename_bookmark(str(bookmark_id))
        elif chosen is delete_action:
            self._delete_bookmark(str(bookmark_id))

    def _find_bookmark_by_id(self, bookmark_id: str) -> BookmarkRecord | None:
        ctx = self.current_context()
        for bookmark in ctx.sidecar_state.bookmarks:
            if bookmark.id == bookmark_id:
                return bookmark
        return None

    def _add_bookmark(self):
        view = self.current_view()
        ctx = self.current_context()
        if not view.document or not ctx.file_path:
            self._status.showMessage("Open a PDF first", 1500)
            return

        page_idx = view.current_page
        if not (0 <= page_idx < len(view._pages)):
            return

        page_item = view._pages[page_idx]
        y_value = (view.verticalScrollBar().value() - page_item.pos().y()) / max(0.001, view.zoom)
        y_value = max(0.0, y_value)

        default_title = f"Page {page_idx + 1}"
        title, ok = QInputDialog.getText(self, "Add Bookmark", "Bookmark title:", text=default_title)
        if not ok:
            return
        title = title.strip() or default_title

        bookmark = BookmarkRecord(id=uuid4().hex, title=title, page=page_idx, y=float(y_value))
        ctx.sidecar_state.bookmarks.append(bookmark)
        self._mark_sidecar_dirty(view)
        self._populate_bookmarks()
        self._status.showMessage("Bookmark added", 1500)

    def _rename_bookmark(self, bookmark_id: str):
        bookmark = self._find_bookmark_by_id(bookmark_id)
        if bookmark is None:
            return

        title, ok = QInputDialog.getText(self, "Rename Bookmark", "Bookmark title:", text=bookmark.title)
        if not ok:
            return
        title = title.strip()
        if not title:
            return

        bookmark.title = title
        self._mark_sidecar_dirty(self.current_view())
        self._populate_bookmarks()

    def _delete_bookmark(self, bookmark_id: str):
        ctx = self.current_context()
        before = len(ctx.sidecar_state.bookmarks)
        ctx.sidecar_state.bookmarks = [b for b in ctx.sidecar_state.bookmarks if b.id != bookmark_id]
        if len(ctx.sidecar_state.bookmarks) != before:
            self._mark_sidecar_dirty(self.current_view())
            self._populate_bookmarks()
            self._status.showMessage("Bookmark deleted", 1200)

    # --------------------------- Sidecar save/load ---------------------------
    def _mark_sidecar_dirty(self, view: PdfView):
        timer = self._sidecar_timers.get(view)
        if timer is not None:
            timer.start(300)

    def _save_sidecar_for_view(self, view: PdfView):
        ctx = self._context_for_view(view)
        if not ctx.file_path:
            return

        try:
            ctx.sidecar_state = clamp_sidecar_for_page_count(ctx.sidecar_state, view.page_count)
            save_sidecar(ctx.file_path, ctx.sidecar_state)
            ctx.sidecar_error = ""
        except OSError as exc:
            ctx.sidecar_error = str(exc)
            if self._is_current_view(view):
                self._status.showMessage("Could not save sidecar (check folder write permission)", 3000)

    # --------------------------- Search ---------------------------
    def _active_search_text(self) -> str:
        return self._search_input.text().strip()

    def _show_find(self):
        """Ctrl+F: focus the toolbar search field and show the results panel.

        Pressed again while the field already has focus, it hides the panel again, so
        Ctrl+F still toggles the panel the way it did before search moved to the toolbar.
        """
        if not self._search_dock.isHidden() and (self._search_input.hasFocus() or self._find_engaged):
            self._find_engaged = False
            self._set_search_panel_visible(False)
            self.current_view().setFocus()
            return
        self._set_search_panel_visible(True)
        self._find_engaged = True
        self._search_input.setFocus()
        self._search_input.selectAll()

    def _on_search_focus_changed(self, focused: bool):
        # Leaving the field (clicking the page, a result, ...) ends the Ctrl+F "session":
        # the next Ctrl+F focuses the field again instead of closing the panel.
        if not focused:
            self._find_engaged = False

    def _on_escape(self):
        """Escape: leave the search field if it has focus, else clear the selection."""
        if self._search_input.hasFocus() or self._page_input.hasFocus():
            self.current_view().setFocus()
            return
        self.current_view().clear_all_selection()

    def _on_search_text_changed(self, text: str):
        if self._search_input_updating:
            return
        self._cancel_search_operation()
        ctx = self.current_context()
        ctx.search_query = text.strip()
        ctx.search_index = -1
        self._search_timer.start(240)

    def _on_search_options_changed(self, _checked: bool):
        if self._search_input_updating:
            return
        self._cancel_search_operation()
        self._search_timer.start(240)

    def _execute_live_search_current(self):
        self._execute_search_current(allow_short_query=False, max_results=self.MAX_LIVE_SEARCH_RESULTS)

    def _load_search_from_context(self):
        ctx = self.current_context()
        self._search_input_updating = True
        self._search_input.setText(ctx.search_query)
        self._search_input_updating = False
        self._populate_search_results_list()
        self._update_search_highlights()
        self._update_search_count_label(ctx)

    def _clear_search(self):
        self._search_timer.stop()
        self._cancel_search_operation()
        ctx = self.current_context()
        ctx.search_query = ""
        ctx.search_results = []
        ctx.search_index = -1
        self.current_view().set_search_highlights([])
        self._search_results_list.clear()
        self._search_count_lbl.setText("")

    def _update_search_count_label(self, ctx: TabContext | None = None):
        ctx = ctx or self.current_context()
        query = ctx.search_query.strip()
        if not query:
            self._search_count_lbl.setText("")
            return
        if self._search_operation and self._search_operation.get("ctx") is ctx:
            self._search_count_lbl.setText("Searching...")
            return
        if ctx.search_results and 0 <= ctx.search_index < len(ctx.search_results):
            self._search_count_lbl.setText(f"{ctx.search_index + 1}/{len(ctx.search_results)}")
            return
        if len(query) < self.MIN_LIVE_SEARCH_CHARS:
            self._search_count_lbl.setText(f"Type {self.MIN_LIVE_SEARCH_CHARS}+ chars")
            return
        self._search_count_lbl.setText("0/0")

    def _search_snippet(self, page: fitz.Page, rect: fitz.Rect) -> str:
        clip = fitz.Rect(rect.x0 - 80, rect.y0 - 10, rect.x1 + 80, rect.y1 + 10)
        clip &= page.rect
        text = page.get_textbox(clip).strip().replace("\n", " ")
        return text[:160] if text else "(match)"

    def _cancel_search_operation(self):
        self._search_batch_timer.stop()
        self._search_operation = None

    def _search_page_rects(self, page: fitz.Page, query: str) -> list[fitz.Rect]:
        return list(page.search_for(query))

    def _scan_search_batch(self, operation: dict[str, object]) -> bool:
        doc = operation["doc"]
        query = operation["query"]
        case_sensitive = bool(operation["case_sensitive"])
        result_limit = int(operation["result_limit"])
        results = operation["results"]
        page_idx = int(operation["page_idx"])
        processed_pages = 0
        started_at = time.perf_counter()

        while page_idx < doc.page_count:
            page = doc.load_page(page_idx)
            found = self._search_page_rects(page, query)
            for rect in found:
                if case_sensitive:
                    text = page.get_textbox(rect)
                    if query not in text:
                        continue
                snippet = self._search_snippet(page, rect)
                results.append(
                    SearchMatch(
                        page_idx=page_idx,
                        rect=(float(rect.x0), float(rect.y0), float(rect.width), float(rect.height)),
                        snippet=snippet,
                    )
                )
                if len(results) >= result_limit:
                    operation["page_idx"] = page_idx + 1
                    return True

            page_idx += 1
            processed_pages += 1
            if processed_pages >= self.SEARCH_BATCH_PAGES:
                break
            if (time.perf_counter() - started_at) * 1000.0 >= self.SEARCH_BATCH_TIME_BUDGET_MS:
                break

        operation["page_idx"] = page_idx
        return page_idx >= doc.page_count or len(results) >= result_limit

    def _apply_search_results(self, view: PdfView, ctx: TabContext, results: list[SearchMatch], post_nav: int = 0):
        ctx.search_results = list(results)
        ctx.search_index = 0 if results else -1

        self._populate_search_results_list()
        self._update_search_highlights()

        if results and post_nav:
            ctx.search_index = (ctx.search_index + post_nav) % len(ctx.search_results)
            self._go_to_search_result()
        else:
            self._update_search_count_label(ctx)

    def _process_search_batch(self):
        operation = self._search_operation
        if operation is None:
            return

        view = operation["view"]
        ctx = operation["ctx"]
        if (
            view is not self.current_view()
            or ctx is not self.current_context()
            or view.document is not operation["doc"]
        ):
            self._cancel_search_operation()
            return

        try:
            completed = self._scan_search_batch(operation)
        except Exception:
            self._cancel_search_operation()
            return
        if not completed:
            self._search_batch_timer.start(0)
            return

        results = list(operation["results"])
        post_nav = int(operation.get("post_nav", 0))
        self._cancel_search_operation()
        self._apply_search_results(view, ctx, results, post_nav=post_nav)

    def _execute_search_current(
        self,
        allow_short_query: bool = True,
        max_results: int | None = None,
        post_nav: int = 0,
    ):
        self._search_timer.stop()
        view = self.current_view()
        ctx = self.current_context()
        doc = view.document
        query = ctx.search_query.strip()
        result_limit = max_results if max_results is not None else self.MAX_SEARCH_RESULTS

        self._cancel_search_operation()
        if not doc:
            self._clear_search()
            return
        if not query:
            ctx.search_results = []
            ctx.search_index = -1
            self._populate_search_results_list()
            view.set_search_highlights([])
            self._update_search_count_label(ctx)
            return
        if not allow_short_query and len(query) < self.MIN_LIVE_SEARCH_CHARS:
            ctx.search_results = []
            ctx.search_index = -1
            self._populate_search_results_list()
            view.set_search_highlights([])
            self._update_search_count_label(ctx)
            return

        case_sensitive = self._search_case_chk.isChecked()
        if doc.page_count <= self.SEARCH_SYNC_PAGE_THRESHOLD:
            operation: dict[str, object] = {
                "doc": doc,
                "query": query,
                "case_sensitive": case_sensitive,
                "result_limit": result_limit,
                "results": [],
                "page_idx": 0,
            }
            while not self._scan_search_batch(operation):
                pass
            self._apply_search_results(view, ctx, operation["results"], post_nav=post_nav)
            return

        ctx.search_results = []
        ctx.search_index = -1
        self._populate_search_results_list()
        view.set_search_highlights([])
        self._search_operation = {
            "view": view,
            "ctx": ctx,
            "doc": doc,
            "query": query,
            "case_sensitive": case_sensitive,
            "result_limit": result_limit,
            "results": [],
            "page_idx": 0,
            "post_nav": post_nav,
        }
        self._update_search_count_label(ctx)
        self._process_search_batch()

    def _populate_search_results_list(self):
        ctx = self.current_context()
        self._search_results_list.clear()

        for i, match in enumerate(ctx.search_results):
            item = QListWidgetItem(f"p{match.page_idx + 1}: {html.escape(match.snippet)}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._search_results_list.addItem(item)

        if 0 <= ctx.search_index < self._search_results_list.count():
            self._search_results_list.setCurrentRow(ctx.search_index)
        count = len(ctx.search_results)
        self._search_title.title.setText(
            f"Search Results - {count} match{'es' if count != 1 else ''}" if ctx.search_query else "Search Results"
        )

    def _jump_to_search_item(self, item: QListWidgetItem):
        if item is None:
            return
        idx = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(idx, int):
            return
        ctx = self.current_context()
        if not (0 <= idx < len(ctx.search_results)):
            return
        ctx.search_index = idx
        self._go_to_search_result()

    def _update_search_highlights(self):
        view = self.current_view()
        ctx = self.current_context()

        if not ctx.search_results:
            view.set_search_highlights([])
            return

        current_page = view.current_page
        highlights = []
        for i, match in enumerate(ctx.search_results):
            if i == ctx.search_index or match.page_idx == current_page:
                rect = QRectF(match.rect[0], match.rect[1], match.rect[2], match.rect[3])
                highlights.append((match.page_idx, rect, i == ctx.search_index))

        view.set_search_highlights(highlights)

    def _go_to_search_result(self):
        view = self.current_view()
        ctx = self.current_context()
        if not ctx.search_results or not (0 <= ctx.search_index < len(ctx.search_results)):
            return

        match = ctx.search_results[ctx.search_index]
        rect = fitz.Rect(match.rect[0], match.rect[1], match.rect[0] + match.rect[2], match.rect[1] + match.rect[3])
        view.scroll_to_rect(match.page_idx, rect)
        self._update_search_highlights()

        if 0 <= ctx.search_index < self._search_results_list.count():
            self._search_results_list.blockSignals(True)
            self._search_results_list.setCurrentRow(ctx.search_index)
            self._search_results_list.blockSignals(False)

        self._search_count_lbl.setText(f"{ctx.search_index + 1}/{len(ctx.search_results)}")
        self._status.showMessage(f"Match {ctx.search_index + 1}/{len(ctx.search_results)}", 1500)

    def _find_next(self):
        ctx = self.current_context()
        query = self._active_search_text()
        if not query:
            return
        if query != ctx.search_query or not ctx.search_results:
            ctx.search_query = query
            self._execute_search_current(post_nav=1)
            if self._search_operation is not None:
                return
        if not ctx.search_results:
            self._status.showMessage("No matches", 1500)
            self._update_search_count_label(ctx)
            return

        ctx.search_index = (ctx.search_index + 1) % len(ctx.search_results)
        self._go_to_search_result()

    def _find_prev(self):
        ctx = self.current_context()
        query = self._active_search_text()
        if not query:
            return
        if query != ctx.search_query or not ctx.search_results:
            ctx.search_query = query
            self._execute_search_current(post_nav=-1)
            if self._search_operation is not None:
                return
        if not ctx.search_results:
            self._status.showMessage("No matches", 1500)
            self._update_search_count_label(ctx)
            return

        ctx.search_index = (ctx.search_index - 1) % len(ctx.search_results)
        self._go_to_search_result()

    # --------------------------- Annotation manager ---------------------------
    def _annotation_filter_kind(self) -> str:
        text = self._annotation_filter.currentText().strip().lower()
        if text == "all":
            return "all"
        return text

    def _populate_annotation_list(self):
        ctx = self.current_context()

        self._annotation_list.clear()
        filt = self._annotation_filter_kind()

        for ann in ctx.sidecar_state.annotations:
            if filt != "all" and ann.type != filt:
                continue
            preview = ann.contents.strip() if ann.contents else ""
            if not preview:
                preview = f"{ann.rect[2]:.0f}x{ann.rect[3]:.0f}"
            prefix = ann.type[:1].upper()
            item = QListWidgetItem(f"[{prefix}] p{ann.page + 1}: {preview[:60]}")
            item.setData(Qt.ItemDataRole.UserRole, ann.id)
            self._annotation_list.addItem(item)

        for ann in ctx.native_annotations:
            if filt != "all" and ann.type != filt:
                continue
            preview = ann.contents.strip() if ann.contents else ""
            if not preview:
                preview = f"{ann.rect[2]:.0f}x{ann.rect[3]:.0f}"
            prefix = ann.type[:1].upper()
            item = QListWidgetItem(f"[{prefix}] p{ann.page + 1}: {preview[:50]} (PDF)")
            item.setData(Qt.ItemDataRole.UserRole, ann.id)
            tip = f"Native PDF annotation ({ann.type}) — read-only"
            if ann.contents:
                tip += f"\n{html.escape(ann.contents)}"
            item.setToolTip(tip)
            self._annotation_list.addItem(item)

        empty = not (ctx.sidecar_state.annotations or ctx.native_annotations)
        self._show_hint(self._annotation_list, self._annotations_hint, empty)

        # Do not call view.set_annotations() here — that triggers a full scene
        # rebuild on every filter change.  set_annotations() is called only when
        # annotation data actually changes (load, create, delete, edit).

    def _find_annotation_by_id(self, ann_id: str) -> AnnotationRecord | None:
        ctx = self.current_context()
        for ann in ctx.sidecar_state.annotations:
            if ann.id == ann_id:
                return ann
        for ann in ctx.native_annotations:
            if ann.id == ann_id:
                return ann
        return None

    def _is_native_annotation_id(self, ann_id: str) -> bool:
        return ann_id.startswith("native-")

    def _selected_annotation_id(self) -> str | None:
        item = self._annotation_list.currentItem()
        if item is None:
            return None
        ann_id = item.data(Qt.ItemDataRole.UserRole)
        return str(ann_id) if ann_id else None

    def _jump_to_annotation_item(self, item: QListWidgetItem):
        if item is None:
            return
        ann_id = item.data(Qt.ItemDataRole.UserRole)
        if not ann_id:
            return
        ann = self._find_annotation_by_id(str(ann_id))
        if ann is None:
            return
        self.current_view().scroll_to_page_y(ann.page, ann.rect[1])

    def _on_view_annotation_clicked(self, view: PdfView, ann_id: str):
        if not self._is_current_view(view):
            return
        for i in range(self._annotation_list.count()):
            item = self._annotation_list.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole)) == ann_id:
                self._annotation_list.setCurrentItem(item)
                break
        # Bring the list into view when the sidebar is open; never pop panels open.
        if not self._sidebar_dock.isHidden():
            self._sidebar.set_current("annotations")

    def _edit_selected_annotation(self):
        ann_id = self._selected_annotation_id()
        if not ann_id:
            return
        if self._is_native_annotation_id(ann_id):
            self._status.showMessage("Native PDF annotations are read-only", 1500)
            return
        ann = self._find_annotation_by_id(ann_id)
        if ann is None:
            return
        self._open_annotation_properties_dialog(ann)

    def _open_annotation_properties_dialog(self, ann: AnnotationRecord):
        """Open the annotation properties / edit dialog."""
        dlg = AnnotationPropertiesDialog(ann, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        dlg.apply_to(ann)
        self._mark_sidecar_dirty(self.current_view())
        self._populate_annotation_list()

    def _delete_selected_annotation(self):
        ann_id = self._selected_annotation_id()
        if not ann_id:
            return
        if self._is_native_annotation_id(ann_id):
            self._status.showMessage("Native PDF annotations cannot be deleted here", 1500)
            return

        ctx = self.current_context()
        before = len(ctx.sidecar_state.annotations)
        ctx.sidecar_state.annotations = [ann for ann in ctx.sidecar_state.annotations if ann.id != ann_id]
        if len(ctx.sidecar_state.annotations) == before:
            return

        cur_view = self.current_view()
        self._mark_sidecar_dirty(cur_view)
        cur_view.set_annotations(ctx.sidecar_state.annotations + ctx.native_annotations)
        self._populate_annotation_list()
        self._status.showMessage("Annotation deleted", 1200)

    def _build_annotation_from_selection(self, ann_type: str) -> AnnotationRecord | None:
        view = self.current_view()
        sel = view.selection_rect
        page_idx = view.selection_page

        if sel is None or page_idx < 0:
            self._status.showMessage("Create a selection first", 1500)
            return None

        contents = ""
        if ann_type == "note":
            text, ok = QInputDialog.getMultiLineText(self, "Add Note", "Note text:")
            if not ok:
                return None
            contents = text

        color = {
            "highlight": "#f7c948",
            "underline": "#7ab4ff",
            "note": "#5b8df6",
        }.get(ann_type, "#f7c948")

        return AnnotationRecord(
            id=uuid4().hex,
            type=ann_type,
            page=page_idx,
            rect=(float(sel.x()), float(sel.y()), float(sel.width()), float(sel.height())),
            color=color,
            opacity=0.3 if ann_type == "highlight" else 0.95 if ann_type == "underline" else 0.9,
            contents=contents,
        )

    def _add_annotation(self, ann_type: str):
        view = self.current_view()
        ctx = self.current_context()
        if not view.document or not ctx.file_path:
            self._status.showMessage("Open a PDF first", 1500)
            return

        record = self._build_annotation_from_selection(ann_type)
        if record is None:
            return

        ctx.sidecar_state.annotations.append(record)
        self._mark_sidecar_dirty(view)
        view.set_annotations(ctx.sidecar_state.annotations + ctx.native_annotations)
        self._populate_annotation_list()
        self._status.showMessage(f"Added {ann_type}", 1200)

    def _add_highlight(self):
        self._add_annotation("highlight")

    def _add_underline(self):
        self._add_annotation("underline")

    def _add_note(self):
        self._add_annotation("note")

    # ------ New annotation signal handlers ------

    def _on_view_annotation_created(self, view: PdfView, record: AnnotationRecord):
        """Called when annotation is drawn directly on the canvas."""
        if not self._is_current_view(view):
            return
        ctx = self._context_for_view(view)
        if not ctx.file_path:
            self._status.showMessage("Open a PDF first", 1500)
            return
        ctx.sidecar_state.annotations.append(record)
        self._mark_sidecar_dirty(view)
        view.set_annotations(ctx.sidecar_state.annotations + ctx.native_annotations)
        self._populate_annotation_list()
        self._status.showMessage(f"Added {record.type}", 1200)

    def _on_view_annotation_deleted(self, view: PdfView, ann_id: str):
        """Called when Delete key or context menu removes an annotation."""
        if not self._is_current_view(view):
            return
        ctx = self._context_for_view(view)
        before = len(ctx.sidecar_state.annotations)
        ctx.sidecar_state.annotations = [a for a in ctx.sidecar_state.annotations if a.id != ann_id]
        if len(ctx.sidecar_state.annotations) < before:
            self._mark_sidecar_dirty(view)
            view.set_annotations(ctx.sidecar_state.annotations + ctx.native_annotations)
            self._populate_annotation_list()
            self._status.showMessage("Annotation deleted", 1200)

    def _on_view_annotation_edit_requested(self, view: PdfView, ann_id: str):
        """Called on double-click or context menu Edit."""
        if not self._is_current_view(view):
            return
        ann = self._find_annotation_by_id(ann_id)
        if ann:
            self._open_annotation_properties_dialog(ann)

    # ------ Annotation toolbar sync ------

    def _on_ann_toolbar_type_changed(self, type_key: str):
        self.current_view().annotate_type = type_key

    def _on_ann_toolbar_color_changed(self, color: str):
        self.current_view().annotate_color = color

    def _on_ann_toolbar_opacity_changed(self, opacity: float):
        self.current_view().annotate_opacity = opacity

    def _on_ann_toolbar_width_changed(self, width: float):
        self.current_view().annotate_border_width = width

    # ------ Export annotations to PDF ------

    def _export_pdf_with_annotations(self):
        """Save a copy of the current PDF with embedded annotations."""
        view = self.current_view()
        ctx = self.current_context()
        if not view.document or not ctx.file_path:
            self._status.showMessage("Open a PDF first", 1500)
            return
        if not ctx.sidecar_state.annotations:
            self._status.showMessage("No annotations to export", 1500)
            return

        src = ctx.file_path
        base, ext = os.path.splitext(src)
        default_out = f"{base}_annotated{ext}"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Annotated PDF", default_out, "PDF Files (*.pdf)"
        )
        if not out_path:
            return

        try:
            export_annotated_pdf(src, ctx.sidecar_state.annotations, out_path)
            self._status.showMessage(f"Saved annotated PDF to {os.path.basename(out_path)}", 3000)
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", f"Could not export annotations:\n{exc}")

    # --------------------------- Thumbnails ---------------------------
    def _populate_thumbnails(self):
        self._clear_thumbnail_queue()
        self._thumbs_list.clear()

        view = self.current_view()
        ctx = self.current_context()
        doc = view.document
        if not doc:
            return

        source_path = ctx.file_path or view.doc_path
        self._thumb_source_key = os.path.abspath(source_path) if source_path else f"doc-{id(doc)}"
        self._thumb_icon_cache = {k: v for k, v in self._thumb_icon_cache.items() if k[0] == self._thumb_source_key}

        # The panel is hidden by default. Building one list item per page (and
        # rendering thumbnails for the current page on every scroll tick) for a
        # panel nobody sees is wasted O(pages) work on open; build it when the
        # panel is shown instead (_on_thumbs_visibility_changed).
        if not self._thumbs_list.isVisible():
            return

        placeholder = self._thumb_placeholder(doc)
        for i in range(doc.page_count):
            item = QListWidgetItem(f"{i + 1}")
            cached = self._thumb_icon_cache.get((self._thumb_source_key, i))
            item.setIcon(cached if cached is not None else placeholder)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._thumbs_list.addItem(item)
        if 0 <= view.current_page < doc.page_count:
            self._thumbs_list.blockSignals(True)
            self._thumbs_list.setCurrentRow(view.current_page)
            self._thumbs_list.blockSignals(False)

        self._schedule_thumbnail_render()

    def _thumb_size(self, width: float, height: float) -> tuple[float, int, int]:
        """Scale and pixel size that fit a ``width`` x ``height`` pt page into THUMB_BOX."""
        box = self.THUMB_BOX
        scale = min(box.width() / max(width, 1.0), box.height() / max(height, 1.0))
        return scale, max(1, round(width * scale)), max(1, round(height * scale))

    def _thumb_placeholder(self, doc) -> QIcon:
        """A blank page outline in the first page's proportions, shown until rendered."""
        try:
            rect = doc.load_page(0).rect
            _scale, w, h = self._thumb_size(rect.width, rect.height)
        except Exception:
            w, h = self.THUMB_BOX.width(), self.THUMB_BOX.height()
        t = theme.tokens()
        pix = QPixmap(w, h)
        pix.fill(QColor(t["surface"]))
        painter = QPainter(pix)
        painter.setPen(QColor(t["border_strong"]))
        painter.drawRect(0, 0, w - 1, h - 1)
        painter.end()
        return QIcon(pix)

    def _on_thumbs_visibility_changed(self, visible: bool):
        doc = self.current_view().document
        if visible and doc is not None and self._thumbs_list.count() != doc.page_count:
            self._populate_thumbnails()
        else:
            self._schedule_thumbnail_render()

    def _clear_thumbnail_queue(self):
        self._thumb_timer.stop()
        self._thumb_queue.clear()
        self._thumb_queued.clear()
        if not self.current_view().document:
            self._thumb_source_key = ""

    def _enqueue_thumbnail(self, page_idx: int, front: bool = False):
        if page_idx < 0 or page_idx >= self._thumbs_list.count():
            return
        if page_idx in self._thumb_queued:
            return
        cache_key = (self._thumb_source_key, page_idx)
        if cache_key in self._thumb_icon_cache:
            return
        if front:
            self._thumb_queue.appendleft(page_idx)
        else:
            self._thumb_queue.append(page_idx)
        self._thumb_queued.add(page_idx)

    def _schedule_thumbnail_render(self):
        view = self.current_view()
        doc = view.document
        if not doc or self._thumbs_list.count() == 0:
            return

        count = self._thumbs_list.count()
        viewport = self._thumbs_list.viewport()
        top_idx = self._thumbs_list.indexAt(QPoint(8, 8))
        bottom_idx = self._thumbs_list.indexAt(QPoint(8, max(8, viewport.height() - 8)))
        visible_start = top_idx.row() if top_idx.isValid() else 0
        visible_end = bottom_idx.row() if bottom_idx.isValid() else min(count - 1, visible_start + 8)
        start = max(0, visible_start - 6)
        end = min(count - 1, visible_end + 6)

        for idx in range(visible_end, visible_start - 1, -1):
            self._enqueue_thumbnail(idx, front=True)
        for idx in range(start, visible_start):
            self._enqueue_thumbnail(idx)
        for idx in range(visible_end + 1, end + 1):
            self._enqueue_thumbnail(idx)

        self._enqueue_thumbnail(view.current_page, front=True)

        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(8)

    def _render_thumbnail_batch(self):
        view = self.current_view()
        doc = view.document
        if not doc or self._thumbs_list.count() == 0:
            self._clear_thumbnail_queue()
            return

        rendered = 0
        while self._thumb_queue and rendered < 4:
            page_idx = self._thumb_queue.popleft()
            self._thumb_queued.discard(page_idx)
            if page_idx < 0 or page_idx >= doc.page_count:
                continue

            cache_key = (self._thumb_source_key, page_idx)
            icon = self._thumb_icon_cache.get(cache_key)
            if icon is None:
                try:
                    page = doc.load_page(page_idx)
                    scale, _w, _h = self._thumb_size(page.rect.width, page.rect.height)
                    dpr = max(1.0, float(self._thumbs_list.devicePixelRatioF()))
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale * dpr, scale * dpr), alpha=False)
                    image = QImage(
                        pix.samples,
                        pix.width,
                        pix.height,
                        pix.stride,
                        QImage.Format.Format_RGB888,
                    ).copy()
                    painter = QPainter(image)
                    painter.setPen(QColor(theme.tokens()["border_strong"]))
                    painter.drawRect(0, 0, image.width() - 1, image.height() - 1)
                    painter.end()
                    pixmap = QPixmap.fromImage(image)
                    pixmap.setDevicePixelRatio(dpr)
                    icon = QIcon(pixmap)
                    self._thumb_icon_cache[cache_key] = icon
                except Exception:
                    icon = icons.icon("image")

            item = self._thumbs_list.item(page_idx)
            if item is not None:
                item.setIcon(icon)
            rendered += 1

        if len(self._thumb_icon_cache) > 600:
            self._thumb_icon_cache = dict(list(self._thumb_icon_cache.items())[-600:])

        if self._thumb_queue:
            self._thumb_timer.start(8)

    def _jump_to_thumb(self, item: QListWidgetItem):
        page_idx = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(page_idx, int):
            self.current_view().go_to_page(page_idx)

    # --------------------------- View signal handlers ---------------------------
    def _on_view_selection_changed(self, view: PdfView):
        if self._is_current_view(view):
            self._update_status()

    def _on_view_zoom_changed(self, view: PdfView):
        if self._is_current_view(view):
            self._update_status()
        self._schedule_session_save()

    def _on_page_nav_changed(self, text: str):
        raw = text.strip()
        if not raw:
            return
        # Guard: returnPressed and editingFinished both fire on Enter.
        if getattr(self, "_page_nav_in_progress", False):
            return
        try:
            page = int(raw)
        except ValueError:
            return
        view = self.current_view()
        if not view.document or not (1 <= page <= view.page_count):
            return
        if view.current_page + 1 == page:
            return  # already there - no-op the duplicate fire.
        self._page_nav_in_progress = True
        try:
            view.go_to_page(page - 1)
        finally:
            self._page_nav_in_progress = False
        self._page_input.setText(str(view.current_page + 1))

    def _on_page_field_editing_finished(self):
        self._on_page_nav_changed(self._page_input.text())
        # Focus-out with junk or an out-of-range number shows the real page again.
        view = self.current_view()
        self._page_field.set_pages(view.current_page + 1 if view.document else 0, view.page_count)

    def _focus_page_field(self):
        self._page_input.setFocus()
        self._page_input.selectAll()

    def _on_view_page_changed(self, view: PdfView, current: int, total: int):
        if not self._is_current_view(view):
            return

        self._doc_page.setText(f"{current} / {total}")
        self._page_field.set_pages(current, total)
        self._status.set_page(current, total)

        if total == self._thumbs_list.count() and total > 0:
            idx = current - 1
            if 0 <= idx < total:
                self._thumbs_list.blockSignals(True)
                self._thumbs_list.setCurrentRow(idx)
                self._thumbs_list.blockSignals(False)

        self._schedule_thumbnail_render()
        self._sync_outline_current_page(current - 1)
        self._update_search_highlights()
        self._schedule_session_save()

    def _on_view_text_info(self, view: PdfView, info: str):
        if not self._is_current_view(view):
            return

        if not info:
            self._font_name.setText("--")
            self._font_size.setText("--")
            self._font_style.setText("--")
            return

        font_name = "--"
        size_text = "--"
        style_text = ""
        for part in [p.strip() for p in info.split("|")]:
            lower = part.lower()
            if lower.startswith("font:"):
                font_name = part.split(":", 1)[1].strip()
            elif lower.startswith("size:"):
                size_text = part.split(":", 1)[1].strip()
            elif lower.startswith("style:"):
                style_text = part.split(":", 1)[1].strip()

        if not style_text:
            normalized = font_name.lower()
            styles = []
            if "bold" in normalized:
                styles.append("Bold")
            if "italic" in normalized or "oblique" in normalized:
                styles.append("Italic")
            style_text = " + ".join(styles) if styles else "Regular"

        self._font_name.setText(font_name)
        self._font_size.setText(size_text)
        self._font_style.setText(style_text)

    def _on_view_text_selected(self, view: PdfView, text: str):
        if not self._is_current_view(view):
            return
        if text:
            QApplication.clipboard().setText(text)
            self._status.showMessage("Copied text selection", 1500)
        else:
            self._status.showMessage("No text in selection", 1500)

    def _load_native_pdf_annotations(self, view: PdfView, ctx) -> None:
        """Read annotations embedded in the PDF (e.g. created by Acrobat) and store as native_annotations."""
        ctx.native_annotations = load_native_annotations(view.document)

    def _on_view_document_loaded(self, view: PdfView):
        if self._reload_in_progress:
            return
        if self._open_in_progress:
            # _open_file loads the sidecar and native annotations and refreshes
            # the panels once itself. Doing it here as well rebuilt the outline
            # and annotation list two extra times per open (O(TOC entries) each).
            return
        ctx = self._context_for_view(view)
        if ctx.file_path:
            ctx.sidecar_state = clamp_sidecar_for_page_count(ctx.sidecar_state, view.page_count)
            self._load_native_pdf_annotations(view, ctx)
            all_annotations = ctx.sidecar_state.annotations + ctx.native_annotations
            view.set_annotations(all_annotations)
        if self._is_current_view(view):
            # Also rebuilds the outline, thumbnails and annotation list.
            self._refresh_document_info()

    # --------------------------- Reload / watch ---------------------------
    def _stop_watch(self):
        for f in self._watcher.files():
            self._watcher.removePath(f)
        for d in self._watcher.directories():
            self._watcher.removePath(d)

    def _start_watch(self):
        if self._current_file and self._auto_reload_enabled:
            if os.path.exists(self._current_file):
                self._watcher.addPath(self._current_file)
                parent = os.path.dirname(self._current_file)
                if parent:
                    self._watcher.addPath(parent)

    def _update_mtime(self):
        try:
            if self._current_file and os.path.exists(self._current_file):
                self._last_file_sig = self._file_signature(self._current_file)
        except OSError:
            pass

    def _normalize_path(self, path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    def _on_change(self, _path: str):
        if not self._auto_reload_enabled:
            return
        if not self._current_file:
            return

        current_file = self._normalize_path(self._current_file)
        current_dir = self._normalize_path(os.path.dirname(self._current_file))
        changed = self._normalize_path(_path) if _path else ""
        if changed and changed != current_file and changed != current_dir:
            if not changed.startswith(current_dir + os.sep):
                return

        self._schedule_reload_if_modified()

    def _poll_check(self):
        if not self._auto_reload_enabled or not self._current_file:
            return
        self._schedule_reload_if_modified()

    def _file_signature(self, path: str | None) -> tuple[int, int, int] | None:
        if not path or not os.path.exists(path):
            return None
        try:
            stat = os.stat(path)
            return (int(stat.st_mtime_ns), int(stat.st_size), int(getattr(stat, "st_ino", 0)))
        except OSError:
            return None

    def _schedule_reload_if_modified(self):
        current_sig = self._file_signature(self._current_file)
        if current_sig is None:
            return
        if current_sig != self._last_file_sig:
            self._reload_timer.start(200)

    def _do_reload(self, force: bool = False):
        if self._reload_in_progress:
            return
        view = self.current_view()
        ctx = self.current_context()
        if not ctx.file_path or not os.path.exists(ctx.file_path):
            return

        current_sig = self._file_signature(ctx.file_path)
        if current_sig is None:
            return
        if not force and current_sig == self._last_file_sig:
            return

        try:
            if os.path.getsize(ctx.file_path) == 0:
                if not force:
                    self._reload_timer.start(250)
                return
        except OSError:
            return

        self._search_timer.stop()
        self._cancel_search_operation()
        self._reload_in_progress = True
        reloaded = False
        try:
            self.setUpdatesEnabled(False)
            reloaded = view.reload_document()
        finally:
            self._reload_in_progress = False
            self.setUpdatesEnabled(True)
            self.update()
            view.viewport().update()

        if reloaded:
            ctx.sidecar_state = clamp_sidecar_for_page_count(ctx.sidecar_state, view.page_count)
            self._load_native_pdf_annotations(view, ctx)
            view.set_annotations(ctx.sidecar_state.annotations + ctx.native_annotations)
            self._last_file_sig = current_sig
            self._status.showMessage("Reloaded", 1000)
            if self._is_current_view(view):
                self._refresh_document_info()
                if ctx.search_query:
                    self._execute_search_current(allow_short_query=bool(ctx.search_results))
                else:
                    self._update_search_count_label(ctx)
            if self._auto_reload_enabled:
                if ctx.file_path not in self._watcher.files():
                    self._watcher.addPath(ctx.file_path)
                parent = os.path.dirname(ctx.file_path)
                if parent and parent not in self._watcher.directories():
                    self._watcher.addPath(parent)
        elif not force:
            # Some editors replace files atomically; retry shortly if we failed during write.
            self._reload_timer.start(250)

    def _force_reload(self):
        self._do_reload(force=True)

    # --------------------------- Actions ---------------------------
    def _copy(self):
        sel = self.current_view().selection_rect
        if not sel:
            self._status.showMessage("No selection", 2000)
            return
        QApplication.clipboard().setText(format_size(sel.width(), sel.height()))
        self._status.showMessage("Copied", 1500)

    def _export(self):
        view = self.current_view()
        sel = view.selection_rect
        if not sel:
            QMessageBox.information(self, "Export", "No selection. Use Measure tool to select an area.")
            return

        dlg = ExportDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        path, _ = QFileDialog.getSaveFileName(self, "Save PNG", "selection.png", "PNG (*.png)")
        if not path:
            return

        try:
            page_idx = view.selection_page
            if page_idx < 0 or not view.document:
                return
            page = view.document.load_page(page_idx)
            clip = fitz.Rect(sel.x(), sel.y(), sel.right(), sel.bottom())
            scale = dlg.selected_dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
            pix.save(path)
            self._status.showMessage(f"Saved {os.path.basename(path)}", 2000)
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _on_tool_action(self, tool: ToolMode):
        """A tool picked from the toolbar, menu or keyboard (not restored from settings)."""
        self._set_tool(tool)
        if tool == ToolMode.MEASURE:
            # Measuring is what the Inspector is for: open it on its first use.
            self._set_inspector_visible(True)
            self._inspector.measure_section.set_expanded(True)

    def _sync_tool_actions(self, tool: ToolMode):
        self._select_action.setChecked(tool == ToolMode.SELECT)
        self._hand_action.setChecked(tool == ToolMode.HAND)
        self._measure_action.setChecked(tool == ToolMode.MEASURE)
        self._annotate_action.setChecked(tool == ToolMode.ANNOTATE)

    def _set_tool(self, tool: ToolMode):
        view = self.current_view()
        view.tool = tool
        self._sync_tool_actions(tool)

        # The annotation toolbar is contextual: only while annotating.
        self._ann_toolbar.setVisible(tool == ToolMode.ANNOTATE)
        if tool == ToolMode.ANNOTATE and not self._sidebar_dock.isHidden():
            self._sidebar.set_current("annotations")

        self._settings.setValue("view/tool", tool.name)
        self._update_status()

    def _on_zoom_combo_changed(self, text: str):
        if self._zoom_combo_updating:
            return
        view = self.current_view()
        if text == ZOOM_FIT_WIDTH:
            view.fit_width()
            self._sync_zoom_combo()
            return
        if text == ZOOM_FIT_PAGE:
            view.fit_page()
            self._sync_zoom_combo()
            return
        raw = text.strip().replace("%", "")
        if not raw:
            return
        try:
            value = float(raw)
        except ValueError:
            return
        if value <= 0:
            return
        target = value / 100.0
        view = self.current_view()
        # Suppress double-fire when both returnPressed and editingFinished hit
        # on the same Enter keypress.
        if abs(view.zoom - target) < 1e-4:
            return
        view.set_zoom(target, immediate=True, zoom_mode=PdfView.ZOOM_MODE_CUSTOM)

    def _sync_zoom_combo(self):
        view = self.current_view()
        self._zoom_combo_updating = True
        self._zoom_combo.setCurrentText(f"{view.zoom * 100:.0f}%" if view.document else "100%")
        self._zoom_combo_updating = False

    def _toggle_auto_reload(self, enabled: bool):
        self._auto_reload_enabled = bool(enabled)
        self._settings.setValue("view/auto_reload", self._auto_reload_enabled)
        if self._auto_reload_enabled:
            self._start_watch()
        else:
            self._stop_watch()

    # --------------------------- Status/update ---------------------------
    def _set_unit(self, unit: str):
        unit = normalize_unit(unit)
        self._unit = unit
        self._settings.setValue("view/unit", unit)
        combo = self._inspector.units_combo
        idx = combo.findData(unit)
        if idx >= 0 and idx != combo.currentIndex():
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        for act in getattr(self, "_unit_actions", {}).values():
            act.setChecked(act.data() == unit)
        self._update_measurements_panel(self.current_view().selection_rect)

    def _update_measurements_panel(self, sel: QRectF | None):
        if not sel:
            for label in (self._measure_w, self._measure_h, self._measure_x, self._measure_y):
                label.setText("--")
            self._status.set_measurement("")
            self._inspector.measure_hint.setVisible(True)
            return
        unit = self._unit
        self._measure_w.setText(format_length(sel.width(), unit))
        self._measure_h.setText(format_length(sel.height(), unit))
        self._measure_x.setText(format_length(sel.x(), unit))
        self._measure_y.setText(format_length(sel.y(), unit))
        self._status.set_measurement(f"{format_length(sel.width(), unit)} x {format_length(sel.height(), unit)}")
        self._inspector.measure_hint.setVisible(False)

    def _update_action_states(self, has_doc: bool):
        for action in self._doc_actions:
            action.setEnabled(has_doc)
        self._zoom_combo.setEnabled(has_doc)
        self._search_field.setEnabled(has_doc)
        self._update_capability_actions()

    # --------------------------- Viewer capabilities ---------------------------
    @staticmethod
    def _view_supports(view, *names: str) -> bool:
        return all(callable(getattr(view, name, None)) for name in names)

    def _view_password(self, view: PdfView) -> str | None:
        getter = getattr(view, "document_password", None)
        return getter() if callable(getter) else None

    def _update_capability_actions(self):
        """Enable print/presentation and the Phase B actions for what the current view supports.

        Page layout, reading mode and back/forward call PdfView methods that land in Phase B
        (docs/dev/viewer-api.md). Until a view has them, their actions stay disabled.
        """
        view = self.current_view()
        has_doc = view.document is not None
        self._print_action.setEnabled(has_doc)
        self._presentation_action.setEnabled(has_doc)

        can_page = has_doc and self._view_supports(view, "set_page_mode", "page_mode")
        page_mode = view.page_mode() if can_page else None
        for mode, act in self._page_mode_actions.items():
            act.setEnabled(can_page)
            act.setChecked(mode == page_mode)

        can_color = has_doc and self._view_supports(view, "set_color_mode", "color_mode")
        color_mode = view.color_mode() if can_color else None
        for mode, act in self._color_mode_actions.items():
            act.setEnabled(can_color)
            act.setChecked(mode == color_mode)

        can_history = has_doc and self._view_supports(view, "go_back", "go_forward", "can_go_back", "can_go_forward")
        self._back_action.setEnabled(bool(can_history and view.can_go_back()))
        self._forward_action.setEnabled(bool(can_history and view.can_go_forward()))

    def _on_view_capability_changed(self, view: PdfView):
        if self._is_current_view(view):
            self._update_capability_actions()
        self._schedule_session_save()

    def _set_page_mode(self, mode: str):
        view = self.current_view()
        if view.document is not None and self._view_supports(view, "set_page_mode"):
            try:
                view.set_page_mode(mode)
            except ValueError as exc:
                self._status.showMessage(str(exc), 3000)
            self._schedule_session_save()
        self._update_capability_actions()

    def _set_color_mode(self, mode: str):
        view = self.current_view()
        if view.document is not None and self._view_supports(view, "set_color_mode"):
            try:
                view.set_color_mode(mode)
            except ValueError as exc:
                self._status.showMessage(str(exc), 3000)
            self._schedule_session_save()
        self._update_capability_actions()

    def _go_back(self):
        view = self.current_view()
        if view.document is not None and self._view_supports(view, "go_back"):
            view.go_back()
        self._update_capability_actions()

    def _go_forward(self):
        view = self.current_view()
        if view.document is not None and self._view_supports(view, "go_forward"):
            view.go_forward()
        self._update_capability_actions()

    def _print_document(self):
        view = self.current_view()
        path = view.doc_path
        if view.document is None or not path:
            self._status.showMessage("Open a PDF first", 1500)
            return
        try:
            printing.print_document(self, path, view.current_page, self._view_password(view))
        except Exception as exc:
            # The file is re-read from disk and may be mid-rebuild (LaTeX) or re-encrypted.
            self._status.showMessage(f"Could not print {os.path.basename(path)}: {exc}", 6000)

    def _start_presentation(self):
        existing = self._presentation
        if existing is not None and shiboken6.isValid(existing) and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            return
        view = self.current_view()
        path = view.doc_path
        if view.document is None or not path:
            self._status.showMessage("Open a PDF first", 1500)
            return
        try:
            win = presentation.PresentationWindow(path, view.current_page, self._view_password(view))
        except Exception as exc:
            self._status.showMessage(f"Could not start the presentation: {exc}", 6000)
            return
        win.closed.connect(lambda page, v=view: self._on_presentation_closed(v, page))
        self._presentation = win
        win.present()

    def _on_presentation_closed(self, view: PdfView, page: int):
        win = self._presentation
        self._presentation = None
        if shiboken6.isValid(view) and view.document is not None and 0 <= page < view.page_count:
            view.go_to_page(page)
        if win is not None and shiboken6.isValid(win):
            win.deleteLater()

    # Encrypted documents (Phase B: PdfView.open_document(path, password), password_required).
    def _view_can_unlock(self, view: PdfView) -> bool:
        return getattr(view, "password_required", None) is not None

    @staticmethod
    def _needs_password(path: str) -> bool:
        try:
            return password.needs_password(path)
        except Exception:
            return False

    def _unlock_and_open(self, view: PdfView, path: str) -> bool:
        """Ask for the password (up to MAX_ATTEMPTS times) and open ``path`` in ``view``."""
        dlg = password.PasswordDialog(self, os.path.basename(path))
        for _attempt in range(password.MAX_ATTEMPTS):
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return False
            if view.open_document(path, dlg.password()):
                return True
            dlg.set_error("Incorrect password. Try again.")
        self._status.showMessage(f"Could not unlock {os.path.basename(path)}", 4000)
        return False

    def _on_view_password_required(self, view: PdfView, path: str):
        # During _open_file the prompt runs inline (and an unopened new tab is closed).
        if self._open_in_progress or self._reload_in_progress:
            if self._reload_in_progress:
                QTimer.singleShot(0, lambda v=view, p=path: self._on_view_password_required(v, p))
            return
        if not shiboken6.isValid(view):
            return
        if self._unlock_and_open(view, path) and self._is_current_view(view):
            self._refresh_document_info()
            self._update_status()

    def _show_about(self):
        try:
            from importlib.metadata import version

            ver = version("neoview")
        except Exception:
            ver = "dev"
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} {html.escape(ver)}</h3>"
            "<p>A PDF viewer with measurement tools, annotations and auto-reload for LaTeX "
            "workflows.</p><p>Icons: Lucide (ISC). Font: Inter (SIL OFL 1.1).</p>",
        )

    def _update_status(self):
        view = self.current_view()
        ctx = self.current_context()
        has_doc = view.document is not None

        if has_doc:
            name = os.path.basename(ctx.file_path) if ctx.file_path else "Untitled"
            zoom_text = f"{view.zoom * 100:.0f}%"
            self._status.set_document(name)
            self._status.set_zoom(view.zoom * 100)
            self._status.set_page(view.current_page + 1, view.page_count)
            self._doc_name.setText(name)
            self._doc_zoom.setText(zoom_text)
            self._doc_page.setText(f"{view.current_page + 1} / {view.page_count}")
            self._page_field.set_pages(view.current_page + 1, view.page_count)
            self._update_measurements_panel(view.selection_rect)
        else:
            self._status.set_document(None)
            self._status.set_zoom(None)
            self._status.set_page(0, 0)
            self._doc_name.setText("No file")
            self._doc_page.setText("0 / 0")
            self._doc_zoom.setText("--")
            self._page_field.set_pages(0, 0)
            self._update_measurements_panel(None)

        self._sync_zoom_combo()
        self._sync_tool_actions(view.tool)
        self._update_action_states(has_doc)

    # ----------------------- Performance mode helpers -----------------------
    def _on_performance_mode_toggled(self, checked: bool) -> None:
        view = self.current_view()
        if isinstance(view, PdfView):
            view.set_performance_mode(checked)
        self._update_perf_status()

    def _update_perf_status(self) -> None:
        view = self.current_view()
        if isinstance(view, PdfView) and view.is_performance_mode():
            self._perf_label.setText("Performance mode")
        else:
            self._perf_label.setText("")

    # --------------------------- Utility ---------------------------
    def _icon(self, name: str) -> QIcon:
        """A bundled icon tinted for the current theme (see neoview.ui.icons)."""
        return icons.icon(name)

    def _metadata_text(self, value, empty: str = "--") -> str:
        if value is None:
            return empty
        text = str(value).strip()
        return text if text else empty

    def _format_pdf_date(self, value) -> str:
        raw = self._metadata_text(value, empty="")
        if not raw:
            return "--"
        if raw.startswith("D:"):
            raw = raw[2:]
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) < 4:
            return self._metadata_text(value)
        year = digits[0:4]
        month = digits[4:6] if len(digits) >= 6 else ""
        day = digits[6:8] if len(digits) >= 8 else ""
        hour = digits[8:10] if len(digits) >= 10 else ""
        minute = digits[10:12] if len(digits) >= 12 else ""

        parts = [year]
        if month:
            parts.append(month)
        if day:
            parts.append(day)

        text = "-".join(parts)
        if hour and minute:
            text += f" {hour}:{minute}"
        return text

    def _format_file_size(self, path: str | None) -> str:
        if not path:
            return "--"
        try:
            size = float(os.path.getsize(path))
        except OSError:
            return "--"
        units = ["B", "KB", "MB", "GB"]
        unit_idx = 0
        while size >= 1024.0 and unit_idx < len(units) - 1:
            size /= 1024.0
            unit_idx += 1
        if unit_idx == 0:
            return f"{int(size)} {units[unit_idx]}"
        return f"{size:.1f} {units[unit_idx]}"

    def closeEvent(self, e):
        if self._presentation is not None and shiboken6.isValid(self._presentation):
            self._presentation.close()
        self._search_timer.stop()
        self._cancel_search_operation()
        self._reload_timer.stop()
        self._thumb_timer.stop()
        self._session_save_timer.stop()

        for idx in range(self._tabs.count()):
            widget = self._tabs.widget(idx)
            if not isinstance(widget, PdfView):
                continue
            self._save_document_session_for_view(widget)
            self._save_sidecar_for_view(widget)

        self._save_json_setting("documents/session", self._document_sessions)
        self._save_persistent_ui()

        for idx in range(self._tabs.count()):
            widget = self._tabs.widget(idx)
            if isinstance(widget, PdfView):
                widget.close_document()

        super().closeEvent(e)
