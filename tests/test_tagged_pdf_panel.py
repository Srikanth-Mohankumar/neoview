"""Persistent Tags sidebar lifecycle, navigation and document-switch safety."""
import fitz
import pytest
from PySide6.QtCore import QObject, Signal

from neoview.models.tagged_pdf import ArtifactInfo, TaggedPdfReport, TagNode
from neoview.ui import tagged_pdf_panel as panel_ui


@pytest.fixture
def jobs(monkeypatch):
    instances = []

    class Job(QObject):
        ready = Signal(object)
        failed = Signal(str)

        def __init__(self, document, owner):
            super().__init__(owner)
            self.done = False
            self.cancelled = False
            self.started = False
            instances.append(self)

        def start(self):
            self.started = True

        def cancel(self):
            self.cancelled = True
            self.done = True

        def complete(self, report):
            self.done = True
            self.ready.emit(report)

    monkeypatch.setattr(panel_ui, "TaggedInspectionJob", Job)
    return instances


def _report():
    child = TagNode(11, "Figure", mapped_role="Figure", alt_text="A caf\u00e9 <diagram>",
                    actual_text="Actual text", language="fr", page=1, mcids=[3, 5])
    parent = TagNode(10, "Document", children=[child])
    return TaggedPdfReport(tagged=True, language="en", nodes=[parent],
                           reading_order=[parent, child], artifacts=[ArtifactInfo(1, 2)],
                           warnings=["Review reading order manually"])


def test_load_hierarchy_properties_and_page_navigation(qtbot, jobs):
    panel = panel_ui.TaggedPdfPanel()
    qtbot.addWidget(panel)
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        panel.set_document(doc)
        assert panel.document is doc
        assert panel.report is None
        assert "Loading" in panel.status.text()
        assert jobs[0].started
        assert not panel.edit_button.isEnabled()
        jobs[0].complete(_report())
        assert panel.tree.topLevelItemCount() == 1
        item = panel.tree.topLevelItem(0).child(0)
        assert item.text(0) == "Figure"
        assert item.text(1) == "2"
        with qtbot.waitSignal(panel.page_requested) as signal:
            panel.tree.setCurrentItem(item)
        assert signal.args == [1]
        assert "Alternate text: A caf\u00e9 <diagram>" in panel.details.toPlainText()
        assert "Actual text: Actual text" in panel.details.toPlainText()
        assert "Language: fr" in panel.details.toPlainText()
        assert "MCIDs: 3, 5" in panel.details.toPlainText()
        assert "1 finding: see Checks" in panel.status.text()
        assert panel.inspect_button.isEnabled()
        with qtbot.waitSignal(panel.inspect_requested):
            panel.inspect_button.click()
        with qtbot.waitSignal(panel.edit_requested):
            panel.edit_button.click()
        panel.set_document(None)
        assert panel.document is None


def test_switch_document_and_refresh_reject_stale_callbacks(qtbot, jobs):
    panel = panel_ui.TaggedPdfPanel()
    qtbot.addWidget(panel)
    with fitz.open() as first, fitz.open() as second:
        first.new_page()
        second.new_page()
        panel.set_document(first)
        old = jobs[-1]
        panel.set_document(second)
        current = jobs[-1]
        assert old.cancelled
        old.ready.emit(_report())
        old.failed.emit("obsolete failure")
        assert panel.report is None
        assert "Loading" in panel.status.text()
        current.complete(TaggedPdfReport(language="de"))
        assert panel.report.language == "de"
        panel.set_document(second)
        assert len(jobs) == 2
        panel.refresh()
        assert len(jobs) == 3
        current.ready.emit(_report())
        assert panel.report is None
        jobs[-1].complete(TaggedPdfReport(language="es"))
        assert panel.report.language == "es"
        panel.set_document(None)


def test_clear_cancels_releases_document_and_ignores_late_results(qtbot, jobs):
    panel = panel_ui.TaggedPdfPanel()
    qtbot.addWidget(panel)
    doc = fitz.open()
    doc.new_page()
    panel.set_document(doc)
    job = jobs[-1]
    panel.set_document(None)
    assert job.cancelled
    assert panel.document is None
    assert panel.tree.topLevelItemCount() == 0
    assert not panel.refresh_button.isEnabled()
    job.ready.emit(_report())
    assert panel.report is None
    assert "Open a PDF" in panel.status.text()
    doc.close()
    del doc
    assert panel._document is None


def test_untagged_checks_artifacts_and_nonnavigable_nodes(qtbot, jobs):
    panel = panel_ui.TaggedPdfPanel()
    qtbot.addWidget(panel)
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        panel.set_document(doc)
        report = TaggedPdfReport(warnings=["No structure tree"], artifacts=[ArtifactInfo(1, 3)])
        jobs[-1].complete(report)
        assert "untagged" in panel.status.text()
        assert panel.tree.topLevelItem(0).text(0) == "No structure tags"
        panel.mode.setCurrentIndex(2)
        assert panel.tree.topLevelItem(0).text(0) == "No structure tree"
        with qtbot.waitSignal(panel.page_requested) as signal:
            panel.tree.setCurrentItem(panel.tree.topLevelItem(1))
        assert signal.args == [1]
        assert "Explicit artifact" in panel.details.toPlainText()
        panel.set_document(None)


def test_reading_order_and_error_can_be_refreshed(qtbot, jobs):
    panel = panel_ui.TaggedPdfPanel()
    qtbot.addWidget(panel)
    with fitz.open() as doc:
        doc.new_page()
        doc.new_page()
        panel.set_document(doc)
        jobs[-1].failed.emit("Worker unavailable <error>")
        assert "Worker unavailable <error>" in panel.status.text()
        assert panel.refresh_button.isEnabled()
        assert not panel.tree.isEnabled()
        panel.refresh_button.click()
        jobs[-1].complete(_report())
        panel.mode.setCurrentIndex(1)
        assert panel.tree.topLevelItemCount() == 2
        assert panel.tree.topLevelItem(1).text(0) == "2. Figure"
        requested = []
        panel.page_requested.connect(requested.append)
        panel.tree.setCurrentItem(panel.tree.topLevelItem(0))
        assert requested == []  # Parent has no page association.
        panel.tree.setCurrentItem(panel.tree.topLevelItem(1))
        assert requested == [1]
        panel.set_document(None)


def test_partial_inspection_is_visible_without_changing_modes(qtbot, jobs):
    panel = panel_ui.TaggedPdfPanel()
    qtbot.addWidget(panel)
    with fitz.open() as doc:
        doc.new_page()
        panel.set_document(doc)
        report = TaggedPdfReport(warnings=["Structure traversal limit reached; results are incomplete."])
        jobs[-1].complete(report)
        assert panel.mode.currentIndex() == 0
        assert "Partial inspection" in panel.status.text()
        assert "see Checks" in panel.status.text()
        panel.set_document(None)
