"""Read-only inspection of PDF structure, logical order and marked artifacts."""
from __future__ import annotations

import json
from dataclasses import asdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from neoview.models.tagged_pdf import inspect_tagged_pdf


class TaggedPdfDialog(QDialog):
    """An inspection snapshot; never writes tags or retains a PDF document."""

    page_requested = Signal(int)

    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tagged PDF Inspection")
        self.resize(900, 650)
        self.report = inspect_tagged_pdf(document)
        self._page_count = len(document)
        self._source = document.name or "document.pdf"
        layout = QVBoxLayout(self)
        self.summary = QLabel(
            f"Marked as tagged: {'Yes' if self.report.tagged else 'No'} | "
            f"Document language: {self.report.language or 'Not specified'}"
        )
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        description = QLabel(
            "Read-only inspection of the PDF's stored structure. Logical tag order can differ "
            "from visual order. Automated checks do not certify accessibility or PDF/UA compliance."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tags = self._tree(["Tag / role", "Page", "MCIDs", "Properties"])
        self.tags.setObjectName("pdf_tags_tree")
        self.tags.setAccessibleName("PDF structure tags")
        self.tabs.addTab(self.tags, "Tags")
        for node in self.report.nodes:
            self._add_tag(self.tags, node)
        if not self.report.nodes:
            QTreeWidgetItem(self.tags, ["No structure tags found"])
        self.tags.expandToDepth(1)
        self.order = self._tree(["Order", "Tag / role", "Page", "MCIDs", "Properties"])
        self.order.setObjectName("pdf_reading_order")
        self.order.setAccessibleName("Logical reading order")
        self.tabs.addTab(self.order, "Logical Reading Order")
        for index, node in enumerate(self.report.reading_order, 1):
            item = QTreeWidgetItem(self.order, [str(index), *self._values(node)])
            self._set_page(item, node.page)
        checks_page = QWidget()
        checks_layout = QVBoxLayout(checks_page)
        self.checks = self._tree(["Inspection findings"])
        self.checks.setObjectName("pdf_tag_findings")
        for warning in self.report.warnings:
            QTreeWidgetItem(self.checks, [warning])
        if not self.report.warnings:
            QTreeWidgetItem(self.checks, [
                "No findings from these limited automated checks. Manual review is still required."
            ])
        checks_layout.addWidget(self.checks)
        checks_layout.addWidget(QLabel("Explicit artifact marked-content sequences by page:"))
        self.artifacts = self._tree(["Page", "Artifact sequences"])
        self.artifacts.setObjectName("pdf_artifacts")
        for artifact in self.report.artifacts:
            item = QTreeWidgetItem(self.artifacts, [str(artifact.page + 1), str(artifact.count)])
            self._set_page(item, artifact.page)
        if not self.report.artifacts:
            QTreeWidgetItem(self.artifacts, ["No artifact counts available; review inspection findings"])
        checks_layout.addWidget(self.artifacts)
        limitations = QLabel(self.report.limitations)
        limitations.setTextFormat(Qt.TextFormat.PlainText)
        limitations.setWordWrap(True)
        limitations.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        checks_layout.addWidget(limitations)
        self.tabs.addTab(checks_page, "Checks and Artifacts")
        controls = QHBoxLayout()
        self.go_to_page = QPushButton("Go to Selected Page")
        self.go_to_page.setEnabled(False)
        self.go_to_page.clicked.connect(self._navigate_selected)
        controls.addWidget(self.go_to_page)
        self.export_report = QPushButton("Export Inspection JSON...")
        self.export_report.clicked.connect(self._export_report)
        controls.addWidget(self.export_report)
        controls.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        controls.addWidget(buttons)
        layout.addLayout(controls)
        self._selected_tree = None
        for tree in (self.tags, self.order, self.artifacts):
            tree.itemSelectionChanged.connect(lambda t=tree: self._selection_changed(t))
            tree.itemActivated.connect(lambda item, _column: self._navigate_item(item))
        self.tabs.currentChanged.connect(self._tab_changed)

    @staticmethod
    def _tree(headers):
        tree = QTreeWidget()
        tree.setHeaderLabels(headers)
        tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setRootIsDecorated(False)
        return tree

    @staticmethod
    def _values(node):
        role = node.role or "(unspecified role)"
        if node.mapped_role and node.mapped_role != node.role:
            role += f" -> {node.mapped_role}"
        properties = []
        for label, value in (
            ("Title", node.title), ("Alt", node.alt_text),
            ("ActualText", node.actual_text), ("Lang", node.language),
        ):
            if value:
                properties.append(f"{label}: {value}")
        return [role, str(node.page + 1) if node.page is not None else "",
                ", ".join(str(mcid) for mcid in node.mcids), " | ".join(properties)]

    def _add_tag(self, parent, node):
        item = QTreeWidgetItem(parent, self._values(node))
        item.setToolTip(0, f"Structure object: {node.xref or 'direct dictionary'}")
        item.setToolTip(3, item.text(3))
        self._set_page(item, node.page)
        for child in node.children:
            self._add_tag(item, child)
        if node.children:
            self.tags.setRootIsDecorated(True)

    def _set_page(self, item, page):
        if isinstance(page, int) and 0 <= page < self._page_count:
            item.setData(0, Qt.ItemDataRole.UserRole, page)

    def _selection_changed(self, tree):
        self._selected_tree = tree
        item = tree.currentItem()
        self.go_to_page.setEnabled(
            item is not None and item.data(0, Qt.ItemDataRole.UserRole) is not None
        )

    def _tab_changed(self, index):
        tree = (self.tags, self.order, self.artifacts)[index]
        self._selection_changed(tree)

    def _navigate_selected(self):
        if self._selected_tree is not None:
            self._navigate_item(self._selected_tree.currentItem())

    def _navigate_item(self, item):
        if item is not None:
            page = item.data(0, Qt.ItemDataRole.UserRole)
            if page is not None:
                self.page_requested.emit(page)

    def _export_report(self):
        from neoview.ui.tool_support import atomic_text, choose_file

        try:
            report = self.report
            # Flat order entries reference the tree instead of duplicating every subtree.
            payload = {
                "tagged": report.tagged, "language": report.language,
                "nodes": [asdict(node) for node in report.nodes],
                "reading_order": [
                    {"xref": node.xref, "role": node.role, "page": node.page,
                     "mcids": node.mcids}
                    for node in report.reading_order
                ],
                "artifacts": [asdict(artifact) for artifact in report.artifacts],
                "warnings": report.warnings, "limitations": report.limitations,
            }
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            target = choose_file(self, self._source, "_tag_inspection", ".json",
                                 "Export Tagged PDF Inspection")
            if target:
                atomic_text(self._source, target, text)
        except Exception as error:
            QMessageBox.warning(self, "Export Tagged PDF Inspection", str(error))
