"""Persistent, document-aware Tags sidebar using isolated inspection snapshots."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from neoview.ui.background_tagged_inspection import TaggedInspectionJob

_PAGE = Qt.ItemDataRole.UserRole
_DETAILS = Qt.ItemDataRole.UserRole + 1


class TaggedPdfPanel(QWidget):
    """Show declared tags beside the PDF without retaining a worker document."""

    page_requested = Signal(int)
    inspect_requested = Signal()
    edit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TaggedPdfPanel")
        self._document = None
        self._source_signature = None
        self._password = None
        self._document_id = None
        self._generation = 0
        self._job = None
        self._page_count = 0
        self.report = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        self.mode = QComboBox()
        self.mode.addItems(["Tags", "Reading Order", "Checks and Artifacts"])
        self.mode.setAccessibleName("Tags panel view")
        self.mode.currentIndexChanged.connect(self._populate)
        layout.addWidget(self.mode)
        tools = QHBoxLayout()
        self.refresh_button = QToolButton()
        self.refresh_button.setText("Refresh")
        self.refresh_button.setAccessibleName("Refresh PDF tags")
        self.refresh_button.clicked.connect(self.refresh)
        tools.addWidget(self.refresh_button)
        self.expand_button = QToolButton()
        self.expand_button.setText("+")
        self.expand_button.setToolTip("Expand all tags")
        self.expand_button.setAccessibleName("Expand all tags")
        self.expand_button.clicked.connect(lambda: self.tree.expandAll())
        tools.addWidget(self.expand_button)
        self.collapse_button = QToolButton()
        self.collapse_button.setText("-")
        self.collapse_button.setToolTip("Collapse all tags")
        self.collapse_button.setAccessibleName("Collapse all tags")
        self.collapse_button.clicked.connect(lambda: self.tree.collapseAll())
        tools.addWidget(self.collapse_button)
        tools.addStretch()
        layout.addLayout(tools)
        self.status = QLabel("Open a PDF to inspect its tags.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tree = QTreeWidget()
        self.tree.setObjectName("sidebar_pdf_tags")
        self.tree.setAccessibleName("PDF structure tags and reading order")
        self.tree.setHeaderLabels(["Tag", "Page"])
        self.tree.setUniformRowHeights(True)
        self.tree.setColumnWidth(0, 155)
        self.tree.currentItemChanged.connect(self._selected)
        layout.addWidget(self.tree, 1)
        self.details = QPlainTextEdit()
        self.details.setObjectName("sidebar_pdf_tag_properties")
        self.details.setAccessibleName("Selected PDF tag properties")
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(180)
        self.details.setPlaceholderText("Select a tag to inspect its properties.")
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.inspect_button = QPushButton("Inspector...")
        self.inspect_button.setToolTip("Open detailed tagged PDF inspection and report export")
        self.inspect_button.clicked.connect(self.inspect_requested)
        self.edit_button = QPushButton("Edit Copy...")
        self.edit_button.setToolTip("Edit PDF tags in a separate copy")
        self.edit_button.clicked.connect(self.edit_requested)
        actions.addWidget(self.inspect_button)
        actions.addWidget(self.edit_button)
        layout.addLayout(actions)
        note = QLabel("Declared structure order; manual accessibility review is still required.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._enable(False)

    @property
    def document(self):
        """Current main-thread document, released when the panel is cleared."""
        return self._document

    def set_document(self, document, *, source_signature=None, password=None):
        if document is self.document and (document is not None or self._document_id is None):
            return
        self._invalidate()
        self._document = document
        self._source_signature = source_signature if document is not None else None
        self._password = password if document is not None else None
        self._document_id = id(document) if document is not None else None
        self._page_count = len(document) if document is not None else 0
        self._clear()
        if document is None:
            self.status.setText("Open a PDF to inspect its tags.")
            return
        self._start(document)

    def refresh(self):
        document = self.document
        if document is None or document.is_closed:
            self.set_document(None)
            return
        self._invalidate()
        self._clear()
        self._start(document)

    def _invalidate(self):
        self._generation += 1
        job, self._job = self._job, None
        if job is not None and not job.done:
            job.cancel()

    def _clear(self):
        self.report = None
        self.tree.clear()
        self.details.clear()
        self._enable(False)

    def _enable(self, ready):
        has_document = self.document is not None
        self.refresh_button.setEnabled(has_document)
        for widget in (self.mode, self.tree, self.expand_button, self.collapse_button,
                       self.inspect_button, self.edit_button):
            widget.setEnabled(ready)

    def _start(self, document):
        self.status.setText("Loading tags and artifacts...")
        generation = self._generation
        try:
            job = TaggedInspectionJob(document, self, from_source=True,
                                      source_signature=self._source_signature, password=self._password)
            self._job = job
            job.ready.connect(lambda report: self._ready(generation, report))
            job.failed.connect(lambda error: self._failed(generation, error))
            job.start()
        except Exception as error:
            self._failed(generation, str(error))

    def _ready(self, generation, report):
        if generation != self._generation or self.document is None:
            return
        self.report = report
        self._job = None
        self._enable(True)
        summary = (
            f"{len(report.reading_order)} tags | Language: {report.language or 'not specified'}"
            if report.nodes else "No structure tags found. This PDF may be untagged."
        )
        if report.warnings:
            count = len(report.warnings)
            summary += f" | {count} finding{'s' if count != 1 else ''}: see Checks"
        if any(any(word in warning.lower() for word in ("incomplete", "partial", "limit", "cancel"))
               for warning in report.warnings):
            summary += " | Partial inspection"
        self.status.setText(summary)
        self._populate()

    def _failed(self, generation, error):
        if generation != self._generation or self.document is None:
            return
        self._job = None
        self.status.setText("Tag inspection failed: " + error)
        self._enable(False)

    @staticmethod
    def _node_details(node):
        values = [f"Role: {node.role or '(unspecified)'}"]
        if node.mapped_role and node.mapped_role != node.role:
            values.append(f"Mapped role: {node.mapped_role}")
        for label, value in (("Title", node.title), ("Alternate text", node.alt_text),
                             ("Actual text", node.actual_text), ("Language", node.language)):
            if value:
                values.append(f"{label}: {value}")
        values.append("MCIDs: " + (", ".join(map(str, node.mcids)) or "None declared"))
        values.append(f"Structure object: {node.xref or 'direct dictionary'}")
        return "\n".join(values)

    def _item(self, parent, title, page=None, details=""):
        item = QTreeWidgetItem(parent, [title, str(page + 1) if page is not None else ""])
        item.setToolTip(0, title)
        item.setData(0, _DETAILS, details)
        if isinstance(page, int) and 0 <= page < self._page_count:
            item.setData(0, _PAGE, page)
        return item

    def _populate(self, *_args):
        self.tree.clear()
        self.details.clear()
        if self.report is None:
            return
        report = self.report
        mode = self.mode.currentIndex()
        self.tree.setHeaderLabels(["Tag" if mode < 2 else "Finding / artifact count", "Page"])
        self.tree.setRootIsDecorated(mode == 0)

        def add(parent, node):
            item = self._item(parent, node.role or "(unspecified)", node.page,
                              self._node_details(node))
            for child in node.children:
                add(item, child)

        if mode == 0:
            for node in report.nodes:
                add(self.tree, node)
            self.tree.expandToDepth(0)
        elif mode == 1:
            for index, node in enumerate(report.reading_order, 1):
                self._item(self.tree, f"{index}. {node.role or '(unspecified)'}", node.page,
                           self._node_details(node))
        else:
            for warning in report.warnings:
                self._item(self.tree, warning, details=warning + "\n\n" + report.limitations)
            for artifact in report.artifacts:
                self._item(self.tree, f"Artifacts: {artifact.count}", artifact.page,
                           "Explicit artifact marked-content sequences.\n\n" + report.limitations)
            if not report.warnings and not report.artifacts:
                self._item(self.tree, "No inspection records available", details=report.limitations)
        if mode < 2 and not report.nodes:
            self._item(self.tree, "No structure tags", details=report.limitations)

    def _selected(self, current, _previous):
        self.details.setPlainText(current.data(0, _DETAILS) or "" if current else "")
        page = current.data(0, _PAGE) if current else None
        if page is not None and self.document is not None:
            self.page_requested.emit(page)
