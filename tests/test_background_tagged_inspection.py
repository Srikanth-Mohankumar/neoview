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


def test_source_job_stages_only_in_worker_and_never_saves_gui_document(tmp_path, qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from neoview.ui.background_tagged_inspection import _signature

    path = tmp_path / 'source.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), 'Accessible source')
        doc.save(str(path))
    original = path.read_bytes()
    owner = QWidget()
    qtbot.addWidget(owner)
    with fitz.open(path) as doc:
        def forbidden_save(*args, **kwargs):
            raise AssertionError('Automatic inspection must not save on the GUI thread')
        monkeypatch.setattr(fitz.Document, 'save', forbidden_save)
        job = TaggedInspectionJob(doc, owner, from_source=True,
                                  source_signature=_signature(path.stat()))
        assert not (job.work / 'snapshot.pdf').exists()
        results = []
        job.ready.connect(results.append)
        job.start()
        qtbot.waitUntil(lambda: job.done, timeout=10000)
        assert len(results) == 1
        assert not job.work.exists()
    assert path.read_bytes() == original


def test_source_worker_rejects_changes_since_viewer_opened_file(tmp_path):
    import json

    from neoview.ui.background_tagged_inspection import _signature

    source, snapshot = tmp_path / 'source.pdf', tmp_path / 'snapshot.pdf'
    output, request = tmp_path / 'report.json', tmp_path / 'request.json'
    source.write_bytes(b'Original source')
    signature = _signature(source.stat())
    request.write_text(json.dumps({'source': str(source), 'signature': signature}), encoding='utf-8')
    source.write_bytes(b'Changed source with different length')
    assert run_worker([str(snapshot), str(output), str(request)]) == 1
    assert not output.exists()
    assert not snapshot.exists()
    assert 'changed since' in (tmp_path / 'error.txt').read_text(encoding='utf-8')


def test_source_worker_copies_and_unlocks_encrypted_pdf(tmp_path):
    import json

    from neoview.ui.background_tagged_inspection import _signature

    source, snapshot = tmp_path / 'source.pdf', tmp_path / 'snapshot.pdf'
    output, request = tmp_path / 'report.json', tmp_path / 'request.json'
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(source), encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw='owner', user_pw='reader')
    original = source.read_bytes()
    request.write_text(json.dumps({'source': str(source), 'signature': _signature(source.stat()),
                                   'password': 'reader'}), encoding='utf-8')
    assert run_worker([str(snapshot), str(output), str(request)]) == 0
    assert json.loads(output.read_text(encoding='utf-8'))['artifacts'][0]['page'] == 0
    assert source.read_bytes() == original


def test_source_worker_rejects_modification_during_copy(tmp_path, monkeypatch):
    import json
    import shutil

    from neoview.ui.background_tagged_inspection import _signature

    source, snapshot = tmp_path / 'source.pdf', tmp_path / 'snapshot.pdf'
    output, request = tmp_path / 'report.json', tmp_path / 'request.json'
    with fitz.open() as document:
        document.new_page()
        document.save(str(source))
    request.write_text(json.dumps({'source': str(source), 'signature': _signature(source.stat())}),
                       encoding='utf-8')
    copy = shutil.copyfileobj

    def changed_copy(original, destination, **options):
        copy(original, destination, **options)
        with source.open('ab') as changed:
            changed.write(b'\n')

    monkeypatch.setattr(shutil, 'copyfileobj', changed_copy)
    assert run_worker([str(snapshot), str(output), str(request)]) == 1
    assert not output.exists()
    assert 'changed while' in (tmp_path / 'error.txt').read_text(encoding='utf-8')
