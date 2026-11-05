"""Copy-only editing of existing PDF structure and whole-page artifacts."""
from __future__ import annotations

import copy

import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from neoview.models.tagged_pdf import inspect_tagged_pdf
from neoview.ui.tool_support import choose_file, save_copy


class TaggedPdfEditorDialog(QDialog):
    """Own a working PDF snapshot; changes reach disk only through Save Copy."""

    HISTORY_BYTES = 64 * 1024 * 1024
    HISTORY_COUNT = 20

    def __init__(self, document, state, source, parent=None):
        if not document.is_pdf or len(document) == 0:
            raise ValueError("Open a nonempty PDF first.")
        if (document.needs_pass or document.is_encrypted
                or (document.metadata or {}).get("encryption")):
            raise ValueError("Tag editing is unavailable for password-protected PDFs.")
        if document.get_sigflags() > 0 or self._has_signature_widget(document):
            raise ValueError("Tag editing is unavailable for PDFs with signature fields.")
        super().__init__(parent)
        self.document = fitz.open(stream=document.tobytes(), filetype="pdf")
        self.source = source
        self.state = copy.deepcopy(state)
        self.saved_path = None
        self._dirty = False
        self._fields_dirty = False
        self._loading = False
        self._undo = []
        self._redo = []
        self._selected_xref = None
        self.setWindowTitle("Edit PDF Tags and Artifacts - Save a Copy")
        self.resize(880, 680)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Edit existing tags and sibling order in a working copy. Apply tag fields before "
            "selecting another tag. Whole-page artifact marking is limited to safe untagged "
            "pages; it marks all page content as decorative. These tools do not certify PDF/UA."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.tags = QTreeWidget()
        self.tags.setHeaderLabels(["Tag", "Page", "Object"])
        self.tags.setObjectName("editable_pdf_tags")
        self.tags.setAccessibleName("Existing PDF tags to edit")
        self.tags.currentItemChanged.connect(self._tag_selected)
        layout.addWidget(self.tags)
        form = QFormLayout()
        self.fields = {}
        for key, label in (("role", "Role"), ("title", "Title"), ("alt_text", "Alternate text"),
                           ("actual_text", "Actual text"), ("language", "Language")):
            field = QLineEdit()
            field.setObjectName(f"tag_{key}")
            field.textEdited.connect(self._field_edited)
            self.fields[key] = field
            form.addRow(label, field)
        layout.addLayout(form)
        actions = QHBoxLayout()
        self.apply_button = QPushButton("Apply Tag Fields")
        self.apply_button.clicked.connect(self._apply_tag)
        actions.addWidget(self.apply_button)
        self.move_up_button = QPushButton("Move Tag Up")
        self.move_up_button.clicked.connect(lambda: self._move(-1))
        actions.addWidget(self.move_up_button)
        self.move_down_button = QPushButton("Move Tag Down")
        self.move_down_button.clicked.connect(lambda: self._move(1))
        actions.addWidget(self.move_down_button)
        layout.addLayout(actions)
        artifacts = QHBoxLayout()
        artifacts.addWidget(QLabel("Whole page:"))
        self.page = QSpinBox()
        self.page.setRange(1, len(self.document))
        self.page.setAccessibleName("Page for artifact marking")
        artifacts.addWidget(self.page)
        self.mark_button = QPushButton("Mark Entire Page as Artifact...")
        self.mark_button.clicked.connect(self._mark_artifact)
        artifacts.addWidget(self.mark_button)
        self.unmark_button = QPushButton("Undo NeoView Page Artifact Marking")
        self.unmark_button.clicked.connect(self._unmark_artifact)
        artifacts.addWidget(self.unmark_button)
        layout.addLayout(artifacts)
        history = QHBoxLayout()
        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self._undo_change)
        self.redo_button = QPushButton("Redo")
        self.redo_button.clicked.connect(self._redo_change)
        history.addWidget(self.undo_button)
        history.addWidget(self.redo_button)
        history.addStretch()
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        history.addWidget(self.status)
        layout.addLayout(history)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Save PDF Copy...")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._refresh()

    @staticmethod
    def _has_signature_widget(document):
        # Some producers omit /SigFlags even when a signature widget exists.
        if document.xref_get_key(document.pdf_catalog(), "AcroForm")[0] == "null":
            return False
        if len(document) > 2000:
            raise ValueError("Form-bearing PDFs over 2000 pages exceed the signature inspection limit.")
        return any(widget.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE
                   for page in document for widget in (page.widgets() or []))

    def _resolve_pending(self):
        if not self._fields_dirty:
            return True
        answer = QMessageBox.question(
            self, "Unapplied Tag Fields", "Apply edited tag fields before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._apply_tag()
        if answer == QMessageBox.StandardButton.Discard:
            self._load_fields(self.tags.currentItem())
            return True
        return False

    def _field_edited(self, _text):
        if not self._loading:
            self._fields_dirty = True

    def _refresh(self, selected=None):
        self._loading = True
        # Editing only needs the structure tree. Artifact content scans belong to
        # the asynchronous inspector; never rescan page drawing streams here.
        self.report = inspect_tagged_pdf(self.document, max_nodes=2000, scan_artifacts=False)
        self.tags.clear()
        self._nodes = {node.xref: node for node in self.report.reading_order if node.xref}
        selected_item = None

        def add(parent, node):
            nonlocal selected_item
            item = QTreeWidgetItem(parent, [node.role,
                str(node.page + 1) if node.page is not None else "", str(node.xref or "direct")])
            item.setData(0, Qt.ItemDataRole.UserRole, node.xref)
            if node.xref == selected:
                selected_item = item
            for child in node.children:
                add(item, child)

        for node in self.report.nodes:
            add(self.tags, node)
        self.tags.expandToDepth(1)
        if selected_item is not None:
            self.tags.setCurrentItem(selected_item)
        elif self.tags.topLevelItemCount():
            self.tags.setCurrentItem(self.tags.topLevelItem(0))
        self._loading = False
        self._fields_dirty = False
        self._load_fields(self.tags.currentItem())
        self.undo_button.setEnabled(bool(self._undo))
        self.redo_button.setEnabled(bool(self._redo))
        self.status.setText("Working copy modified" if self._dirty else "Source PDF unchanged")

    def _tag_selected(self, current, previous):
        if self._loading:
            return
        if self._fields_dirty and QMessageBox.question(
            self, "Unapplied Tag Fields", "Discard unapplied tag fields?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            self._loading = True
            self.tags.setCurrentItem(previous)
            self._loading = False
            return
        self._load_fields(current)

    def _load_fields(self, item):
        xref = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        node = self._nodes.get(xref)
        self._selected_xref = xref if node else None
        self._loading = True
        for key, field in self.fields.items():
            field.setText(getattr(node, key) if node else "")
            field.setEnabled(node is not None)
        self._loading = False
        self._fields_dirty = False
        for button in (self.apply_button, self.move_up_button, self.move_down_button):
            button.setEnabled(node is not None)

    def _restore(self, data):
        replacement = fitz.open(stream=data, filetype="pdf")
        self.document.close()
        self.document = replacement

    def _trim_history(self):
        while (len(self._undo) + len(self._redo) > self.HISTORY_COUNT
               or sum(map(len, self._undo + self._redo)) > self.HISTORY_BYTES):
            if self._undo:
                self._undo.pop(0)
            elif self._redo:
                self._redo.pop(0)

    def _mutate(self, operation):
        before = self.document.tobytes()
        if len(before) > self.HISTORY_BYTES:
            QMessageBox.warning(self, "Edit Limit", "This PDF exceeds the safe undo snapshot limit.")
            return False
        try:
            result = operation()
        except Exception as exc:
            self._restore(before)
            QMessageBox.warning(self, "Cannot Edit PDF", str(exc))
            return False
        if result is False:
            return True
        self._undo.append(before)
        self._redo.clear()
        self._trim_history()
        self._dirty = True
        self._refresh(self._selected_xref)
        return True

    def _apply_tag(self):
        from neoview.models.tagged_pdf_editing import edit_tag
        if self._selected_xref is None:
            return True
        node = self._nodes[self._selected_xref]
        values = {key: field.text() for key, field in self.fields.items()
                  if field.text() != getattr(node, key)}
        if not values:
            self._fields_dirty = False
            return True
        return self._mutate(lambda: edit_tag(self.document, self._selected_xref, **values))

    def _move(self, direction):
        from neoview.models.tagged_pdf_editing import move_tag
        if not self._resolve_pending():
            return
        if self._selected_xref is not None:
            self._mutate(lambda: move_tag(self.document, self._selected_xref, direction))

    def _mark_artifact(self):
        from neoview.models.tagged_pdf_content import mark_page_as_artifact
        if not self._resolve_pending():
            return
        if QMessageBox.question(
            self, "Mark Entire Page as Artifact?",
            "This marks ALL content on the selected page as decorative. Do this only when "
            "the entire page should be excluded from meaningful reading content. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            self._mutate(lambda: mark_page_as_artifact(self.document, self.page.value() - 1))

    def _unmark_artifact(self):
        from neoview.models.tagged_pdf_content import unmark_page_artifact
        if not self._resolve_pending():
            return
        self._mutate(lambda: unmark_page_artifact(self.document, self.page.value() - 1))

    def _undo_change(self):
        if not self._resolve_pending():
            return
        if self._undo:
            self._redo.append(self.document.tobytes())
            self._restore(self._undo.pop())
            self._dirty = True
            self._trim_history()
            self._refresh(self._selected_xref)

    def _redo_change(self):
        if not self._resolve_pending():
            return
        if self._redo:
            self._undo.append(self.document.tobytes())
            self._restore(self._redo.pop())
            self._dirty = True
            self._trim_history()
            self._refresh(self._selected_xref)

    def _save(self):
        if self._fields_dirty and not self._apply_tag():
            return
        try:
            target = choose_file(self, self.source, "-tagged", ".pdf", "Save Tagged PDF Copy")
            if not target:
                return
            self.saved_path = save_copy(self.document, self.state, self.source, target)
        except Exception as exc:
            QMessageBox.warning(self, "Cannot Save PDF Copy", str(exc))
            return
        self._dirty = False
        self.accept()

    def reject(self):
        if self.document.is_closed:
            super().reject()
            return
        if (self._dirty or self._fields_dirty) and QMessageBox.question(
            self, "Discard PDF Changes?", "Discard the unsaved working copy?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self._dirty = False
        self._fields_dirty = False
        super().reject()

    def done(self, result):
        if not self.document.is_closed:
            self.document.close()
        super().done(result)
