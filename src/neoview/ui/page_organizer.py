"""Modal page organizer with an isolated edit session and explicit saves."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from neoview.models.page_organization import PageOrganization


def paths_alias(first: str, second: str) -> bool:
    if os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second)):
        return True
    try:
        return os.path.samefile(first, second)
    except FileNotFoundError:
        return False


class PageOrganizer(QDialog):
    def __init__(self, session: PageOrganization, path: str, parent=None):
        super().__init__(parent)
        self.session = session
        self.save_document = session.save
        self.path = path
        self._source_signature = self._signature(path)
        self.saved_path = None
        self.setWindowTitle("Organize Pages")
        self.resize(700, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Select pages to move or delete. Drag to reorder. Changes apply only when saved."
        ))
        self.pages = QListWidget()
        self.pages.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.pages.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.pages.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.pages.setIconSize(QSize(80, 110))
        self.pages.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pages.customContextMenuRequested.connect(self._context_menu)
        self.pages.model().rowsMoved.connect(self._reordered)
        layout.addWidget(self.pages)
        controls = QHBoxLayout()
        for label, callback in (
            ("Insert PDF Before...", lambda: self._insert(False)),
            ("Append PDF...", lambda: self._insert(True)),
            ("Move Up", lambda: self._move(-1)),
            ("Move Down", lambda: self._move(1)),
            ("Delete", self._delete),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        buttons = QHBoxLayout()
        buttons.addStretch()
        for label, callback in (
            ("Save", lambda: self._save(False)),
            ("Save As...", lambda: self._save(True)),
            ("Close", self.reject),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._thumbnail_timer = QTimer(self)
        self._thumbnail_timer.timeout.connect(self._render_thumbnail)
        self.finished.connect(self._thumbnail_timer.stop)
        self._refresh()

    def _refresh(self, selected=()):
        self.pages.clear()
        for row, page in enumerate(self.session.order):
            item = QListWidgetItem(f"Page {row + 1}")
            item.setData(Qt.ItemDataRole.UserRole, page)
            self.pages.addItem(item)
            item.setSelected(row in selected)
        self._thumbnail_row = 0
        self._thumbnail_timer.start(0)

    def _render_thumbnail(self):
        if self.session.document.is_closed or self._thumbnail_row >= self.pages.count():
            self._thumbnail_timer.stop()
            return
        item = self.pages.item(self._thumbnail_row)
        page = self.session.document[item.data(Qt.ItemDataRole.UserRole)]
        import fitz
        scale = min(80 / page.rect.width, 110 / page.rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride,
                       QImage.Format.Format_RGB888).copy()
        thumbnail = QPixmap.fromImage(image)
        painter = QPainter(thumbnail)
        painter.setPen(QColor("#a0a0a0"))
        painter.drawRect(0, 0, thumbnail.width() - 1, thumbnail.height() - 1)
        painter.end()
        item.setIcon(QIcon(thumbnail))
        self._thumbnail_row += 1

    def _rows(self):
        return sorted(self.pages.row(item) for item in self.pages.selectedItems())

    def _reordered(self, *_):
        self.session.reorder([
            self.pages.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.pages.count())
        ])
        for row in range(self.pages.count()):
            self.pages.item(row).setText(f"Page {row + 1}")

    def _move(self, step):
        rows = self._rows()
        if not rows or rows[0] + step < 0 or rows[-1] + step >= self.pages.count():
            return
        order = self.session.order.copy()
        for row in rows if step < 0 else reversed(rows):
            order[row], order[row + step] = order[row + step], order[row]
        self.session.reorder(order)
        self._refresh([row + step for row in rows])

    def _delete(self):
        rows = self._rows()
        if not rows:
            return
        try:
            self.session.delete(rows)
            self._refresh([min(rows[0], len(self.session.order) - 1)])
        except ValueError as exc:
            QMessageBox.warning(self, "Cannot Delete Pages", str(exc))

    def _insert(self, append):
        path, _ = QFileDialog.getOpenFileName(self, "Merge PDF", "", "PDF (*.pdf)")
        if not path:
            return
        before = len(self.session.order) if append else max(0, self.pages.currentRow())
        try:
            self.session.insert(path, before)
            self._refresh([before])
        except Exception as exc:
            QMessageBox.warning(self, "Could Not Merge PDF", str(exc))

    def _context_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Move Up", lambda: self._move(-1))
        menu.addAction("Move Down", lambda: self._move(1))
        menu.addAction("Delete Pages", self._delete)
        menu.exec(self.pages.viewport().mapToGlobal(pos))

    @staticmethod
    def _signature(path):
        try:
            stat = os.stat(path)
            return stat.st_mtime_ns, stat.st_size, stat.st_ino
        except OSError:
            return None

    def _save(self, save_as):
        path = self.path
        if save_as:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Organized PDF", str(Path(path).with_stem(Path(path).stem + "-organized")),
                "PDF (*.pdf)",
            )
            if not path:
                return
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
        elif QMessageBox.question(
            self, "Save Pages", "Replace the original PDF with the organized pages?"
        ) != QMessageBox.StandardButton.Yes:
            return
        if (paths_alias(path, self.path)
                and self._signature(self.path) != self._source_signature):
            QMessageBox.warning(
                self, "PDF Changed", "The original PDF changed while organizing pages. "
                "Use Save As to keep your changes in a separate file."
            )
            return
        try:
            from neoview.persistence.sidecar_store import sidecar_path_for

            if (paths_alias(path, sidecar_path_for(self.path))
                    or paths_alias(sidecar_path_for(path), self.path)
                    or paths_alias(path, sidecar_path_for(path))):
                raise ValueError("The PDF and sidecars must be separate files.")
            self.save_document(path)
        except Exception as exc:
            QMessageBox.warning(self, "Could Not Save PDF", str(exc))
            return
        self.saved_path = path
        self.accept()

    def reject(self):
        if self.session.dirty and QMessageBox.question(
            self, "Unsaved Page Changes", "Discard the unsaved page changes?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) != QMessageBox.StandardButton.Discard:
            return
        super().reject()
