"""Inspect owned PDF snapshots in a separate MuPDF process."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal
from PySide6.QtWidgets import QApplication

from neoview.models.tagged_pdf import ArtifactInfo, TaggedPdfReport, TagNode

_MAX_REPORT_BYTES = 32 * 1024 * 1024


def _signature(stat):
    return (int(stat.st_mtime_ns), int(stat.st_size), int(getattr(stat, "st_ino", 0)))


def _report_payload(report):
    return {
        "tagged": report.tagged, "language": report.language,
        "nodes": [asdict(node) for node in report.nodes],
        "artifacts": [asdict(item) for item in report.artifacts],
        "warnings": report.warnings, "limitations": report.limitations,
    }


def _decode_report(payload):
    report = TaggedPdfReport(tagged=payload["tagged"], language=payload["language"],
                             warnings=payload["warnings"], limitations=payload["limitations"])

    def node(value):
        data = dict(value)
        children = data.pop("children")
        result = TagNode(**data)
        report.reading_order.append(result)
        result.children = [node(child) for child in children]
        return result

    report.nodes = [node(value) for value in payload["nodes"]]
    report.artifacts = [ArtifactInfo(**value) for value in payload["artifacts"]]
    return report


class TaggedInspectionJob(QObject):
    """One isolated worker and private staging folder, cancelled with its dialog."""

    ready = Signal(object)
    failed = Signal(str)

    def __init__(self, document, owner, *, from_source=False, source_signature=None, password=None):
        # App ownership keeps a killed process alive through final OS termination.
        super().__init__(QApplication.instance())
        self.done = False
        self.cancelled = False
        self.work = Path(tempfile.mkdtemp(prefix=".neoview-tag-inspection-"))
        try:
            self.from_source = from_source
            if from_source:
                if not document.name:
                    raise ValueError("Automatic inspection requires a saved PDF. Use Inspector instead.")
                source = str(Path(document.name).absolute())
                signature = source_signature or _signature(os.stat(source))
                request = {"source": source, "signature": signature, "password": password or ""}
                (self.work / "request.json").write_text(json.dumps(request), encoding="utf-8")
            else:
                document.save(str(self.work / "snapshot.pdf"))
            self.process = QProcess(self)
            self.process.setProgram(sys.executable)
            self.process.setArguments(self.worker_arguments())
            self.process.finished.connect(self._finished)
            self.process.errorOccurred.connect(self._error)
            self.process.started.connect(self._started)
            owner.destroyed.connect(self.cancel)
            QApplication.instance().aboutToQuit.connect(self.cancel)
        except Exception:
            shutil.rmtree(self.work, ignore_errors=True)
            self.deleteLater()
            raise

    def worker_arguments(self):
        arguments = [str(self.work / "snapshot.pdf"), str(self.work / "report.json")]
        if self.from_source:
            arguments.append(str(self.work / "request.json"))
        if getattr(sys, "frozen", False):
            return ["--tag-inspection-worker", *arguments]
        return ["-m", "neoview.ui.background_tagged_inspection", "--worker", *arguments]

    def start(self):
        if not self.done:
            self.process.start()

    def _started(self):
        if self.cancelled:
            self.process.kill()

    def cancel(self, *_args):
        if self.done:
            return
        self.cancelled = True
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._complete()

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._complete(self.process.errorString())

    def _finished(self, exit_code, exit_status):
        if self.done:
            return
        if self.cancelled:
            self._complete()
        elif exit_code or exit_status != QProcess.ExitStatus.NormalExit:
            detail = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
            try:
                detail = (self.work / "error.txt").read_text(encoding="utf-8") or detail
            except OSError:
                pass
            self._complete(detail[-2000:] or "The inspection process failed.")
        else:
            self._complete()

    def _complete(self, error=None):
        if self.done:
            return
        self.done = True
        try:
            if not self.cancelled and error is None:
                try:
                    path = self.work / "report.json"
                    if path.stat().st_size > _MAX_REPORT_BYTES:
                        raise ValueError("Inspection report exceeds the safe display size limit.")
                    report = _decode_report(json.loads(path.read_text(encoding="utf-8")))
                except Exception as exc:
                    error = str(exc)
                else:
                    self.ready.emit(report)
            if error and not self.cancelled:
                self.failed.emit(error)
        finally:
            shutil.rmtree(self.work, ignore_errors=True)
            self.deleteLater()


def run_worker(arguments):
    """Worker CLI: snapshot PDF path and report JSON path; no GUI is created."""
    try:
        if len(arguments) not in (2, 3):
            raise ValueError("Usage: worker SNAPSHOT_PDF REPORT_JSON [SOURCE_REQUEST]")
        import fitz

        from neoview.models.tagged_pdf import inspect_tagged_pdf

        source, destination = arguments[:2]
        password = ""
        if len(arguments) == 3:
            request = json.loads(Path(arguments[2]).read_text(encoding="utf-8"))
            password = request.get("password", "")
            expected = tuple(request["signature"])
            with open(request["source"], "rb") as original:
                if _signature(os.fstat(original.fileno())) != expected:
                    raise ValueError("PDF changed since it was opened; reload it before inspecting tags.")
                with open(source, "wb") as snapshot:
                    shutil.copyfileobj(original, snapshot, length=1024 * 1024)
                if (_signature(os.fstat(original.fileno())) != expected
                        or _signature(os.stat(request["source"])) != expected):
                    raise ValueError("PDF changed while preparing inspection; reload and try again.")
        with fitz.open(source) as document:
            if document.needs_pass and not document.authenticate(password):
                raise ValueError("Could not unlock the inspection snapshot; reopen the PDF.")
            payload = _report_payload(inspect_tagged_pdf(document))
        text = json.dumps(payload, ensure_ascii=False)
        if len(text.encode("utf-8")) > _MAX_REPORT_BYTES:
            raise ValueError("Inspection report exceeds the safe display size limit.")
        Path(destination).write_text(text, encoding="utf-8")
        return 0
    except Exception as exc:
        detail = f"Tagged PDF inspection failed: {exc}"
        if len(arguments) in (2, 3):
            try:
                (Path(arguments[1]).parent / "error.txt").write_text(detail, encoding="utf-8")
            except OSError:
                pass
        if sys.stderr is not None:
            try:
                sys.stderr.write(detail + "\n")
            except (OSError, UnicodeError):
                pass
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "--worker":
        raise SystemExit("Usage: --worker SNAPSHOT_PDF REPORT_JSON")
    raise SystemExit(run_worker(sys.argv[2:]))
