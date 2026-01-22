"""Main application window."""

from __future__ import annotations

import os
from typing import Optional, List

import fitz
from PySide6.QtCore import QTimer, QFileSystemWatcher, QRectF
from PySide6.QtGui import QAction, QKeySequence, QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QFileDialog,
    QStatusBar,
    QToolBar,
    QLabel,
    QMessageBox,
    QDialog,
    QLineEdit,
)

from neoview.resources import load_app_icon
from neoview.ui.pdf_view import PdfView, ToolMode
from neoview.ui.dialogs import ExportDialog, FindDialog
from neoview.utils.units import format_size


APP_NAME = "NeoView"


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

        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_change)
        self._watcher.directoryChanged.connect(self._on_change)

        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self._do_reload)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_check)
        self._poll_timer.start(500)

        self._setup_ui()

        if pdf_path:
            self._open_file(pdf_path)

    def _setup_ui(self):
        self._view = PdfView(self)
        self.setCentralWidget(self._view)

        self._view.selection_changed.connect(self._update_status)
        self._view.zoom_changed.connect(self._update_status)
        self._view.page_changed.connect(self._on_page_changed)
        self._view.text_info_changed.connect(self._on_text_info)
        self._view.text_selected.connect(self._on_text_selected)

        self._setup_menus()
        self._setup_toolbar()
        self._setup_statusbar()

    def _setup_menus(self):
        file_m = self.menuBar().addMenu("&File")
        file_m.addAction(self._action("&Open...", self._open_dialog, QKeySequence.StandardKey.Open))
        file_m.addAction(self._action("&Reload", self._force_reload, "F5"))
        file_m.addSeparator()
        file_m.addAction(self._action("&Export Selection...", self._export, QKeySequence.StandardKey.Save))
        file_m.addSeparator()
        file_m.addAction(self._action("E&xit", self.close, QKeySequence.StandardKey.Quit))

        edit_m = self.menuBar().addMenu("&Edit")
        edit_m.addAction(self._action("&Copy Measurements", self._copy, QKeySequence.StandardKey.Copy))
        edit_m.addAction(self._action("&Find...", self._show_find, QKeySequence.StandardKey.Find))
        edit_m.addAction(self._action("C&lear Selection", self._view.clear_all_selection, "Escape"))

        view_m = self.menuBar().addMenu("&View")
        view_m.addAction(self._action("Zoom &In", lambda: self._view.zoom_by(1.25), QKeySequence.StandardKey.ZoomIn))
        view_m.addAction(self._action("Zoom &Out", lambda: self._view.zoom_by(0.8), QKeySequence.StandardKey.ZoomOut))
        view_m.addSeparator()
        view_m.addAction(self._action("Fit &Width", self._view.fit_width, "W"))
        view_m.addAction(self._action("Fit &Page", self._view.fit_page, "F"))

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

    def _setup_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addAction(self._action("Open", self._open_dialog))
        tb.addSeparator()

        tb.addAction(self._action("Prev", self._view.prev_page))
        tb.addAction(self._action("Next", self._view.next_page))
        tb.addSeparator()

        tb.addAction(self._action("Zoom -", lambda: self._view.zoom_by(0.8)))
        tb.addAction(self._action("Zoom +", lambda: self._view.zoom_by(1.25)))
        tb.addAction(self._action("Fit", self._view.fit_width))
        tb.addSeparator()

        self._select_btn = self._action("Select", lambda: self._set_tool(ToolMode.SELECT))
        self._select_btn.setCheckable(True)
        tb.addAction(self._select_btn)

        self._hand_btn = self._action("Hand", lambda: self._set_tool(ToolMode.HAND))
        self._hand_btn.setCheckable(True)
        self._hand_btn.setChecked(True)
        tb.addAction(self._hand_btn)

        self._measure_btn = self._action("Measure", lambda: self._set_tool(ToolMode.MEASURE))
        self._measure_btn.setCheckable(True)
        tb.addAction(self._measure_btn)

        tb.addSeparator()
        tb.addAction(self._action("Copy", self._copy))
        tb.addAction(self._action("Export", self._export))

    def _action(self, text: str, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        return action

    def _set_tool(self, tool: ToolMode):
        self._view.tool = tool
        self._select_btn.setChecked(tool == ToolMode.SELECT)
        self._hand_btn.setChecked(tool == ToolMode.HAND)
        self._measure_btn.setChecked(tool == ToolMode.MEASURE)
        self._select_action.setChecked(tool == ToolMode.SELECT)
        self._hand_action.setChecked(tool == ToolMode.HAND)
        self._measure_action.setChecked(tool == ToolMode.MEASURE)
        self._update_status()

    def _setup_statusbar(self):
        self._status = QStatusBar()
        self.setStatusBar(self._status)

        self._file_lbl = QLabel("No file")
        self._page_lbl = QLabel("")
        self._zoom_lbl = QLabel("")
        self._tool_lbl = QLabel("")
        self._font_lbl = QLabel("")
        self._size_lbl = QLabel("")

        self._status.addWidget(self._file_lbl)
        self._status.addWidget(self._page_lbl)
        self._status.addWidget(self._zoom_lbl)
        self._status.addWidget(self._tool_lbl)
        self._status.addWidget(self._font_lbl)
        self._status.addPermanentWidget(self._size_lbl)

    def _on_page_changed(self, current: int, total: int):
        self._page_lbl.setText(f"Page {current}/{total}")
        if self._search_results:
            self._update_search_highlights()

    def _on_text_info(self, info: str):
        if info:
            self._font_lbl.setText(f"Font: {info}")
        else:
            self._font_lbl.setText("")

    def _on_text_selected(self, text: str):
        if text:
            QApplication.clipboard().setText(text)
            self._status.showMessage("Copied text selection", 1500)
        else:
            self._status.showMessage("No text in selection", 1500)

    def _show_find(self):
        if not self._find_dlg:
            dlg = FindDialog(self)
            dlg.prev_btn.clicked.connect(self._find_prev)
            dlg.next_btn.clicked.connect(self._find_next)
            dlg.input.returnPressed.connect(self._find_next)
            self._find_dlg = dlg
            self._find_input = dlg.input
        self._find_dlg.show()
        self._find_dlg.raise_()
        self._find_input.setFocus()
        self._find_input.selectAll()

    def _clear_search(self):
        self._search_query = ""
        self._search_results = []
        self._search_index = -1
        self._view.set_search_highlights([])

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
            return
        for i in range(self._view.document.page_count):
            page = self._view.document.load_page(i)
            for r in page.search_for(query):
                self._search_results.append((i, r))

        if not self._search_results:
            self._view.set_search_highlights([])

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
        query = self._find_input.text().strip() if self._find_input else ""
        if not query:
            return
        self._search(query)
        if not self._search_results:
            self._status.showMessage("No matches", 1500)
            return
        self._search_index = (self._search_index + 1) % len(self._search_results)
        self._go_to_search_result()

    def _find_prev(self):
        query = self._find_input.text().strip() if self._find_input else ""
        if not query:
            return
        self._search(query)
        if not self._search_results:
            self._status.showMessage("No matches", 1500)
            return
        self._search_index = (self._search_index - 1) % len(self._search_results)
        self._go_to_search_result()

    def _update_status(self):
        if self._view.document:
            name = os.path.basename(self._current_file) if self._current_file else "Untitled"
            self._file_lbl.setText(f"{name}")
            self._zoom_lbl.setText(f"{self._view.zoom * 100:.0f}%")

            tool_names = {ToolMode.SELECT: "Select", ToolMode.HAND: "Hand", ToolMode.MEASURE: "Measure"}
            self._tool_lbl.setText(tool_names[self._view.tool])

            sel = self._view.selection_rect
            if sel:
                self._size_lbl.setText(format_size(sel.width(), sel.height()))
            else:
                self._size_lbl.setText("")
        else:
            self._file_lbl.setText("No file")
            self._page_lbl.setText("")
            self._zoom_lbl.setText("")
            self._tool_lbl.setText("")
            self._size_lbl.setText("")

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF (*.pdf);;All (*)")
        if path:
            self._open_file(path)

    def _open_file(self, path: str):
        self._stop_watch()

        if self._view.open_document(path):
            self._current_file = os.path.abspath(path)
            self._clear_search()
            self.setWindowTitle(f"{APP_NAME} — {os.path.basename(path)}")
            self._view.fit_width()
            self._update_status()
            self._update_mtime()
            self._start_watch()

    def _stop_watch(self):
        if self._current_file:
            for f in self._watcher.files():
                self._watcher.removePath(f)
            for d in self._watcher.directories():
                self._watcher.removePath(d)

    def _start_watch(self):
        if self._current_file:
            self._watcher.addPath(self._current_file)
            self._watcher.addPath(os.path.dirname(self._current_file))

    def _update_mtime(self):
        try:
            if self._current_file and os.path.exists(self._current_file):
                self._last_mtime = os.path.getmtime(self._current_file)
        except OSError:
            pass

    def _on_change(self, _path: str):
        self._reload_timer.start(200)

    def _poll_check(self):
        if not self._current_file:
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
            if self._current_file not in self._watcher.files():
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

    def closeEvent(self, e):
        self._view.close_document()
        super().closeEvent(e)
