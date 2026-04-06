"""Main application window."""

from __future__ import annotations

from collections import deque
import html
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

import fitz
from PySide6.QtCore import QEvent, QFileSystemWatcher, QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QWindowStateChangeEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QFileDialog,
    QFrame,
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
    QStatusBar,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from neoview.models.view_state import AnnotationRecord, BookmarkRecord, SearchMatch, TabContext
from neoview.persistence.sidecar_store import clamp_sidecar_for_page_count, load_sidecar, save_sidecar
from neoview.resources import load_app_icon
from neoview.ui.annotation_toolbar import AnnotationToolbar
from neoview.ui.dialogs import ExportDialog
from neoview.ui.pdf_view import PdfView, ToolMode
from neoview.utils.units import format_size


APP_NAME = "NeoView"


class CollapsibleSection(QWidget):
    """Simple expandable/collapsible content section."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = QToolButton(self)
        self._header.setText(title)
        self._header.setObjectName("InspectorSectionHeader")
        self._header.setCheckable(True)
        self._header.setChecked(True)
        self._header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._header.setArrowType(Qt.ArrowType.DownArrow)
        self._header.clicked.connect(self._on_toggled)

        self._content = QWidget()
        self._content.setObjectName("InspectorSectionContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 2, 0, 6)
        self._content_layout.setSpacing(6)

        root.addWidget(self._header)
        root.addWidget(self._content)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def _on_toggled(self, expanded: bool):
        self._header.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._content.setVisible(expanded)


class MainWindow(QMainWindow):
    ROLE_KIND = int(Qt.ItemDataRole.UserRole)
    ROLE_PAGE = int(Qt.ItemDataRole.UserRole) + 1
    ROLE_BOOKMARK_ID = int(Qt.ItemDataRole.UserRole) + 2
    ROLE_ANNOTATION_ID = int(Qt.ItemDataRole.UserRole) + 3
    MAX_SEARCH_RESULTS = 2000
    MAX_LIVE_SEARCH_RESULTS = 250
    MIN_LIVE_SEARCH_CHARS = 2
    SEARCH_SYNC_PAGE_THRESHOLD = 8
    SEARCH_BATCH_PAGES = 6
    SEARCH_BATCH_TIME_BUDGET_MS = 18.0

    # Inspector tab indices — must match the order tabs are added in _setup_docks
    _INSPECTOR_TAB_MEASURE = 0
    _INSPECTOR_TAB_FONT = 1
    _INSPECTOR_TAB_ANNOTATIONS = 2
    _INSPECTOR_TAB_DOCUMENT = 3

    def __init__(self, pdf_path: Optional[str] = None):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1280, 900)

        self._current_file: Optional[str] = None
        self._last_file_sig: Optional[Tuple[int, int, int]] = None
        self._settings = QSettings("NeoView", "NeoView")
        self._recent_files: List[str] = self._settings.value("recent_files", [], type=list)
        self._recent_menu: Optional[object] = None
        self._document_sessions: Dict[str, Dict[str, object]] = self._load_json_setting("documents/session", {})
        self._startup_last_file = ""
        if not pdf_path:
            self._startup_last_file = self._settings.value("session/last_active_file", "", type=str)

        self._zoom_combo_updating = False
        self._search_input_updating = False
        self._auto_reload_enabled = self._settings.value("view/auto_reload", True, type=bool)

        self._view: Optional[PdfView] = None
        self._tab_contexts: Dict[PdfView, TabContext] = {}
        self._sidecar_timers: Dict[PdfView, QTimer] = {}

        # Active-tab thumbnail state.
        self._thumb_source_key: str = ""
        self._thumb_icon_cache: Dict[tuple, QIcon] = {}
        self._thumb_queue: deque[int] = deque()
        self._thumb_queued: set[int] = set()

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
        self._search_operation: Optional[Dict[str, object]] = None
        self._reload_in_progress = False
        self._last_maximize_at: float = 0.0

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
        self._tabs = QTabWidget(self)
        self._tabs.setObjectName("DocumentTabs")
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabCloseRequested.connect(self._close_tab_index)
        self.setCentralWidget(self._tabs)

        self._create_tab()

        self._setup_menus()
        self._setup_toolbar()
        self._setup_annotation_toolbar()
        self._setup_statusbar()
        self._setup_docks()
        self._update_status()

    def _create_tab(self) -> PdfView:
        view = PdfView(self)

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

    def _set_current_file(self, file_path: Optional[str]):
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
        self._refresh_document_info()
        self._populate_outline()
        self._populate_thumbnails()
        self._populate_annotation_list()
        self._update_status()

        if hasattr(self, "_perf_action"):
            if isinstance(view, PdfView):
                view.set_performance_mode(self._perf_action.isChecked())
            self._update_perf_status()

    def _close_tab_index(self, index: int):
        widget = self._tabs.widget(index)
        if not isinstance(widget, PdfView):
            return

        if self._tabs.count() == 1:
            self._save_sidecar_for_view(widget)
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

    def _find_open_view(self, path: str) -> Optional[PdfView]:
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

    def _setup_menus(self):
        file_m = self.menuBar().addMenu("&File")
        self._open_action = self._action("&Open...", self._open_dialog, QKeySequence.StandardKey.Open)
        file_m.addAction(self._open_action)

        self._recent_menu = file_m.addMenu("Open &Recent")
        self._rebuild_recent_menu()

        self._close_tab_action = self._action("Close &Tab", self._close_current_tab, "Ctrl+W")
        file_m.addAction(self._close_tab_action)

        self._reload_action = self._action("&Reload", self._force_reload, "F5")
        file_m.addAction(self._reload_action)
        file_m.addSeparator()

        self._export_action = self._action("&Export Selection...", self._export, QKeySequence.StandardKey.Save)
        file_m.addAction(self._export_action)
        file_m.addSeparator()
        file_m.addAction(self._action("E&xit", self.close, QKeySequence.StandardKey.Quit))

        edit_m = self.menuBar().addMenu("&Edit")
        self._copy_action = self._action("&Copy Measurements", self._copy, QKeySequence.StandardKey.Copy)
        edit_m.addAction(self._copy_action)
        self._find_action = self._action("&Find...", self._show_find, "Ctrl+F")
        edit_m.addAction(self._find_action)
        edit_m.addAction(self._action("C&lear Selection", lambda: self.current_view().clear_all_selection(), "Escape"))

        view_m = self.menuBar().addMenu("&View")
        self._zoom_in_action = self._action(
            "Zoom &In", lambda: self.current_view().zoom_by(1.25), QKeySequence.StandardKey.ZoomIn
        )
        self._zoom_out_action = self._action(
            "Zoom &Out", lambda: self.current_view().zoom_by(0.8), QKeySequence.StandardKey.ZoomOut
        )
        self._fit_width_action = self._action("Fit &Width", lambda: self.current_view().fit_width(), "W")
        self._fit_page_action = self._action("Fit &Page", lambda: self.current_view().fit_page(), "F")
        self._actual_size_action = self._action("&Actual Size", lambda: self.current_view().actual_size(), "Ctrl+1")

        view_m.addAction(self._zoom_in_action)
        view_m.addAction(self._zoom_out_action)
        view_m.addSeparator()
        view_m.addAction(self._fit_width_action)
        view_m.addAction(self._fit_page_action)
        view_m.addAction(self._actual_size_action)
        view_m.addSeparator()
        view_m.addAction(self._action("Rotate &Left", lambda: self.current_view().rotate_by(-90), "Ctrl+L"))
        view_m.addAction(self._action("Rotate &Right", lambda: self.current_view().rotate_by(90), "Ctrl+R"))
        view_m.addAction(self._action("Reset &Rotation", lambda: self.current_view().set_rotation(0), "Ctrl+0"))
        view_m.addSeparator()
        self._fullscreen_action = self._action("&Toggle Full Screen", self._toggle_fullscreen, "F11")
        view_m.addAction(self._fullscreen_action)
        view_m.addAction(self._action("Reset Window &Layout", self._reset_window_layout))
        view_m.addSeparator()
        self._perf_action = QAction("Performance Mode", self)
        self._perf_action.setCheckable(True)
        self._perf_action.setStatusTip("Pause rendering during zoom/scroll — reduces CPU on large PDFs")
        self._perf_action.triggered.connect(self._on_performance_mode_toggled)
        view_m.addAction(self._perf_action)

        go_m = self.menuBar().addMenu("&Go")
        go_m.addAction(self._action("&Previous Page", lambda: self.current_view().prev_page(), "PgUp"))
        go_m.addAction(self._action("&Next Page", lambda: self.current_view().next_page(), "PgDown"))
        go_m.addAction(self._action("&First Page", lambda: self.current_view().first_page(), "Home"))
        go_m.addAction(self._action("&Last Page", lambda: self.current_view().last_page(), "End"))
        go_m.addSeparator()
        self._next_tab_action = self._action("Next Ta&b", self._switch_to_next_tab)
        self._next_tab_action.setShortcuts(
            [
                QKeySequence("Ctrl+Tab"),
                QKeySequence("Ctrl+PgDown"),
            ]
        )
        self._prev_tab_action = self._action("Previous T&ab", self._switch_to_previous_tab)
        self._prev_tab_action.setShortcuts(
            [
                QKeySequence("Ctrl+Shift+Tab"),
                QKeySequence("Ctrl+PgUp"),
            ]
        )
        self._next_tab_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self._prev_tab_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.addAction(self._next_tab_action)
        self.addAction(self._prev_tab_action)
        go_m.addAction(self._next_tab_action)
        go_m.addAction(self._prev_tab_action)

        self._add_bookmark_action = self._action("Add &Bookmark", self._add_bookmark, "Ctrl+D")
        go_m.addSeparator()
        go_m.addAction(self._add_bookmark_action)

        tools_m = self.menuBar().addMenu("&Tools")
        self._tool_group = QActionGroup(self)
        self._tool_group.setExclusive(True)

        self._select_action = self._action("&Select", lambda: self._set_tool(ToolMode.SELECT), "1")
        self._select_action.setCheckable(True)
        self._tool_group.addAction(self._select_action)
        tools_m.addAction(self._select_action)

        self._hand_action = self._action("&Hand", lambda: self._set_tool(ToolMode.HAND), "2")
        self._hand_action.setCheckable(True)
        self._hand_action.setChecked(True)
        self._tool_group.addAction(self._hand_action)
        tools_m.addAction(self._hand_action)

        self._measure_action = self._action("&Measure", lambda: self._set_tool(ToolMode.MEASURE), "3")
        self._measure_action.setCheckable(True)
        self._tool_group.addAction(self._measure_action)
        tools_m.addAction(self._measure_action)

        self._annotate_action = self._action("&Annotate", lambda: self._set_tool(ToolMode.ANNOTATE), "4")
        self._annotate_action.setCheckable(True)
        self._tool_group.addAction(self._annotate_action)
        tools_m.addAction(self._annotate_action)

        tools_m.addSeparator()
        self._annot_highlight_action = self._action("Add &Highlight (selection)", self._add_highlight, "Ctrl+Shift+H")
        self._annot_underline_action = self._action("Add &Underline (selection)", self._add_underline, "Ctrl+Shift+U")
        self._annot_note_action = self._action("Add &Note (selection)", self._add_note, "Ctrl+Shift+N")
        tools_m.addAction(self._annot_highlight_action)
        tools_m.addAction(self._annot_underline_action)
        tools_m.addAction(self._annot_note_action)

        tools_m.addSeparator()
        self._export_annot_action = self._action("Export PDF with &Annotations", self._export_pdf_with_annotations)
        tools_m.addAction(self._export_annot_action)

        tools_m.addSeparator()
        tools_m.addAction(self._action("&Search Panel", self._toggle_search_dock, "Ctrl+Shift+F"))
        tools_m.addAction(self._action("&Navigation Panel", self._toggle_outline_dock, "Ctrl+Shift+O"))
        tools_m.addAction(self._action("&Thumbnails Panel", self._toggle_thumbs_dock, "Ctrl+Shift+T"))
        tools_m.addAction(self._action("&Page Info Panel", self._toggle_info_dock, "Ctrl+Shift+I"))

        self._open_action.setIcon(self._icon("document-open", QStyle.StandardPixmap.SP_DialogOpenButton))
        self._zoom_out_action.setIcon(self._icon("zoom-out", QStyle.StandardPixmap.SP_ArrowDown))
        self._zoom_in_action.setIcon(self._icon("zoom-in", QStyle.StandardPixmap.SP_ArrowUp))
        self._fit_width_action.setIcon(self._icon("zoom-fit-width", QStyle.StandardPixmap.SP_TitleBarMaxButton))
        self._fit_page_action.setIcon(self._icon("zoom-fit-best", QStyle.StandardPixmap.SP_DesktopIcon))
        self._actual_size_action.setIcon(self._icon("zoom-original", QStyle.StandardPixmap.SP_ComputerIcon))
        self._select_action.setIcon(self._icon("cursor-arrow", QStyle.StandardPixmap.SP_ArrowRight))
        self._hand_action.setIcon(self._hand_icon())
        self._measure_action.setIcon(self._icon("draw-rectangle", QStyle.StandardPixmap.SP_DialogApplyButton))
        self._copy_action.setIcon(self._icon("edit-copy", QStyle.StandardPixmap.SP_FileIcon))
        self._export_action.setIcon(self._icon("document-save", QStyle.StandardPixmap.SP_DialogSaveButton))
        self._annot_highlight_action.setIcon(self._icon("format-text-highlight", QStyle.StandardPixmap.SP_DialogApplyButton))
        self._annot_underline_action.setIcon(self._icon("format-text-underline", QStyle.StandardPixmap.SP_LineEditClearButton))
        self._annot_note_action.setIcon(self._icon("insert-text", QStyle.StandardPixmap.SP_MessageBoxInformation))

        self._open_action.setToolTip("Open PDF (Ctrl+O)")
        self._zoom_out_action.setToolTip("Zoom out")
        self._zoom_in_action.setToolTip("Zoom in")
        self._fit_width_action.setToolTip("Fit width (W)")
        self._actual_size_action.setToolTip("Actual size (Ctrl+1)")
        self._select_action.setToolTip("Select tool (1)")
        self._hand_action.setToolTip("Hand tool (2)")
        self._measure_action.setToolTip("Measure tool (3)")
        self._copy_action.setToolTip("Copy measurements (Ctrl+C)")
        self._export_action.setToolTip("Export selection")

    def _setup_toolbar(self):
        tb = QToolBar("Main")
        tb.setObjectName("MainToolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        tb.addAction(self._open_action)

        self._recent_btn = QToolButton(self)
        self._recent_btn.setIcon(self._icon("document-open-recent", QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self._recent_btn.setToolTip("Open recent file")
        self._recent_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._recent_btn.setMenu(self._recent_menu)
        tb.addWidget(self._recent_btn)
        tb.addSeparator()

        # -- Page navigation --
        self._page_nav_combo = QComboBox(self)
        self._page_nav_combo.setEditable(True)
        self._page_nav_combo.setMinimumWidth(70)
        self._page_nav_combo.setMaximumWidth(90)
        self._page_nav_combo.setToolTip("Go to page")
        self._page_nav_combo.currentTextChanged.connect(self._on_page_nav_changed)
        tb.addWidget(self._page_nav_combo)

        self._page_total_lbl = QLabel(" / 0 ")
        self._page_total_lbl.setStyleSheet("color: #888; font-size: 11px; padding: 0 4px;")
        tb.addWidget(self._page_total_lbl)
        tb.addSeparator()

        # -- Zoom controls --
        tb.addAction(self._zoom_out_action)

        self._zoom_combo = QComboBox(self)
        self._zoom_combo.setEditable(True)
        self._zoom_combo.setMinimumWidth(78)
        self._zoom_combo.setMaximumWidth(90)
        self._zoom_combo.addItems(["50%", "75%", "100%", "125%", "150%", "200%", "300%"])
        self._zoom_combo.setCurrentText("100%")
        self._zoom_combo.currentTextChanged.connect(self._on_zoom_combo_changed)
        tb.addWidget(self._zoom_combo)

        tb.addAction(self._zoom_in_action)
        tb.addAction(self._fit_width_action)
        tb.addAction(self._fit_page_action)
        tb.addAction(self._actual_size_action)
        tb.addSeparator()

        # -- Tool group --
        self._toolbar_select_action = QAction(self._icon("cursor-arrow", QStyle.StandardPixmap.SP_ArrowRight), "Select", self)
        self._toolbar_select_action.setToolTip("Select tool (1)")
        self._toolbar_select_action.setCheckable(True)
        self._toolbar_select_action.triggered.connect(lambda: self._set_tool(ToolMode.SELECT))

        self._toolbar_hand_action = QAction(
            self._hand_icon(),
            "Hand",
            self,
        )
        self._toolbar_hand_action.setToolTip("Hand tool (2)")
        self._toolbar_hand_action.setCheckable(True)
        self._toolbar_hand_action.triggered.connect(lambda: self._set_tool(ToolMode.HAND))

        self._toolbar_measure_action = QAction(
            self._icon("draw-rectangle", QStyle.StandardPixmap.SP_DialogApplyButton),
            "Measure",
            self,
        )
        self._toolbar_measure_action.setToolTip("Measure tool (3)")
        self._toolbar_measure_action.setCheckable(True)
        self._toolbar_measure_action.triggered.connect(lambda: self._set_tool(ToolMode.MEASURE))

        self._toolbar_tool_group = QActionGroup(self)
        self._toolbar_tool_group.setExclusive(True)
        self._toolbar_tool_group.addAction(self._toolbar_select_action)
        self._toolbar_tool_group.addAction(self._toolbar_hand_action)
        self._toolbar_tool_group.addAction(self._toolbar_measure_action)

        tb.addAction(self._toolbar_select_action)
        tb.addAction(self._toolbar_hand_action)
        tb.addAction(self._toolbar_measure_action)

        self._toolbar_annotate_action = QAction(
            self._icon("draw-brush", QStyle.StandardPixmap.SP_FileDialogDetailedView),
            "Annotate",
            self,
        )
        self._toolbar_annotate_action.setToolTip("Annotate tool (4)")
        self._toolbar_annotate_action.setCheckable(True)
        self._toolbar_annotate_action.triggered.connect(lambda: self._set_tool(ToolMode.ANNOTATE))
        self._toolbar_tool_group.addAction(self._toolbar_annotate_action)
        tb.addAction(self._toolbar_annotate_action)
        tb.addSeparator()

        # -- Actions --
        self._toolbar_export_action = QAction(self._icon("document-save", QStyle.StandardPixmap.SP_DialogSaveButton), "Export", self)
        self._toolbar_export_action.setToolTip("Export selection")
        self._toolbar_export_action.triggered.connect(self._export)
        tb.addAction(self._toolbar_export_action)

        self._toolbar_copy_action = QAction(self._icon("edit-copy", QStyle.StandardPixmap.SP_FileIcon), "Copy Measurements", self)
        self._toolbar_copy_action.setToolTip("Copy measurements (Ctrl+C)")
        self._toolbar_copy_action.triggered.connect(self._copy)
        tb.addAction(self._toolbar_copy_action)
        tb.addSeparator()

        # -- Panel toggle buttons (right side) --
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self._tb_search_btn = QPushButton("Search")
        self._tb_search_btn.setObjectName("PanelToggleBtn")
        self._tb_search_btn.setCheckable(True)
        self._tb_search_btn.setToolTip("Toggle search panel (Ctrl+Shift+F)")
        self._tb_search_btn.clicked.connect(self._toggle_search_dock)
        tb.addWidget(self._tb_search_btn)

        self._tb_nav_btn = QPushButton("Outline")
        self._tb_nav_btn.setObjectName("PanelToggleBtn")
        self._tb_nav_btn.setCheckable(True)
        self._tb_nav_btn.setToolTip("Toggle outline panel (Ctrl+Shift+O)")
        self._tb_nav_btn.clicked.connect(self._toggle_outline_dock)
        tb.addWidget(self._tb_nav_btn)

        self._tb_thumb_btn = QPushButton("Thumbs")
        self._tb_thumb_btn.setObjectName("PanelToggleBtn")
        self._tb_thumb_btn.setCheckable(True)
        self._tb_thumb_btn.setToolTip("Toggle thumbnails panel (Ctrl+Shift+T)")
        self._tb_thumb_btn.clicked.connect(self._toggle_thumbs_dock)
        tb.addWidget(self._tb_thumb_btn)

        self._tb_info_btn = QPushButton("Inspector")
        self._tb_info_btn.setObjectName("PanelToggleBtn")
        self._tb_info_btn.setCheckable(True)
        self._tb_info_btn.setChecked(True)
        self._tb_info_btn.setToolTip("Toggle inspector panel (Ctrl+Shift+I)")
        self._tb_info_btn.clicked.connect(self._toggle_info_dock)
        tb.addWidget(self._tb_info_btn)

    def _setup_annotation_toolbar(self):
        """Create and add the dedicated annotation toolbar (shown below main toolbar)."""
        self._ann_toolbar = AnnotationToolbar(self)
        self.addToolBar(self._ann_toolbar)
        self._ann_toolbar.setVisible(False)  # only visible when ANNOTATE tool is active

        self._ann_toolbar.type_changed.connect(self._on_ann_toolbar_type_changed)
        self._ann_toolbar.color_changed.connect(self._on_ann_toolbar_color_changed)
        self._ann_toolbar.opacity_changed.connect(self._on_ann_toolbar_opacity_changed)
        self._ann_toolbar.border_width_changed.connect(self._on_ann_toolbar_width_changed)

    def _setup_statusbar(self):
        self._status = QStatusBar()
        self.setStatusBar(self._status)

        self._status_dot = QLabel("")
        self._status_dot.setObjectName("StatusDot")

        self._file_lbl = QLabel("No file")
        self._page_count_lbl = QLabel("Pages: 0")
        self._zoom_lbl = QLabel("--")

        self._status.addWidget(self._status_dot)
        self._status.addWidget(self._file_lbl)

        # Spacer to push remaining items right
        status_spacer = QWidget()
        status_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._status.addWidget(status_spacer)

        self._status.addWidget(self._page_count_lbl)
        self._perf_label = QLabel("")
        self._status.addPermanentWidget(self._perf_label)
        self._status.addPermanentWidget(self._zoom_lbl)

    def _setup_docks(self):
        self._search_dock = QDockWidget("Search", self)
        self._search_dock.setObjectName("SearchDock")
        self._search_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        search_widget = QWidget()
        search_layout = QVBoxLayout(search_widget)
        search_layout.setContentsMargins(8, 8, 8, 8)
        search_layout.setSpacing(6)

        search_top = QHBoxLayout()
        search_top.setContentsMargins(0, 0, 0, 0)
        search_top.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Find text...")
        self._search_input.textChanged.connect(self._on_search_text_changed)

        self._search_case_chk = QCheckBox("Case")
        self._search_case_chk.toggled.connect(self._on_search_options_changed)

        self._search_prev_btn = QPushButton("Prev")
        self._search_next_btn = QPushButton("Next")
        self._search_close_btn = QPushButton("Close")
        self._search_close_btn.setProperty("secondary", True)
        self._search_count_lbl = QLabel("")

        search_top.addWidget(self._search_input, 1)
        search_top.addWidget(self._search_case_chk)
        search_top.addWidget(self._search_prev_btn)
        search_top.addWidget(self._search_next_btn)
        search_top.addWidget(self._search_close_btn)
        search_top.addWidget(self._search_count_lbl)

        self._search_results_list = QListWidget()
        self._search_results_list.itemActivated.connect(self._jump_to_search_item)
        self._search_results_list.itemClicked.connect(self._jump_to_search_item)

        search_layout.addLayout(search_top)
        search_layout.addWidget(self._search_results_list)

        self._search_dock.setWidget(search_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._search_dock)
        self._search_dock.hide()

        self._search_prev_btn.clicked.connect(self._find_prev)
        self._search_next_btn.clicked.connect(self._find_next)
        self._search_close_btn.clicked.connect(lambda: self._search_dock.setVisible(False))
        self._search_input.returnPressed.connect(self._find_next)

        self._outline_dock = QDockWidget("Navigation", self)
        self._outline_dock.setObjectName("OutlineDock")
        self._outline_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        nav_widget = QWidget()
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(8, 8, 8, 8)
        nav_layout.setSpacing(6)

        self._outline_filter = QLineEdit()
        self._outline_filter.setPlaceholderText("Filter TOC / bookmarks")
        self._outline_filter.textChanged.connect(self._populate_outline)

        self._outline_tree = QTreeWidget()
        self._outline_tree.setHeaderHidden(True)
        self._outline_tree.itemActivated.connect(self._jump_to_outline_item)
        self._outline_tree.itemClicked.connect(self._jump_to_outline_item)
        self._outline_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._outline_tree.customContextMenuRequested.connect(self._on_outline_context_menu)

        nav_layout.addWidget(self._outline_filter)
        nav_layout.addWidget(self._outline_tree)

        self._outline_dock.setWidget(nav_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._outline_dock)
        self._outline_dock.hide()

        self._thumbs_dock = QDockWidget("Thumbnails", self)
        self._thumbs_dock.setObjectName("ThumbnailsDock")
        self._thumbs_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self._thumbs_list = QListWidget()
        self._thumbs_list.setIconSize(QSize(120, 160))
        self._thumbs_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._thumbs_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._thumbs_list.setMovement(QListWidget.Movement.Static)
        self._thumbs_dock.setWidget(self._thumbs_list)
        self._thumbs_dock.setMinimumWidth(180)
        self._thumbs_dock.setMaximumWidth(520)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._thumbs_dock)
        self.splitDockWidget(self._outline_dock, self._thumbs_dock, Qt.Orientation.Vertical)
        self._thumbs_dock.hide()
        self._thumbs_list.itemActivated.connect(self._jump_to_thumb)
        self._thumbs_list.verticalScrollBar().valueChanged.connect(self._schedule_thumbnail_render)
        self._thumbs_dock.visibilityChanged.connect(lambda _visible: self._schedule_thumbnail_render())

        self._info_dock = QDockWidget("Inspector", self)
        self._info_dock.setObjectName("InspectorDock")
        self._info_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )

        inspector_widget = QWidget()
        inspector_widget.setObjectName("InspectorPanel")
        inspector_widget.setMinimumWidth(220)
        inspector_widget.setMaximumWidth(420)

        inspector_layout = QVBoxLayout(inspector_widget)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(0)

        # --- Tab widget for context-sensitive panels ---
        self._inspector_tabs = QTabWidget()
        self._inspector_tabs.setObjectName("InspectorTabs")
        self._inspector_tabs.setDocumentMode(False)
        inspector_layout.addWidget(self._inspector_tabs)

        # ── Tab 0: Measure ──────────────────────────────────────
        measure_tab = QWidget()
        m_root = QVBoxLayout(measure_tab)
        m_root.setContentsMargins(10, 10, 10, 10)
        m_root.setSpacing(8)

        meas_header = QLabel("Dimensions")
        meas_header.setObjectName("InfoLabel")
        meas_header.setStyleSheet("font-weight:600; font-size:11px; margin-bottom:4px;")
        m_root.addWidget(meas_header)

        self._measure_w = self._kv_value("W")
        self._measure_h = self._kv_value("H")
        self._measure_x = self._kv_value("X")
        self._measure_y = self._kv_value("Y")
        m_root.addWidget(self._measure_w)
        m_root.addWidget(self._measure_h)
        m_root.addWidget(self._measure_x)
        m_root.addWidget(self._measure_y)

        m_root.addWidget(self._divider())

        tool_label = QLabel("Active Tool")
        tool_label.setObjectName("InfoLabel")
        m_root.addWidget(tool_label)

        tool_row = QHBoxLayout()
        tool_row.setContentsMargins(0, 4, 0, 0)
        tool_row.setSpacing(4)
        self._panel_tool_group = QButtonGroup(self)
        self._panel_tool_group.setExclusive(True)
        self._panel_select_btn = QPushButton("Select")
        self._panel_hand_btn = QPushButton("Hand")
        self._panel_measure_btn = QPushButton("Measure")
        self._panel_annotate_btn = QPushButton("Annotate")
        for btn, mode in (
            (self._panel_select_btn, ToolMode.SELECT),
            (self._panel_hand_btn, ToolMode.HAND),
            (self._panel_measure_btn, ToolMode.MEASURE),
            (self._panel_annotate_btn, ToolMode.ANNOTATE),
        ):
            btn.setCheckable(True)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setMinimumWidth(0)
            btn.clicked.connect(lambda _checked=False, m=mode: self._set_tool(m))
            self._panel_tool_group.addButton(btn)
            tool_row.addWidget(btn)
        self._panel_select_btn.setToolTip("Select tool (1)")
        self._panel_hand_btn.setToolTip("Hand tool (2)")
        self._panel_measure_btn.setToolTip("Measure tool (3)")
        self._panel_annotate_btn.setToolTip("Annotate tool (4)")
        m_root.addLayout(tool_row)
        m_root.addStretch()

        self._inspector_tabs.addTab(measure_tab, "Measure")

        # ── Tab 1: Font ─────────────────────────────────────────
        font_tab = QWidget()
        f_root = QVBoxLayout(font_tab)
        f_root.setContentsMargins(10, 10, 10, 10)
        f_root.setSpacing(8)

        font_header = QLabel("Text / Font Info")
        font_header.setObjectName("InfoLabel")
        font_header.setStyleSheet("font-weight:600; font-size:11px; margin-bottom:4px;")
        f_root.addWidget(font_header)

        font_hint = QLabel("Hover over text in the PDF\nto inspect its font properties.")
        font_hint.setObjectName("InfoLabel")
        font_hint.setWordWrap(True)
        font_hint.setStyleSheet("font-size:11px; margin-bottom:6px;")
        f_root.addWidget(font_hint)

        self._font_name = self._info_row(f_root, "Name", "--")
        self._font_size = self._info_row(f_root, "Size", "--")
        self._font_style = self._info_row(f_root, "Style", "--")
        f_root.addStretch()

        self._inspector_tabs.addTab(font_tab, "Font")

        # ── Tab 2: Annotations ──────────────────────────────────
        ann_tab = QWidget()
        a_root = QVBoxLayout(ann_tab)
        a_root.setContentsMargins(8, 8, 8, 8)
        a_root.setSpacing(6)

        ann_top = QHBoxLayout()
        ann_top.setSpacing(4)
        ann_top.setContentsMargins(0, 0, 0, 0)
        ann_label = QLabel("Filter:")
        ann_label.setObjectName("InfoLabel")
        ann_top.addWidget(ann_label)
        self._annotation_filter = QComboBox()
        self._annotation_filter.addItems([
            "All", "Highlight", "Underline", "Strikethrough", "Note",
            "Text-box", "Rectangle", "Ellipse", "Line", "Arrow", "Freehand",
        ])
        self._annotation_filter.currentIndexChanged.connect(self._populate_annotation_list)
        ann_top.addWidget(self._annotation_filter, 1)
        a_root.addLayout(ann_top)

        self._annotation_list = QListWidget()
        self._annotation_list.setObjectName("annotation_list")
        self._annotation_list.setAlternatingRowColors(True)
        self._annotation_list.setSpacing(2)
        self._annotation_list.itemActivated.connect(self._jump_to_annotation_item)
        self._annotation_list.itemClicked.connect(self._jump_to_annotation_item)
        a_root.addWidget(self._annotation_list, 1)

        self._annotation_edit_btn = QPushButton("Properties")
        self._annotation_delete_btn = QPushButton("Delete")
        self._annotation_export_btn = QPushButton("Export PDF")
        self._annotation_edit_btn.setToolTip("Edit annotation properties")
        self._annotation_delete_btn.setToolTip("Delete selected annotation (Delete key)")
        self._annotation_export_btn.setToolTip("Save PDF with annotations embedded")
        self._annotation_edit_btn.clicked.connect(self._edit_selected_annotation)
        self._annotation_delete_btn.clicked.connect(self._delete_selected_annotation)
        self._annotation_export_btn.clicked.connect(self._export_pdf_with_annotations)

        ann_btn_row = QHBoxLayout()
        ann_btn_row.setContentsMargins(0, 0, 0, 0)
        ann_btn_row.setSpacing(4)
        ann_btn_row.addWidget(self._annotation_edit_btn)
        ann_btn_row.addWidget(self._annotation_delete_btn)
        a_root.addLayout(ann_btn_row)
        a_root.addWidget(self._annotation_export_btn)

        self._inspector_tabs.addTab(ann_tab, "Annotations")

        # ── Tab 3: Document ─────────────────────────────────────
        doc_tab = QWidget()
        d_root = QVBoxLayout(doc_tab)
        d_root.setContentsMargins(10, 10, 10, 10)
        d_root.setSpacing(8)

        doc_header = QLabel("Document Info")
        doc_header.setObjectName("InfoLabel")
        doc_header.setStyleSheet("font-weight:600; font-size:11px; margin-bottom:4px;")
        d_root.addWidget(doc_header)

        self._doc_name = self._info_row(d_root, "File", "No file")
        self._doc_page = self._info_row(d_root, "Page", "0 / 0")
        self._doc_zoom = self._info_row(d_root, "Zoom", "100%")

        d_root.addWidget(self._divider())

        self._reload_toggle = QCheckBox("Auto reload")
        self._reload_toggle.setChecked(True)
        self._reload_toggle.toggled.connect(self._toggle_auto_reload)
        d_root.addWidget(self._reload_toggle)
        d_root.addStretch()

        self._inspector_tabs.addTab(doc_tab, "Document")

        self._info_dock.setWidget(inspector_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._info_dock)
        self._info_dock.setMinimumWidth(220)
        self._info_dock.setMaximumWidth(420)

    # --------------------------- Dock toggles ---------------------------
    def _toggle_search_dock(self):
        visible = not self._search_dock.isVisible()
        self._search_dock.setVisible(visible)
        self._settings.setValue("window/show_search", visible)
        if hasattr(self, "_tb_search_btn"):
            self._tb_search_btn.setChecked(visible)
        if visible:
            self._search_input.setFocus()
            self._search_input.selectAll()

    def _toggle_outline_dock(self):
        visible = not self._outline_dock.isVisible()
        self._outline_dock.setVisible(visible)
        self._settings.setValue("window/show_outline", visible)
        if hasattr(self, "_tb_nav_btn"):
            self._tb_nav_btn.setChecked(visible)

    def _toggle_thumbs_dock(self):
        visible = not self._thumbs_dock.isVisible()
        self._thumbs_dock.setVisible(visible)
        self._settings.setValue("window/show_thumbnails", visible)
        if hasattr(self, "_tb_thumb_btn"):
            self._tb_thumb_btn.setChecked(visible)

    def _toggle_info_dock(self):
        visible = not self._info_dock.isVisible()
        self._info_dock.setVisible(visible)
        self._settings.setValue("window/show_inspector", visible)
        if hasattr(self, "_tb_info_btn"):
            self._tb_info_btn.setChecked(visible)

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
        if not restored_state:
            self._search_dock.setVisible(self._settings.value("window/show_search", False, type=bool))
            self._outline_dock.setVisible(self._settings.value("window/show_outline", False, type=bool))
            self._thumbs_dock.setVisible(self._settings.value("window/show_thumbnails", False, type=bool))
            self._info_dock.setVisible(self._settings.value("window/show_inspector", True, type=bool))

        # Sync panel toggle buttons with dock visibility
        if hasattr(self, "_tb_search_btn"):
            self._tb_search_btn.setChecked(self._search_dock.isVisible())
            self._tb_nav_btn.setChecked(self._outline_dock.isVisible())
            self._tb_thumb_btn.setChecked(self._thumbs_dock.isVisible())
            self._tb_info_btn.setChecked(self._info_dock.isVisible())

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
        self._settings.setValue("window/show_search", self._search_dock.isVisible())
        self._settings.setValue("window/show_outline", self._outline_dock.isVisible())
        self._settings.setValue("window/show_thumbnails", self._thumbs_dock.isVisible())
        self._settings.setValue("window/show_inspector", self._info_dock.isVisible())
        self._settings.setValue("view/auto_reload", self._auto_reload_enabled)
        self._settings.setValue("view/tool", self.current_view().tool.name)

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

        self._search_dock.setVisible(False)
        self._outline_dock.setVisible(False)
        self._thumbs_dock.setVisible(False)
        self._info_dock.setVisible(True)

        if hasattr(self, "_tb_search_btn"):
            self._tb_search_btn.setChecked(False)
            self._tb_nav_btn.setChecked(False)
            self._tb_thumb_btn.setChecked(False)
            self._tb_info_btn.setChecked(True)

        self._settings.remove("window/geometry")
        self._settings.remove("window/state")
        self._settings.setValue("window/start_state", "normal")
        self._settings.setValue("window/show_search", False)
        self._settings.setValue("window/show_outline", False)
        self._settings.setValue("window/show_thumbnails", False)
        self._settings.setValue("window/show_inspector", True)
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
        self._document_sessions[path] = {
            "page": int(view.current_page),
            "zoom": float(view.zoom),
            "zoom_mode": view.zoom_mode,
        }

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

        if not target.open_document(norm_path):
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
        self._populate_outline()
        self._populate_annotation_list()
        self._update_status()
        self._update_mtime()
        self._start_watch()
        self._schedule_session_save()

    def _refresh_document_info(self):
        view = self.current_view()
        ctx = self.current_context()
        doc = view.document

        if not doc:
            self._doc_name.setText("No file")
            self._doc_page.setText("0 / 0")
            self._doc_zoom.setText("--")
            self._page_count_lbl.setText("Pages: 0")
            self._page_total_lbl.setText(" / 0 ")
            self._page_nav_combo.blockSignals(True)
            self._page_nav_combo.clear()
            self._page_nav_combo.blockSignals(False)
            self._outline_tree.clear()
            self._thumbs_list.clear()
            self._clear_thumbnail_queue()
            self._update_measurements_panel(None)
            self._populate_annotation_list()
            self.setWindowTitle(APP_NAME)
            return

        source_path = ctx.file_path or view.doc_path
        name = os.path.basename(source_path) if source_path else "Untitled"
        self._doc_name.setText(name)
        self._doc_page.setText(f"{view.current_page + 1} / {doc.page_count}")
        self._doc_zoom.setText(f"{view.zoom * 100:.0f}%")
        self._page_count_lbl.setText(f"Pages: {doc.page_count}")
        self._page_total_lbl.setText(f" / {doc.page_count} ")
        self._page_nav_combo.blockSignals(True)
        self._page_nav_combo.clear()
        self._page_nav_combo.addItems([str(i + 1) for i in range(doc.page_count)])
        self._page_nav_combo.setCurrentText(str(view.current_page + 1))
        self._page_nav_combo.blockSignals(False)
        self.setWindowTitle(f"{APP_NAME} - {name}")

        self._populate_outline()
        self._populate_thumbnails()
        self._populate_annotation_list()

    # --------------------------- Navigation / TOC / bookmarks ---------------------------
    def _populate_outline(self):
        self._outline_tree.clear()

        view = self.current_view()
        ctx = self.current_context()
        doc = view.document

        root_toc = QTreeWidgetItem(["Document TOC"])
        root_toc.setData(0, self.ROLE_KIND, "toc_root")
        root_bookmarks = QTreeWidgetItem(["My Bookmarks"])
        root_bookmarks.setData(0, self.ROLE_KIND, "bookmark_root")

        self._outline_tree.addTopLevelItem(root_toc)
        self._outline_tree.addTopLevelItem(root_bookmarks)
        root_toc.setExpanded(True)
        root_bookmarks.setExpanded(True)

        filt = self._outline_filter.text().strip().lower()

        if doc:
            for level, title, page in doc.get_toc(simple=True):
                page_idx = max(0, page - 1)
                if filt and filt not in title.lower() and filt not in str(page):
                    continue
                display = f"{'  ' * max(0, level - 1)}{title}"
                item = QTreeWidgetItem([display])
                item.setData(0, self.ROLE_KIND, "toc")
                item.setData(0, self.ROLE_PAGE, page_idx)
                root_toc.addChild(item)

        for bookmark in ctx.sidecar_state.bookmarks:
            if filt and filt not in bookmark.title.lower() and filt not in str(bookmark.page + 1):
                continue
            item = QTreeWidgetItem([f"{bookmark.title} (p{bookmark.page + 1})"])
            item.setData(0, self.ROLE_KIND, "bookmark")
            item.setData(0, self.ROLE_PAGE, bookmark.page)
            item.setData(0, self.ROLE_BOOKMARK_ID, bookmark.id)
            root_bookmarks.addChild(item)

        self._sync_outline_current_page(view.current_page)

    def _sync_outline_current_page(self, page_idx: int):
        nearest_item = None
        nearest_page = -1

        root_toc = self._outline_tree.topLevelItem(0)
        if root_toc is None:
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

    def _on_outline_context_menu(self, pos: QPoint):
        item = self._outline_tree.itemAt(pos)
        if item is None:
            return
        if item.data(0, self.ROLE_KIND) != "bookmark":
            return

        bookmark_id = item.data(0, self.ROLE_BOOKMARK_ID)
        if not bookmark_id:
            return

        menu = QMenu(self)
        rename_action = menu.addAction("Rename Bookmark")
        delete_action = menu.addAction("Delete Bookmark")
        chosen = menu.exec(self._outline_tree.viewport().mapToGlobal(pos))
        if chosen is rename_action:
            self._rename_bookmark(str(bookmark_id))
        elif chosen is delete_action:
            self._delete_bookmark(str(bookmark_id))

    def _find_bookmark_by_id(self, bookmark_id: str) -> Optional[BookmarkRecord]:
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
        self._populate_outline()
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
        self._populate_outline()

    def _delete_bookmark(self, bookmark_id: str):
        ctx = self.current_context()
        before = len(ctx.sidecar_state.bookmarks)
        ctx.sidecar_state.bookmarks = [b for b in ctx.sidecar_state.bookmarks if b.id != bookmark_id]
        if len(ctx.sidecar_state.bookmarks) != before:
            self._mark_sidecar_dirty(self.current_view())
            self._populate_outline()
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
        self._toggle_search_dock()

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

    def _update_search_count_label(self, ctx: Optional[TabContext] = None):
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

    def _search_page_rects(self, page: fitz.Page, query: str) -> List[fitz.Rect]:
        return list(page.search_for(query))

    def _scan_search_batch(self, operation: Dict[str, object]) -> bool:
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

    def _apply_search_results(self, view: PdfView, ctx: TabContext, results: List[SearchMatch], post_nav: int = 0):
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
        if view is not self.current_view() or ctx is not self.current_context():
            self._cancel_search_operation()
            return

        completed = self._scan_search_batch(operation)
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
        max_results: Optional[int] = None,
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
            operation: Dict[str, object] = {
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

        # Do not call view.set_annotations() here — that triggers a full scene
        # rebuild on every filter change.  set_annotations() is called only when
        # annotation data actually changes (load, create, delete, edit).

    def _find_annotation_by_id(self, ann_id: str) -> Optional[AnnotationRecord]:
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

    def _selected_annotation_id(self) -> Optional[str]:
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
        # Auto-switch inspector to Annotations tab
        if hasattr(self, "_inspector_tabs"):
            self._inspector_tabs.setCurrentIndex(self._INSPECTOR_TAB_ANNOTATIONS)

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
        from PySide6.QtWidgets import (
            QColorDialog,
            QDialog,
            QDialogButtonBox,
            QDoubleSpinBox,
            QFormLayout,
            QSlider,
            QTextEdit,
        )

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Annotation Properties ({ann.type})")
        dlg.setMinimumWidth(380)
        form = QFormLayout(dlg)

        # Text / contents (for types that support it)
        text_edit = None
        if ann.type in ("note", "text-box"):
            text_edit = QTextEdit()
            text_edit.setPlainText(ann.contents)
            text_edit.setFixedHeight(90)
            form.addRow("Text:", text_edit)

        # Color
        color_btn = QPushButton()
        color_btn.setFixedSize(60, 24)
        cur_color = QColor(ann.color or "#f7c948")

        def _update_color_btn(c: QColor):
            pix = QPixmap(40, 16)
            pix.fill(c)
            color_btn.setIcon(QIcon(pix))
            color_btn.setText(c.name())
        _update_color_btn(cur_color)

        chosen_color = [cur_color]

        def _pick_color():
            c = QColorDialog.getColor(chosen_color[0], dlg, "Annotation Color")
            if c.isValid():
                chosen_color[0] = c
                _update_color_btn(c)
        color_btn.clicked.connect(_pick_color)
        form.addRow("Color:", color_btn)

        # Opacity
        opacity_slider = QSlider(Qt.Orientation.Horizontal)
        opacity_slider.setRange(5, 100)
        opacity_slider.setValue(int(ann.opacity * 100))
        opacity_label = QLabel(f"{int(ann.opacity * 100)}%")
        opacity_slider.valueChanged.connect(lambda v: opacity_label.setText(f"{v}%"))
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(opacity_slider)
        opacity_row.addWidget(opacity_label)
        opacity_container = QWidget()
        opacity_container.setLayout(opacity_row)
        form.addRow("Opacity:", opacity_container)

        # Border width (for shapes, freehand, line, arrow)
        if ann.type in ("rectangle", "ellipse", "line", "arrow", "freehand", "text-box"):
            width_spin = QDoubleSpinBox()
            width_spin.setRange(0.5, 20.0)
            width_spin.setSingleStep(0.5)
            width_spin.setDecimals(1)
            width_spin.setValue(ann.border_width)
            form.addRow("Stroke width:", width_spin)
        else:
            width_spin = None

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        ann.color = chosen_color[0].name()
        ann.opacity = opacity_slider.value() / 100.0
        if text_edit is not None:
            ann.contents = text_edit.toPlainText()
        if width_spin is not None:
            ann.border_width = width_spin.value()
        ann.updated_at = ""
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

    def _build_annotation_from_selection(self, ann_type: str) -> Optional[AnnotationRecord]:
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
            import fitz as _fitz
            doc = _fitz.open(src)
            for ann_rec in ctx.sidecar_state.annotations:
                if not (0 <= ann_rec.page < doc.page_count):
                    continue
                page = doc[ann_rec.page]
                x, y, w, h = ann_rec.rect
                rect = _fitz.Rect(x, y, x + w, y + h)
                color_obj = QColor(ann_rec.color or "#f7c948")
                rgb = (color_obj.redF(), color_obj.greenF(), color_obj.blueF())

                # Resolve border/stroke color
                if ann_rec.border_color:
                    bc_obj = QColor(ann_rec.border_color)
                    stroke_rgb = (bc_obj.redF(), bc_obj.greenF(), bc_obj.blueF())
                else:
                    stroke_rgb = rgb

                t = ann_rec.type
                if t == "highlight":
                    a = page.add_highlight_annot(rect)
                elif t == "underline":
                    a = page.add_underline_annot(rect)
                elif t == "strikethrough":
                    a = page.add_strikeout_annot(rect)
                elif t in ("note",):
                    a = page.add_text_annot(_fitz.Point(x, y), ann_rec.contents or "")
                elif t == "text-box":
                    a = page.add_freetext_annot(rect, ann_rec.contents or "", fontsize=ann_rec.font_size, text_color=rgb)
                elif t == "rectangle":
                    a = page.add_rect_annot(rect)
                elif t == "ellipse":
                    a = page.add_circle_annot(rect)
                elif t == "line":
                    a = page.add_line_annot(_fitz.Point(x, y), _fitz.Point(x + w, y + h))
                elif t == "arrow":
                    a = page.add_line_annot(_fitz.Point(x, y), _fitz.Point(x + w, y + h))
                elif t == "freehand" and ann_rec.points:
                    pts = [(p[0], p[1]) for p in ann_rec.points]
                    a = page.add_ink_annot([pts])
                else:
                    continue

                try:
                    # Apply colors per annotation type
                    if t in ("highlight", "underline", "strikethrough"):
                        # Text markup: only color matters (no stroke/fill distinction)
                        a.set_colors(stroke=rgb)
                    elif t in ("rectangle", "ellipse"):
                        # Shapes: stroke = border_color, fill = color
                        a.set_colors(stroke=stroke_rgb, fill=rgb)
                    elif t in ("line", "arrow", "freehand"):
                        # Lines/paths: stroke only
                        a.set_colors(stroke=stroke_rgb)
                    elif t == "note":
                        a.set_colors(fill=rgb)
                    elif t == "text-box":
                        pass  # colors set via add_freetext_annot params
                    else:
                        a.set_colors(stroke=rgb, fill=rgb)

                    a.set_opacity(ann_rec.opacity)

                    # Apply border width for shapes, lines, and freehand
                    if t in ("rectangle", "ellipse", "line", "arrow", "freehand"):
                        a.set_border(width=ann_rec.border_width)

                    # Arrow line ending
                    if t == "arrow":
                        a.set_line_ends(_fitz.PDF_ANNOT_LE_NONE, _fitz.PDF_ANNOT_LE_CLOSED_ARROW)

                    if ann_rec.contents and t not in ("note", "text-box", "freehand"):
                        a.set_info(content=ann_rec.contents)
                    a.update()
                except Exception:
                    pass

            doc.save(out_path, garbage=4, deflate=True)
            doc.close()
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

        for i in range(doc.page_count):
            item = QListWidgetItem(f"{i + 1}")
            cached = self._thumb_icon_cache.get((self._thumb_source_key, i))
            if cached is not None:
                item.setIcon(cached)
            else:
                item.setIcon(self._icon("image-x-generic", QStyle.StandardPixmap.SP_FileIcon))
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._thumbs_list.addItem(item)

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
                    pix = page.get_pixmap(matrix=fitz.Matrix(0.15, 0.15), alpha=False)
                    image = QImage(
                        pix.samples,
                        pix.width,
                        pix.height,
                        pix.stride,
                        QImage.Format.Format_RGB888,
                    ).copy()
                    icon = QIcon(QPixmap.fromImage(image))
                    self._thumb_icon_cache[cache_key] = icon
                except Exception:
                    icon = self._icon("image-x-generic", QStyle.StandardPixmap.SP_FileIcon)

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
        try:
            page = int(raw)
        except ValueError:
            return
        view = self.current_view()
        if view.document and 1 <= page <= view.page_count:
            view.go_to_page(page - 1)

    def _on_view_page_changed(self, view: PdfView, current: int, total: int):
        if not self._is_current_view(view):
            return

        self._doc_page.setText(f"{current} / {total}")
        self._page_count_lbl.setText(f"Pages: {total}")
        self._page_total_lbl.setText(f" / {total} ")
        self._page_nav_combo.blockSignals(True)
        self._page_nav_combo.setCurrentText(str(current))
        self._page_nav_combo.blockSignals(False)

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

        # Auto-switch inspector to Font tab when hovering text (SELECT tool only)
        if hasattr(self, "_inspector_tabs"):
            view = self.current_view()
            if view.tool == ToolMode.SELECT:
                self._inspector_tabs.setCurrentIndex(self._INSPECTOR_TAB_FONT)

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
        import fitz as _fitz

        _FITZ_TYPE_MAP = {
            _fitz.PDF_ANNOT_HIGHLIGHT: "highlight",
            _fitz.PDF_ANNOT_UNDERLINE: "underline",
            _fitz.PDF_ANNOT_SQUIGGLY: "underline",
            _fitz.PDF_ANNOT_STRIKE_OUT: "strikethrough",
            _fitz.PDF_ANNOT_TEXT: "note",
            _fitz.PDF_ANNOT_FREE_TEXT: "text-box",
            _fitz.PDF_ANNOT_SQUARE: "rectangle",
            _fitz.PDF_ANNOT_CIRCLE: "ellipse",
            _fitz.PDF_ANNOT_LINE: "line",
            _fitz.PDF_ANNOT_INK: "freehand",
            _fitz.PDF_ANNOT_POLYGON: "rectangle",
            _fitz.PDF_ANNOT_POLY_LINE: "line",
            _fitz.PDF_ANNOT_STAMP: "rectangle",
        }

        native = []
        doc = view.document
        if not doc:
            ctx.native_annotations = native
            return

        try:
            for page_idx in range(doc.page_count):
                page = doc[page_idx]
                for ann in page.annots():
                    ann_type = ann.type[0]
                    mapped = _FITZ_TYPE_MAP.get(ann_type)
                    if mapped is None:
                        continue
                    r = ann.rect
                    color_tuple = ann.colors.get("stroke") or ann.colors.get("fill") or (1.0, 0.8, 0.0)
                    hex_color = "#{:02x}{:02x}{:02x}".format(
                        int(color_tuple[0] * 255),
                        int(color_tuple[1] * 255),
                        int(color_tuple[2] * 255),
                    )
                    info = ann.info
                    contents = info.get("content", "") or ""
                    native.append(
                        AnnotationRecord(
                            id=f"native-{page_idx}-{len(native)}",
                            type=mapped,
                            page=page_idx,
                            rect=(r.x0, r.y0, r.width, r.height),
                            color=hex_color,
                            opacity=ann.opacity if ann.opacity is not None else 0.4,
                            contents=contents,
                        )
                    )
        except Exception:
            pass

        ctx.native_annotations = native

    def _on_view_document_loaded(self, view: PdfView):
        if self._reload_in_progress:
            return
        ctx = self._context_for_view(view)
        if ctx.file_path:
            ctx.sidecar_state = clamp_sidecar_for_page_count(ctx.sidecar_state, view.page_count)
            self._load_native_pdf_annotations(view, ctx)
            all_annotations = ctx.sidecar_state.annotations + ctx.native_annotations
            view.set_annotations(all_annotations)
        if self._is_current_view(view):
            self._refresh_document_info()
            self._populate_outline()
            self._populate_annotation_list()

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

    def _file_signature(self, path: Optional[str]) -> Optional[Tuple[int, int, int]]:
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
            reloaded = view.reload_document()
        finally:
            self._reload_in_progress = False

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

    def _set_tool(self, tool: ToolMode):
        view = self.current_view()
        view.tool = tool

        self._select_action.setChecked(tool == ToolMode.SELECT)
        self._hand_action.setChecked(tool == ToolMode.HAND)
        self._measure_action.setChecked(tool == ToolMode.MEASURE)
        self._annotate_action.setChecked(tool == ToolMode.ANNOTATE)
        self._toolbar_select_action.setChecked(tool == ToolMode.SELECT)
        self._toolbar_hand_action.setChecked(tool == ToolMode.HAND)
        self._toolbar_measure_action.setChecked(tool == ToolMode.MEASURE)
        self._toolbar_annotate_action.setChecked(tool == ToolMode.ANNOTATE)

        self._panel_select_btn.setChecked(tool == ToolMode.SELECT)
        self._panel_hand_btn.setChecked(tool == ToolMode.HAND)
        self._panel_measure_btn.setChecked(tool == ToolMode.MEASURE)
        self._panel_annotate_btn.setChecked(tool == ToolMode.ANNOTATE)

        # Show/hide annotation toolbar
        self._ann_toolbar.setVisible(tool == ToolMode.ANNOTATE)

        # Auto-switch inspector tab to context-relevant panel
        if hasattr(self, "_inspector_tabs"):
            if tool == ToolMode.MEASURE:
                self._inspector_tabs.setCurrentIndex(self._INSPECTOR_TAB_MEASURE)
            elif tool == ToolMode.ANNOTATE:
                self._inspector_tabs.setCurrentIndex(self._INSPECTOR_TAB_ANNOTATIONS)
            elif tool in (ToolMode.SELECT, ToolMode.HAND):
                # Only switch away from measure/annotate tabs; stay if already on font/doc
                cur = self._inspector_tabs.currentIndex()
                if cur in (self._INSPECTOR_TAB_MEASURE, self._INSPECTOR_TAB_ANNOTATIONS):
                    self._inspector_tabs.setCurrentIndex(self._INSPECTOR_TAB_FONT)

        self._settings.setValue("view/tool", tool.name)
        self._update_status()

    def _on_zoom_combo_changed(self, text: str):
        if self._zoom_combo_updating:
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
        self.current_view().set_zoom(value / 100.0, immediate=True, zoom_mode=PdfView.ZOOM_MODE_CUSTOM)

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
    def _update_measurements_panel(self, sel: Optional[QRectF]):
        if not sel:
            self._measure_w.setText("W  --")
            self._measure_h.setText("H  --")
            self._measure_x.setText("X  --")
            self._measure_y.setText("Y  --")
            return
        self._measure_w.setText(f"W  {sel.width():.1f} pt")
        self._measure_h.setText(f"H  {sel.height():.1f} pt")
        self._measure_x.setText(f"X  {sel.x():.1f} pt")
        self._measure_y.setText(f"Y  {sel.y():.1f} pt")

    def _update_status(self):
        view = self.current_view()
        ctx = self.current_context()

        if view.document:
            name = os.path.basename(ctx.file_path) if ctx.file_path else "Untitled"
            zoom_text = f"{view.zoom * 100:.0f}%"

            self._status_dot.setProperty("offline", False)
            self._status_dot.style().unpolish(self._status_dot)
            self._status_dot.style().polish(self._status_dot)

            self._file_lbl.setText(name)
            self._zoom_lbl.setText(zoom_text)
            self._doc_name.setText(name)
            self._doc_zoom.setText(zoom_text)
            self._doc_page.setText(f"{view.current_page + 1} / {view.page_count}")
            self._page_count_lbl.setText(f"Pages: {view.page_count}")
            self._page_total_lbl.setText(f" / {view.page_count} ")
            self._page_nav_combo.blockSignals(True)
            self._page_nav_combo.setCurrentText(str(view.current_page + 1))
            self._page_nav_combo.blockSignals(False)

            self._sync_zoom_combo()
            self._update_measurements_panel(view.selection_rect)
        else:
            self._status_dot.setProperty("offline", True)
            self._status_dot.style().unpolish(self._status_dot)
            self._status_dot.style().polish(self._status_dot)

            self._file_lbl.setText("No file")
            self._page_count_lbl.setText("Pages: 0")
            self._page_total_lbl.setText(" / 0 ")
            self._zoom_lbl.setText("--")
            self._doc_name.setText("No file")
            self._doc_page.setText("0 / 0")
            self._doc_zoom.setText("--")
            self._sync_zoom_combo()
            self._update_measurements_panel(None)

        self._toolbar_select_action.setChecked(view.tool == ToolMode.SELECT)
        self._toolbar_hand_action.setChecked(view.tool == ToolMode.HAND)
        self._toolbar_measure_action.setChecked(view.tool == ToolMode.MEASURE)
        self._toolbar_annotate_action.setChecked(view.tool == ToolMode.ANNOTATE)
        self._panel_select_btn.setChecked(view.tool == ToolMode.SELECT)
        self._panel_hand_btn.setChecked(view.tool == ToolMode.HAND)
        self._panel_measure_btn.setChecked(view.tool == ToolMode.MEASURE)
        self._panel_annotate_btn.setChecked(view.tool == ToolMode.ANNOTATE)

    # ----------------------- Performance mode helpers -----------------------
    def _on_performance_mode_toggled(self, checked: bool) -> None:
        view = self.current_view()
        if isinstance(view, PdfView):
            view.set_performance_mode(checked)
        self._update_perf_status()

    def _update_perf_status(self) -> None:
        view = self.current_view()
        if isinstance(view, PdfView) and view.is_performance_mode():
            self._perf_label.setText("Perf Mode ON")
        else:
            self._perf_label.setText("")

    # --------------------------- Utility widgets ---------------------------
    def _hand_icon(self) -> QIcon:
        for name in (
            "cursor-openhand",
            "pan",
            "tool-pan",
            "input-touchpad",
            "draw-freehand",
        ):
            icon = QIcon.fromTheme(name)
            if not icon.isNull():
                return icon

        app = QApplication.instance()
        is_dark = str(app.property("theme_mode") or "").lower() == "dark" if app else False
        line_color = QColor("#cccccc") if is_dark else QColor("#555555")
        fill_color = QColor("#37547a") if is_dark else QColor("#ffffff")

        pix = QPixmap(20, 20)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(line_color, 1.3))
        painter.setBrush(fill_color)

        painter.drawRoundedRect(7.0, 9.0, 7.0, 7.0, 1.6, 1.6)  # palm
        painter.drawRoundedRect(7.0, 4.0, 1.4, 5.4, 0.7, 0.7)  # index
        painter.drawRoundedRect(8.8, 3.5, 1.4, 5.8, 0.7, 0.7)  # middle
        painter.drawRoundedRect(10.6, 4.0, 1.4, 5.4, 0.7, 0.7)  # ring
        painter.drawRoundedRect(12.4, 4.8, 1.4, 4.6, 0.7, 0.7)  # pinky

        thumb = QPolygonF(
            [
                QPointF(7.0, 10.2),
                QPointF(4.4, 9.0),
                QPointF(3.8, 11.7),
                QPointF(6.6, 12.8),
            ]
        )
        painter.drawPolygon(thumb)
        painter.end()
        return QIcon(pix)

    def _icon(self, name: str, fallback: QStyle.StandardPixmap) -> QIcon:
        icon = QIcon.fromTheme(name)
        if not icon.isNull():
            return icon
        return self.style().standardIcon(fallback)

    def _action(self, text: str, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        return action

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setProperty("separator", True)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        return line

    def _kv_value(self, label: str) -> QLabel:
        value = QLabel(f"{label}  --")
        value.setObjectName("MonoValue")
        return value

    def _info_row(self, parent_layout: QVBoxLayout, label: str, value: str) -> QLabel:
        row = QHBoxLayout()
        key = QLabel(f"{label}:")
        key.setObjectName("InfoLabel")
        val = QLabel(value)
        val.setObjectName("InfoValue")
        val.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(key)
        row.addStretch()
        row.addWidget(val)
        parent_layout.addLayout(row)
        return val

    def closeEvent(self, e):
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
