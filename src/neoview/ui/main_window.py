"""Main application window."""

from __future__ import annotations

from collections import deque
import json
import os
from typing import Dict, List, Optional

import fitz
from PySide6.QtCore import QFileSystemWatcher, QPoint, QRectF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QImage, QKeySequence, QPixmap
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
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QStyle,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from neoview.resources import load_app_icon
from neoview.ui.dialogs import ExportDialog, FindDialog
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
    def __init__(self, pdf_path: Optional[str] = None):
        super().__init__()

        self.setWindowTitle(APP_NAME)
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1200, 900)

        self._current_file: Optional[str] = None
        self._last_mtime: float = 0
        self._search_query: str = ""
        self._search_results: List[tuple] = []
        self._search_index: int = -1
        self._find_dlg: Optional[FindDialog] = None
        self._find_input: Optional[QLineEdit] = None
        self._settings = QSettings("NeoView", "NeoView")
        self._recent_files: List[str] = self._settings.value("recent_files", [], type=list)
        self._recent_menu: Optional[object] = None
        self._document_sessions: Dict[str, Dict[str, object]] = self._load_json_setting("documents/session", {})
        self._zoom_combo_updating = False
        self._auto_reload_enabled = self._settings.value("view/auto_reload", True, type=bool)
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

        self._setup_ui()
        self._restore_persistent_ui()

        if pdf_path:
            self._open_file(pdf_path)

    def _setup_ui(self):
        self._view = PdfView(self)
        self.setCentralWidget(self._view)

        self._view.selection_changed.connect(self._update_status)
        self._view.zoom_changed.connect(self._update_status)
        self._view.zoom_changed.connect(self._schedule_session_save)
        self._view.page_changed.connect(self._on_page_changed)
        self._view.page_changed.connect(lambda _current, _total: self._schedule_session_save())
        self._view.text_info_changed.connect(self._on_text_info)
        self._view.text_selected.connect(self._on_text_selected)
        self._view.document_loaded.connect(self._refresh_document_info)

        self._setup_menus()
        self._setup_toolbar()
        self._setup_statusbar()
        self._setup_docks()
        self._update_status()

    def _setup_menus(self):
        file_m = self.menuBar().addMenu("&File")
        self._open_action = self._action("&Open...", self._open_dialog, QKeySequence.StandardKey.Open)
        file_m.addAction(self._open_action)

        self._recent_menu = file_m.addMenu("Open &Recent")
        self._rebuild_recent_menu()

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
        edit_m.addAction(self._action("C&lear Selection", self._view.clear_all_selection, "Escape"))

        view_m = self.menuBar().addMenu("&View")
        self._zoom_in_action = self._action("Zoom &In", lambda: self._view.zoom_by(1.25), QKeySequence.StandardKey.ZoomIn)
        self._zoom_out_action = self._action("Zoom &Out", lambda: self._view.zoom_by(0.8), QKeySequence.StandardKey.ZoomOut)
        self._fit_width_action = self._action("Fit &Width", self._view.fit_width, "W")
        self._fit_page_action = self._action("Fit &Page", self._view.fit_page, "F")
        self._actual_size_action = self._action("&Actual Size", self._view.actual_size, "Ctrl+1")

        view_m.addAction(self._zoom_in_action)
        view_m.addAction(self._zoom_out_action)
        view_m.addSeparator()
        view_m.addAction(self._fit_width_action)
        view_m.addAction(self._fit_page_action)
        view_m.addAction(self._actual_size_action)
        view_m.addSeparator()
        view_m.addAction(self._action("Rotate &Left", lambda: self._view.rotate_by(-90), "Ctrl+L"))
        view_m.addAction(self._action("Rotate &Right", lambda: self._view.rotate_by(90), "Ctrl+R"))
        view_m.addAction(self._action("Reset &Rotation", lambda: self._view.set_rotation(0), "Ctrl+0"))

        go_m = self.menuBar().addMenu("&Go")
        go_m.addAction(self._action("&Previous Page", self._view.prev_page, "PgUp"))
        go_m.addAction(self._action("&Next Page", self._view.next_page, "PgDown"))
        go_m.addAction(self._action("&First Page", self._view.first_page, "Home"))
        go_m.addAction(self._action("&Last Page", self._view.last_page, "End"))

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

        tools_m.addSeparator()
        tools_m.addAction(self._action("&Search Panel", self._toggle_search_dock, "Ctrl+Shift+F"))
        tools_m.addAction(self._action("&Outline Panel", self._toggle_outline_dock, "Ctrl+Shift+O"))
        tools_m.addAction(self._action("&Thumbnails Panel", self._toggle_thumbs_dock, "Ctrl+Shift+T"))
        tools_m.addAction(self._action("&Page Info Panel", self._toggle_info_dock, "Ctrl+Shift+I"))

        self._open_action.setIcon(self._icon("document-open", QStyle.StandardPixmap.SP_DialogOpenButton))
        self._zoom_out_action.setIcon(self._icon("zoom-out", QStyle.StandardPixmap.SP_ArrowDown))
        self._zoom_in_action.setIcon(self._icon("zoom-in", QStyle.StandardPixmap.SP_ArrowUp))
        self._fit_width_action.setIcon(self._icon("zoom-fit-width", QStyle.StandardPixmap.SP_TitleBarMaxButton))
        self._fit_page_action.setIcon(self._icon("zoom-fit-best", QStyle.StandardPixmap.SP_DesktopIcon))
        self._actual_size_action.setIcon(self._icon("zoom-original", QStyle.StandardPixmap.SP_ComputerIcon))
        self._select_action.setIcon(self._icon("cursor-arrow", QStyle.StandardPixmap.SP_ArrowRight))
        self._copy_action.setIcon(self._icon("edit-copy", QStyle.StandardPixmap.SP_FileIcon))
        self._export_action.setIcon(self._icon("document-save", QStyle.StandardPixmap.SP_DialogSaveButton))

        self._open_action.setToolTip("Open PDF (Ctrl+O)")
        self._zoom_out_action.setToolTip("Zoom out")
        self._zoom_in_action.setToolTip("Zoom in")
        self._fit_width_action.setToolTip("Fit width (W)")
        self._actual_size_action.setToolTip("Actual size (Ctrl+1)")
        self._select_action.setToolTip("Select tool (1)")
        self._copy_action.setToolTip("Copy measurements (Ctrl+C)")
        self._export_action.setToolTip("Export selection")

    def _setup_toolbar(self):
        tb = QToolBar("Main")
        tb.setObjectName("MainToolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(tb)

        # File section
        tb.addAction(self._open_action)

        self._recent_btn = QToolButton(self)
        self._recent_btn.setIcon(self._icon("document-open-recent", QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self._recent_btn.setToolTip("Open recent file")
        self._recent_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._recent_btn.setMenu(self._recent_menu)
        tb.addWidget(self._recent_btn)
        tb.addSeparator()

        # View section
        tb.addAction(self._zoom_out_action)

        self._zoom_combo = QComboBox(self)
        self._zoom_combo.setEditable(True)
        self._zoom_combo.setMinimumWidth(84)
        self._zoom_combo.addItems(["50%", "75%", "100%", "125%", "150%", "200%", "300%"])
        self._zoom_combo.setCurrentText("100%")
        self._zoom_combo.currentTextChanged.connect(self._on_zoom_combo_changed)
        tb.addWidget(self._zoom_combo)

        tb.addAction(self._zoom_in_action)
        tb.addAction(self._fit_width_action)
        tb.addAction(self._actual_size_action)
        tb.addSeparator()

        # Tools section
        self._toolbar_select_action = QAction(self._icon("cursor-arrow", QStyle.StandardPixmap.SP_ArrowRight), "Select", self)
        self._toolbar_select_action.setToolTip("Select tool (1)")
        self._toolbar_select_action.setCheckable(True)
        self._toolbar_select_action.triggered.connect(lambda: self._set_tool(ToolMode.SELECT))
        tb.addAction(self._toolbar_select_action)

        self._toolbar_export_action = QAction(self._icon("document-save", QStyle.StandardPixmap.SP_DialogSaveButton), "Export", self)
        self._toolbar_export_action.setToolTip("Export selection")
        self._toolbar_export_action.triggered.connect(self._export)
        tb.addAction(self._toolbar_export_action)

        self._toolbar_copy_action = QAction(self._icon("edit-copy", QStyle.StandardPixmap.SP_FileIcon), "Copy Measurements", self)
        self._toolbar_copy_action.setToolTip("Copy measurements (Ctrl+C)")
        self._toolbar_copy_action.triggered.connect(self._copy)
        tb.addAction(self._toolbar_copy_action)

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
        self._status.addWidget(self._page_count_lbl)
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
        search_layout = QHBoxLayout(search_widget)
        search_layout.setContentsMargins(6, 6, 6, 6)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Find text...")
        self._search_prev_btn = QPushButton("Prev")
        self._search_next_btn = QPushButton("Next")
        self._search_close_btn = QPushButton("Close")
        self._search_close_btn.setProperty("secondary", True)
        self._search_count_lbl = QLabel("")
        search_layout.addWidget(self._search_input)
        search_layout.addWidget(self._search_prev_btn)
        search_layout.addWidget(self._search_next_btn)
        search_layout.addWidget(self._search_close_btn)
        search_layout.addWidget(self._search_count_lbl)
        self._search_dock.setWidget(search_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._search_dock)
        self._search_dock.hide()

        self._search_prev_btn.clicked.connect(self._find_prev)
        self._search_next_btn.clicked.connect(self._find_next)
        self._search_close_btn.clicked.connect(lambda: self._search_dock.setVisible(False))
        self._search_input.returnPressed.connect(self._find_next)

        self._outline_dock = QDockWidget("Outline", self)
        self._outline_dock.setObjectName("OutlineDock")
        self._outline_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._outline_list = QListWidget()
        self._outline_dock.setWidget(self._outline_list)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._outline_dock)
        self._outline_dock.hide()
        self._outline_list.itemActivated.connect(self._jump_to_outline_item)

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
        self._info_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self._info_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)

        inspector_widget = QWidget()
        inspector_widget.setObjectName("InspectorPanel")
        inspector_widget.setMinimumWidth(240)
        inspector_widget.setMaximumWidth(240)

        inspector_layout = QVBoxLayout(inspector_widget)
        inspector_layout.setContentsMargins(12, 12, 12, 12)
        inspector_layout.setSpacing(0)

        measure_section = CollapsibleSection("Measurements")
        m_layout = measure_section.content_layout
        self._measure_w = self._kv_value("W")
        self._measure_h = self._kv_value("H")
        self._measure_x = self._kv_value("X")
        self._measure_y = self._kv_value("Y")
        m_layout.addWidget(self._measure_w)
        m_layout.addWidget(self._measure_h)
        m_layout.addWidget(self._measure_x)
        m_layout.addWidget(self._measure_y)

        tool_label = QLabel("Tool")
        tool_label.setObjectName("InfoLabel")
        m_layout.addWidget(tool_label)
        tool_row = QHBoxLayout()
        tool_row.setContentsMargins(0, 0, 0, 0)
        tool_row.setSpacing(6)
        self._panel_tool_group = QButtonGroup(self)
        self._panel_tool_group.setExclusive(True)
        self._panel_select_btn = QPushButton("Select (1)")
        self._panel_hand_btn = QPushButton("Hand (2)")
        self._panel_measure_btn = QPushButton("Measure (3)")
        for btn, mode in (
            (self._panel_select_btn, ToolMode.SELECT),
            (self._panel_hand_btn, ToolMode.HAND),
            (self._panel_measure_btn, ToolMode.MEASURE),
        ):
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked=False, m=mode: self._set_tool(m))
            self._panel_tool_group.addButton(btn)
            tool_row.addWidget(btn)
        m_layout.addLayout(tool_row)

        font_section = CollapsibleSection("Font Inspector")
        f_layout = font_section.content_layout
        self._font_name = self._info_row(f_layout, "Name", "--")
        self._font_size = self._info_row(f_layout, "Size", "--")
        self._font_style = self._info_row(f_layout, "Style", "--")

        document_section = CollapsibleSection("Document")
        d_layout = document_section.content_layout
        self._doc_name = self._info_row(d_layout, "File", "No file")
        self._doc_page = self._info_row(d_layout, "Page", "0 / 0")
        self._doc_zoom = self._info_row(d_layout, "Zoom", "100%")
        self._reload_toggle = QCheckBox("Auto reload")
        self._reload_toggle.setChecked(True)
        self._reload_toggle.toggled.connect(self._toggle_auto_reload)
        d_layout.addWidget(self._reload_toggle)

        inspector_layout.addWidget(measure_section)
        inspector_layout.addWidget(self._divider())
        inspector_layout.addWidget(font_section)
        inspector_layout.addWidget(self._divider())
        inspector_layout.addWidget(document_section)
        inspector_layout.addStretch()

        self._info_dock.setWidget(inspector_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._info_dock)
        self._info_dock.setMinimumWidth(240)
        self._info_dock.setMaximumWidth(240)

    def _toggle_search_dock(self):
        visible = not self._search_dock.isVisible()
        self._search_dock.setVisible(visible)
        self._settings.setValue("window/show_search", visible)
        if visible:
            self._search_input.setFocus()
            self._search_input.selectAll()

    def _toggle_outline_dock(self):
        visible = not self._outline_dock.isVisible()
        self._outline_dock.setVisible(visible)
        self._settings.setValue("window/show_outline", visible)

    def _toggle_thumbs_dock(self):
        visible = not self._thumbs_dock.isVisible()
        self._thumbs_dock.setVisible(visible)
        self._settings.setValue("window/show_thumbnails", visible)

    def _toggle_info_dock(self):
        visible = not self._info_dock.isVisible()
        self._info_dock.setVisible(visible)
        self._settings.setValue("window/show_inspector", visible)

    def _active_search_text(self) -> str:
        if hasattr(self, "_search_input") and self._search_input is not None:
            return self._search_input.text().strip()
        return self._find_input.text().strip() if self._find_input else ""

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
        if geometry:
            self.restoreGeometry(geometry)

        state = self._settings.value("window/state")
        if state:
            self.restoreState(state)
        else:
            self._search_dock.setVisible(self._settings.value("window/show_search", False, type=bool))
            self._outline_dock.setVisible(self._settings.value("window/show_outline", False, type=bool))
            self._thumbs_dock.setVisible(self._settings.value("window/show_thumbnails", False, type=bool))
            self._info_dock.setVisible(self._settings.value("window/show_inspector", True, type=bool))

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
        self._settings.setValue("window/show_search", self._search_dock.isVisible())
        self._settings.setValue("window/show_outline", self._outline_dock.isVisible())
        self._settings.setValue("window/show_thumbnails", self._thumbs_dock.isVisible())
        self._settings.setValue("window/show_inspector", self._info_dock.isVisible())
        self._settings.setValue("view/auto_reload", self._auto_reload_enabled)
        self._settings.setValue("view/tool", self._view.tool.name)

    def _schedule_session_save(self):
        if self._current_file and self._view.document:
            self._session_save_timer.start(300)

    def _save_current_document_session(self):
        if not self._current_file or not self._view.document:
            return

        path = os.path.abspath(self._current_file)
        self._document_sessions[path] = {
            "page": int(self._view.current_page),
            "zoom": float(self._view.zoom),
            "zoom_mode": self._view.zoom_mode,
        }

        while len(self._document_sessions) > 50:
            first_key = next(iter(self._document_sessions))
            del self._document_sessions[first_key]

        self._save_json_setting("documents/session", self._document_sessions)

    def _restore_document_session(self, path: str) -> bool:
        if not path:
            return False
        state = self._document_sessions.get(os.path.abspath(path))
        if not state:
            return False

        try:
            zoom = float(state.get("zoom", 1.0))
            page = int(state.get("page", 0))
        except (TypeError, ValueError):
            return False

        zoom_mode = str(state.get("zoom_mode", PdfView.ZOOM_MODE_CUSTOM))
        if zoom_mode == PdfView.ZOOM_MODE_FIT_WIDTH:
            self._view.fit_width()
        elif zoom_mode == PdfView.ZOOM_MODE_FIT_PAGE:
            self._view.fit_page()
        elif zoom_mode == PdfView.ZOOM_MODE_ACTUAL_SIZE:
            self._view.actual_size()
        else:
            self._view.set_zoom(zoom, immediate=True, zoom_mode=PdfView.ZOOM_MODE_CUSTOM)

        if 0 <= page < self._view.page_count:
            QTimer.singleShot(0, lambda p=page: self._view.go_to_page(p))
        return True

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

    def _refresh_document_info(self):
        doc = self._view.document
        if not doc:
            self._doc_name.setText("No file")
            self._doc_page.setText("0 / 0")
            self._doc_zoom.setText("--")
            self._page_count_lbl.setText("Pages: 0")
            self._outline_list.clear()
            self._thumbs_list.clear()
            self._clear_thumbnail_queue()
            self._update_measurements_panel(None)
            return

        source_path = self._view.doc_path or self._current_file
        name = os.path.basename(source_path) if source_path else "Untitled"
        self._doc_name.setText(name)
        self._doc_page.setText(f"{self._view.current_page + 1} / {doc.page_count}")
        self._doc_zoom.setText(f"{self._view.zoom * 100:.0f}%")
        self._page_count_lbl.setText(f"Pages: {doc.page_count}")
        self._populate_outline()
        self._populate_thumbnails()

    def _populate_outline(self):
        self._outline_list.clear()
        doc = self._view.document
        if not doc:
            return
        toc = doc.get_toc(simple=True)
        for level, title, page in toc:
            indent = "  " * max(0, level - 1)
            item = QListWidgetItem(f"{indent}{title}")
            item.setData(Qt.ItemDataRole.UserRole, page - 1)
            self._outline_list.addItem(item)

    def _populate_thumbnails(self):
        self._clear_thumbnail_queue()
        self._thumbs_list.clear()
        doc = self._view.document
        if not doc:
            return

        source_path = self._view.doc_path or self._current_file
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
        if not self._view.document:
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
        doc = self._view.document
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

        current_idx = self._view.current_page
        self._enqueue_thumbnail(current_idx, front=True)

        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(8)

    def _render_thumbnail_batch(self):
        doc = self._view.document
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

    def _jump_to_outline_item(self, item: QListWidgetItem):
        page_idx = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(page_idx, int):
            self._view.go_to_page(page_idx)

    def _jump_to_thumb(self, item: QListWidgetItem):
        page_idx = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(page_idx, int):
            self._view.go_to_page(page_idx)

    def _on_page_changed(self, current: int, total: int):
        self._doc_page.setText(f"{current} / {total}")
        self._page_count_lbl.setText(f"Pages: {total}")
        if total == self._thumbs_list.count() and total > 0:
            idx = current - 1
            if 0 <= idx < total:
                self._thumbs_list.blockSignals(True)
                self._thumbs_list.setCurrentRow(idx)
                self._thumbs_list.blockSignals(False)
        self._schedule_thumbnail_render()
        if self._search_results:
            self._update_search_highlights()

    def _on_text_info(self, info: str):
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

    def _on_text_selected(self, text: str):
        if text:
            QApplication.clipboard().setText(text)
            self._status.showMessage("Copied text selection", 1500)
        else:
            self._status.showMessage("No text in selection", 1500)

    def _show_find(self):
        self._toggle_search_dock()

    def _clear_search(self):
        self._search_query = ""
        self._search_results = []
        self._search_index = -1
        self._view.set_search_highlights([])
        if hasattr(self, "_search_count_lbl"):
            self._search_count_lbl.setText("")

    def _search(self, query: str):
        if not self._view.document:
            self._clear_search()
            return
        if query == self._search_query:
            return
        self._search_query = query
        self._search_results = []
        self._search_index = -1
        if not query:
            self._view.set_search_highlights([])
            self._search_count_lbl.setText("0/0")
            return
        for i in range(self._view.document.page_count):
            page = self._view.document.load_page(i)
            for r in page.search_for(query):
                self._search_results.append((i, r))

        if not self._search_results:
            self._view.set_search_highlights([])
            self._search_count_lbl.setText("0/0")

    def _update_search_highlights(self):
        if not self._search_results:
            self._view.set_search_highlights([])
            return
        current_page = self._view.current_page
        highlights = []
        for i, (page_idx, rect) in enumerate(self._search_results):
            if i == self._search_index or page_idx == current_page:
                qrect = QRectF(rect.x0, rect.y0, rect.width, rect.height)
                highlights.append((page_idx, qrect, i == self._search_index))
        self._view.set_search_highlights(highlights)

    def _go_to_search_result(self):
        if not self._search_results or self._search_index < 0:
            return
        page_idx, rect = self._search_results[self._search_index]
        self._view.scroll_to_rect(page_idx, rect)
        self._update_search_highlights()
        self._status.showMessage(f"Match {self._search_index + 1}/{len(self._search_results)}", 1500)

    def _find_next(self):
        query = self._active_search_text()
        if not query:
            return
        self._search(query)
        if not self._search_results:
            self._status.showMessage("No matches", 1500)
            self._search_count_lbl.setText("0/0")
            return
        self._search_index = (self._search_index + 1) % len(self._search_results)
        self._go_to_search_result()
        self._search_count_lbl.setText(f"{self._search_index + 1}/{len(self._search_results)}")

    def _find_prev(self):
        query = self._active_search_text()
        if not query:
            return
        self._search(query)
        if not self._search_results:
            self._status.showMessage("No matches", 1500)
            self._search_count_lbl.setText("0/0")
            return
        self._search_index = (self._search_index - 1) % len(self._search_results)
        self._go_to_search_result()
        self._search_count_lbl.setText(f"{self._search_index + 1}/{len(self._search_results)}")

    def _update_status(self):
        if self._view.document:
            name = os.path.basename(self._current_file) if self._current_file else "Untitled"
            zoom_text = f"{self._view.zoom * 100:.0f}%"

            self._status_dot.setProperty("offline", False)
            self._status_dot.style().unpolish(self._status_dot)
            self._status_dot.style().polish(self._status_dot)

            self._file_lbl.setText(name)
            self._zoom_lbl.setText(zoom_text)
            self._doc_name.setText(name)
            self._doc_zoom.setText(zoom_text)
            self._doc_page.setText(f"{self._view.current_page + 1} / {self._view.page_count}")
            self._page_count_lbl.setText(f"Pages: {self._view.page_count}")

            self._sync_zoom_combo()
            self._update_measurements_panel(self._view.selection_rect)
        else:
            self._status_dot.setProperty("offline", True)
            self._status_dot.style().unpolish(self._status_dot)
            self._status_dot.style().polish(self._status_dot)

            self._file_lbl.setText("No file")
            self._page_count_lbl.setText("Pages: 0")
            self._zoom_lbl.setText("--")
            self._doc_name.setText("No file")
            self._doc_page.setText("0 / 0")
            self._doc_zoom.setText("--")
            self._sync_zoom_combo()
            self._update_measurements_panel(None)

        if self._toolbar_select_action:
            self._toolbar_select_action.setChecked(self._view.tool == ToolMode.SELECT)
        if hasattr(self, "_panel_select_btn"):
            self._panel_select_btn.setChecked(self._view.tool == ToolMode.SELECT)
            self._panel_hand_btn.setChecked(self._view.tool == ToolMode.HAND)
            self._panel_measure_btn.setChecked(self._view.tool == ToolMode.MEASURE)

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf);;All (*)")
        if path:
            self._open_file(path)

    def _open_file(self, path: str):
        self._save_current_document_session()
        self._stop_watch()

        if self._view.open_document(path):
            self._current_file = os.path.abspath(path)
            self._add_recent_file(self._current_file)
            self._clear_search()
            self.setWindowTitle(f"{APP_NAME} - {os.path.basename(path)}")
            if not self._restore_document_session(self._current_file):
                self._view.fit_width()
            self._update_status()
            self._update_mtime()
            self._start_watch()
            self._schedule_session_save()

    def _stop_watch(self):
        if self._current_file:
            for f in self._watcher.files():
                self._watcher.removePath(f)
            for d in self._watcher.directories():
                self._watcher.removePath(d)

    def _start_watch(self):
        if self._current_file and self._auto_reload_enabled:
            self._watcher.addPath(self._current_file)
            self._watcher.addPath(os.path.dirname(self._current_file))

    def _update_mtime(self):
        try:
            if self._current_file and os.path.exists(self._current_file):
                self._last_mtime = os.path.getmtime(self._current_file)
        except OSError:
            pass

    def _on_change(self, _path: str):
        if not self._auto_reload_enabled:
            return
        self._reload_timer.start(200)

    def _poll_check(self):
        if not self._auto_reload_enabled or not self._current_file:
            return
        try:
            if os.path.exists(self._current_file):
                mtime = os.path.getmtime(self._current_file)
                if mtime != self._last_mtime:
                    self._reload_timer.start(200)
        except OSError:
            pass

    def _do_reload(self):
        if not self._current_file or not os.path.exists(self._current_file):
            return
        try:
            size = os.path.getsize(self._current_file)
            if size == 0:
                return
        except OSError:
            return

        if self._view.reload_document():
            self._update_mtime()
            self._status.showMessage("Reloaded", 1000)
            if self._auto_reload_enabled and self._current_file not in self._watcher.files():
                self._watcher.addPath(self._current_file)

    def _force_reload(self):
        self._do_reload()

    def _copy(self):
        sel = self._view.selection_rect
        if not sel:
            self._status.showMessage("No selection", 2000)
            return
        QApplication.clipboard().setText(format_size(sel.width(), sel.height()))
        self._status.showMessage("Copied", 1500)

    def _export(self):
        sel = self._view.selection_rect
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
            page_idx = self._view.selection_page
            if page_idx < 0:
                return
            page = self._view.document.load_page(page_idx)
            clip = fitz.Rect(sel.x(), sel.y(), sel.right(), sel.bottom())
            scale = dlg.selected_dpi / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
            pix.save(path)
            self._status.showMessage(f"Saved {os.path.basename(path)}", 2000)
        except Exception as exc:
            QMessageBox.critical(self, "Error", str(exc))

    def _set_tool(self, tool: ToolMode):
        self._view.tool = tool
        self._select_action.setChecked(tool == ToolMode.SELECT)
        self._hand_action.setChecked(tool == ToolMode.HAND)
        self._measure_action.setChecked(tool == ToolMode.MEASURE)
        if self._toolbar_select_action:
            self._toolbar_select_action.setChecked(tool == ToolMode.SELECT)
        if hasattr(self, "_panel_select_btn"):
            self._panel_select_btn.setChecked(tool == ToolMode.SELECT)
            self._panel_hand_btn.setChecked(tool == ToolMode.HAND)
            self._panel_measure_btn.setChecked(tool == ToolMode.MEASURE)
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
        self._view.set_zoom(value / 100.0, immediate=True, zoom_mode=PdfView.ZOOM_MODE_CUSTOM)

    def _sync_zoom_combo(self):
        if not hasattr(self, "_zoom_combo"):
            return
        self._zoom_combo_updating = True
        self._zoom_combo.setCurrentText(f"{self._view.zoom * 100:.0f}%" if self._view.document else "100%")
        self._zoom_combo_updating = False

    def _toggle_auto_reload(self, enabled: bool):
        self._auto_reload_enabled = bool(enabled)
        self._settings.setValue("view/auto_reload", self._auto_reload_enabled)
        if self._auto_reload_enabled:
            self._start_watch()
        else:
            self._stop_watch()

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
        row.addWidget(key)
        row.addStretch()
        row.addWidget(val)
        parent_layout.addLayout(row)
        return val

    def closeEvent(self, e):
        self._session_save_timer.stop()
        self._save_current_document_session()
        self._save_persistent_ui()
        self._view.close_document()
        super().closeEvent(e)
