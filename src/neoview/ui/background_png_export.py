"""Run MuPDF PNG rendering in a separate process, keeping the Qt GUI responsive."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Qt
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget


class PngExportJob(QObject):
    """Own one process and its staging files; publish only after successful completion."""

    def __init__(self, window, document, ranges, dpi, destination):
        super().__init__(window if isinstance(window, QObject) else None)
        self.window = window
        self.destination = Path(destination).absolute()
        if os.path.lexists(self.destination):
            raise FileExistsError("Choose a new output directory; existing folders are not overwritten.")
        self.work = Path(tempfile.mkdtemp(prefix=".neoview-png-job-", dir=self.destination.parent))
        self.done = False
        self.cancelled = False
        self.silent = False
        try:
            document.save(str(self.work / "snapshot.pdf"))
            self.process = QProcess(self)
            self.process.setProgram(sys.executable)
            self.process.setArguments(self.worker_arguments(ranges, dpi))
            self.process.started.connect(self._started)
            self.process.finished.connect(self._finished)
            self.process.errorOccurred.connect(self._process_error)
            self.progress = QProgressDialog(
                "Exporting PDF pages as PNG images...", "Cancel", 0, 0,
                window if isinstance(window, QWidget) else None,
            )
            self.progress.setWindowModality(Qt.WindowModality.NonModal)
            self.progress.setWindowTitle("Export Page Images")
            self.progress.setMinimumDuration(0)
            self.progress.canceled.connect(self.cancel)
        except Exception:
            shutil.rmtree(self.work)
            raise

    def worker_arguments(self, ranges, dpi):
        return ["-m", "neoview.ui.background_png_export", "--worker",
                str(self.work / "snapshot.pdf"), ranges, str(dpi), str(self.work / "output")]

    def start(self):
        jobs = getattr(self.window, "_document_export_jobs", None)
        if jobs is None:
            jobs = self.window._document_export_jobs = []
        jobs.append(self)
        self.progress.show()
        self.process.start()
        return self

    def _started(self):
        if self.cancelled:
            self.process.kill()

    def cancel(self, wait=False, silent=False):
        if self.done:
            return
        self.cancelled = True
        self.silent = silent
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            if wait:
                self.process.waitForFinished(1000)
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self._complete()

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._complete(self.process.errorString())

    def _finished(self, exit_code, exit_status):
        if self.done:
            return
        if self.cancelled:
            self._complete()
        elif exit_code or exit_status != QProcess.ExitStatus.NormalExit:
            detail = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
            self._complete(detail[-2000:] or "The image export process failed.")
        else:
            self._complete()

    def _publish(self):
        output = self.work / "output"
        images = list(output.iterdir())
        if not images or any(not p.is_file() or p.suffix != ".png" for p in images):
            raise OSError("The image export process produced no valid PNG output.")
        # Exclusive reservation means cleanup only touches a folder this job created.
        self.destination.mkdir()
        try:
            for image in images:
                os.replace(image, self.destination / image.name)
        except Exception:
            shutil.rmtree(self.destination)
            raise

    def _complete(self, error=None):
        if self.done:
            return
        self.done = True
        try:
            if not self.cancelled and error is None:
                try:
                    self._publish()
                except Exception as exc:
                    error = str(exc)
            self.progress.close()
            if not self.silent:
                if error and not self.cancelled:
                    QMessageBox.warning(
                        self.window if isinstance(self.window, QWidget) else None,
                        "Could Not Export Page Images", error,
                    )
                elif not self.cancelled:
                    self.window._status.showMessage(
                        f"Exported page images to {self.destination}", 4000,
                    )
        finally:
            shutil.rmtree(self.work, ignore_errors=True)
            jobs = getattr(self.window, "_document_export_jobs", [])
            if self in jobs:
                jobs.remove(self)
            self.progress.deleteLater()
            self.deleteLater()


def main():
    if len(sys.argv) != 6 or sys.argv[1] != "--worker":
        raise SystemExit("Usage: --worker PDF RANGES DPI OUTPUT")
    import fitz

    from neoview.ui.tools.page_pngs import export_pages_png

    with fitz.open(sys.argv[2]) as document:
        export_pages_png(document, sys.argv[3], int(sys.argv[4]), sys.argv[5])


if __name__ == "__main__":
    main()
