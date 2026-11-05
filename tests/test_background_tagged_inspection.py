"""Isolation, loading-state responsiveness, cancellation and worker serialization."""
import sys

import fitz
from PySide6.QtCore import QProcess, QTimer

from neoview.models.tagged_pdf import TagNode, inspect_tagged_pdf
from neoview.ui.background_tagged_inspection import (
    TaggedInspectionJob,
    _decode_report,
    _report_payload,
    run_worker,
)
from neoview.ui.tagged_pdf import TaggedPdfDialog


def test_slow_inspection_keeps_gui_responsive_and_close_cancels(qtbot, monkeypatch):
    monkeypatch.setattr(TaggedInspectionJob, "worker_arguments", lambda _self: [
        "-c", "import time; time.sleep(60)",
    ])
    with fitz.open() as doc:
        doc.new_page()
        dialog = TaggedPdfDialog(doc)
    qtbot.addWidget(dialog)
    dialog.show()
    job = dialog._job
    work = job.work
    qtbot.waitUntil(lambda: job.process.state() == QProcess.ProcessState.Running)
    assert dialog.report is None
    assert "Inspecting" in dialog.summary.text()
    assert not dialog.tabs.isEnabled()
    assert not dialog.export_report.isEnabled()
    assert not dialog.go_to_page.isEnabled()
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    qtbot.waitUntil(lambda: bool(heartbeat))
    dialog.reject()
    qtbot.waitUntil(lambda: job.done)
    assert not work.exists()
    # A late result cannot populate or re-enable a closed dialog.
    with fitz.open() as doc:
        doc.new_page()
        late = inspect_tagged_pdf(doc)
    dialog._inspection_ready(late)
    assert dialog.report is None
    assert not dialog.export_report.isEnabled()


def test_destroying_loading_dialog_cancels_worker(qtbot, monkeypatch):
    monkeypatch.setattr(TaggedInspectionJob, "worker_arguments", lambda _self: [
        "-c", "import time; time.sleep(60)",
    ])
    with fitz.open() as doc:
        doc.new_page()
        dialog = TaggedPdfDialog(doc)
    job = dialog._job
    work = job.work
    qtbot.waitUntil(lambda: job.process.state() == QProcess.ProcessState.Running)
    dialog.deleteLater()
    qtbot.waitUntil(lambda: job.done)
    assert not work.exists()


def test_worker_serialization_keeps_preorder_without_duplicate_subtrees():
    with fitz.open() as doc:
        doc.new_page()
        report = inspect_tagged_pdf(doc)
    child = TagNode(2, "P", page=0, mcids=[4])
    report.nodes = [TagNode(1, "Document", children=[child])]
    report.reading_order = [report.nodes[0], child]
    payload = _report_payload(report)
    assert "reading_order" not in payload
    decoded = _decode_report(payload)
    assert [node.xref for node in decoded.reading_order] == [1, 2]
    assert decoded.reading_order[1] is decoded.nodes[0].children[0]


def test_standalone_worker_arguments(qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget

    owner = QWidget()
    qtbot.addWidget(owner)
    with fitz.open() as doc:
        doc.new_page()
        job = TaggedInspectionJob(doc, owner)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert job.worker_arguments()[0] == "--tag-inspection-worker"
    job.cancel()
    assert not job.work.exists()


def test_worker_failures_write_diagnostic_without_pdf_mutation(tmp_path):
    missing = tmp_path / "missing.pdf"
    output = tmp_path / "report.json"
    assert run_worker([str(missing), str(output)]) == 1
    assert not output.exists()
    assert "inspection failed" in (tmp_path / "error.txt").read_text(encoding="utf-8")


def test_app_dispatches_inspection_worker_before_gui(monkeypatch):
    import pytest

    from neoview import app
    from neoview.ui import background_tagged_inspection

    calls = []
    monkeypatch.setattr(sys, 'argv', ['neoview', '--tag-inspection-worker',
                                    'snapshot.pdf', 'report.json'])
    monkeypatch.setattr(background_tagged_inspection, 'run_worker',
                        lambda arguments: calls.append(arguments) or 0)
    with pytest.raises(SystemExit) as exc:
        app.main()
    assert exc.value.code == 0
    assert calls == [['snapshot.pdf', 'report.json']]
