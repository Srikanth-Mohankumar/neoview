from contextlib import contextmanager
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog

from neoview.ui.tools import page_pngs


def document():
    doc = fitz.open()
    for index in range(3):
        page = doc.new_page(width=144, height=72)
        page.insert_text((10, 30), f"Page {index + 1}")
    return doc


def test_real_png_dimensions_order_and_source_unchanged(tmp_path):
    output = tmp_path / "images"
    with document() as doc:
        before = doc.tobytes(no_new_id=True)
        result = page_pngs.export_pages_png(doc, "3, 1", 144, str(output))
        assert result == str(output)
        assert sorted(p.name for p in output.iterdir()) == ["page-0001.png", "page-0003.png"]
        for path in output.iterdir():
            pixmap = fitz.Pixmap(str(path))
            assert (pixmap.width, pixmap.height) == (288, 144)
            assert pixmap.n == 3
        assert doc.tobytes(no_new_id=True) == before


@pytest.mark.parametrize("ranges", ["0", "1-4", "1,1", "", "2-1"])
def test_invalid_ranges_write_nothing(tmp_path, ranges):
    with document() as doc, pytest.raises(ValueError):
        page_pngs.export_pages_png(doc, ranges, 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


@pytest.mark.parametrize("dpi", [0, 35, 301, 72.5, True])
def test_invalid_dpi(tmp_path, dpi):
    with document() as doc, pytest.raises(ValueError, match="DPI"):
        page_pngs.export_pages_png(doc, "1", dpi, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


def test_pixel_budget_checked_before_render(tmp_path, monkeypatch):
    monkeypatch.setattr(page_pngs, "MAX_TOTAL_PIXELS", 20_000)
    monkeypatch.setattr(fitz.Page, "get_pixmap", lambda *_a, **_k: pytest.fail("rendered early"))
    with document() as doc, pytest.raises(ValueError, match="lower DPI"):
        page_pngs.export_pages_png(doc, "1-3", 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


def test_existing_empty_directory_never_overwritten(tmp_path):
    output = tmp_path / "images"
    output.mkdir()
    with document() as doc, pytest.raises(FileExistsError):
        page_pngs.export_pages_png(doc, "1", 72, str(output))
    assert output.is_dir() and list(output.iterdir()) == []


def test_render_failure_cleans_partial_images(tmp_path, monkeypatch):
    original = fitz.Page.get_pixmap

    def fail_second(page, *args, **kwargs):
        if page.number == 1:
            raise OSError("render failed")
        return original(page, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_pixmap", fail_second)
    with document() as doc, pytest.raises(OSError, match="render failed"):
        page_pngs.export_pages_png(doc, "1-3", 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


def test_publish_failure_cleans_reserved_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(page_pngs.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("publish")))
    with document() as doc, pytest.raises(OSError, match="publish"):
        page_pngs.export_pages_png(doc, "1", 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []


@pytest.mark.parametrize("cancel", ["range", "dpi", "folder", None])
def test_run_dialog_flow(tmp_path, monkeypatch, qtbot, cancel):
    messages = []
    window = SimpleNamespace(_status=SimpleNamespace(showMessage=lambda *args: messages.append(args)))

    @contextmanager
    def snapshot(_window):
        with document() as doc:
            yield doc, None, str(tmp_path / "source.pdf")

    monkeypatch.setattr(page_pngs, "snapshot", snapshot)
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("2", cancel != "range"))
    monkeypatch.setattr(QInputDialog, "getInt", lambda *_: (72, cancel != "dpi"))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: "" if cancel == "folder" else str(tmp_path))
    assert page_pngs.run(window) is None
    output = tmp_path / "source-pages"
    if cancel is None:
        assert not output.exists()
        assert window._document_export_jobs
        qtbot.waitUntil(lambda: not window._document_export_jobs, timeout=10000)
    assert output.exists() == (cancel is None)
    assert bool(messages) == (cancel is None)
    if output.exists():
        assert [p.name for p in output.iterdir()] == ["page-0002.png"]


def test_mid_publish_failure_removes_all_published_files(tmp_path, monkeypatch):
    original = page_pngs.os.replace
    calls = 0

    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second publication failed")
        return original(*args)

    monkeypatch.setattr(page_pngs.os, "replace", fail_second)
    with document() as doc, pytest.raises(OSError, match="publication failed"):
        page_pngs.export_pages_png(doc, "1-3", 72, str(tmp_path / "images"))
    assert [p for p in tmp_path.iterdir() if p.name != "qsettings"] == []



def test_background_job_remains_responsive_and_cancels_cleanly(tmp_path, qtbot, monkeypatch):
    from PySide6.QtCore import QTimer

    from neoview.ui.background_png_export import PngExportJob

    monkeypatch.setattr(PngExportJob, "worker_arguments",
                        lambda *_: ["-c", "import time; time.sleep(30)"])
    window = SimpleNamespace(_status=SimpleNamespace(showMessage=lambda *_: None))
    with document() as doc:
        job = PngExportJob(window, doc, "1", 72, str(tmp_path / "images")).start()
    work = job.work
    events = []
    QTimer.singleShot(1, lambda: events.append("responsive"))
    qtbot.waitUntil(lambda: bool(events), timeout=1000)
    assert not job.done
    assert not (tmp_path / "images").exists()
    job.cancel(wait=True, silent=True)
    qtbot.waitUntil(lambda: not window._document_export_jobs, timeout=1500)
    assert not work.exists()
    assert not (tmp_path / "images").exists()


def test_background_worker_failure_cleans_staging(tmp_path, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from neoview.ui.background_png_export import PngExportJob

    monkeypatch.setattr(PngExportJob, "worker_arguments", lambda *_: ["-c", "raise SystemExit(3)"])
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: warnings.append(True))
    window = SimpleNamespace(_status=SimpleNamespace(showMessage=lambda *_: None))
    with document() as doc:
        job = PngExportJob(window, doc, "1", 72, str(tmp_path / "images")).start()
    work = job.work
    qtbot.waitUntil(lambda: not window._document_export_jobs, timeout=10000)
    assert warnings
    assert not work.exists()
    assert not (tmp_path / "images").exists()


def test_failed_process_start_cleans_staging(tmp_path, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from neoview.ui.background_png_export import PngExportJob

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: warnings.append(True))
    window = SimpleNamespace(_status=SimpleNamespace(showMessage=lambda *_: None))
    with document() as doc:
        job = PngExportJob(window, doc, "1", 72, str(tmp_path / "images"))
    job.process.setProgram(str(tmp_path / "missing-executable"))
    work = job.work
    job.start()
    qtbot.waitUntil(lambda: not window._document_export_jobs, timeout=10000)
    assert warnings
    assert not work.exists()
    assert not (tmp_path / "images").exists()


def test_background_publish_does_not_clobber_destination(tmp_path, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from neoview.ui.background_png_export import PngExportJob

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: warnings.append(True))
    window = SimpleNamespace(_status=SimpleNamespace(showMessage=lambda *_: None))
    target = tmp_path / "images"
    with document() as doc:
        job = PngExportJob(window, doc, "1", 72, str(target)).start()
    target.mkdir()
    marker = target / "existing.txt"
    marker.write_text("keep")
    work = job.work
    qtbot.waitUntil(lambda: not window._document_export_jobs, timeout=10000)
    assert warnings
    assert marker.read_text() == "keep"
    assert [p.name for p in target.iterdir()] == ["existing.txt"]
    assert not work.exists()


def test_immediate_cancel_handles_starting_process_on_destination_filesystem(tmp_path, qtbot, monkeypatch):
    from neoview.ui.background_png_export import PngExportJob

    monkeypatch.setattr(PngExportJob, "worker_arguments", lambda *_: [
        "-c", "import time; time.sleep(30)",
    ])
    window = SimpleNamespace(_status=SimpleNamespace(showMessage=lambda *_: None))
    with document() as doc:
        job = PngExportJob(window, doc, "1", 72, str(tmp_path / "images"))
    work = job.work
    assert work.parent == tmp_path
    job.start()
    job.cancel(wait=True, silent=True)
    qtbot.waitUntil(lambda: not window._document_export_jobs, timeout=3000)
    assert job.done and job.cancelled
    assert not work.exists()
    assert not (tmp_path / "images").exists()


@pytest.mark.parametrize("frozen", [False, True])
def test_worker_arguments_support_standalone_executable(tmp_path, monkeypatch, frozen):
    from neoview.ui import background_png_export

    monkeypatch.setattr(background_png_export.sys, "frozen", frozen, raising=False)
    job = SimpleNamespace(work=tmp_path)
    arguments = background_png_export.PngExportJob.worker_arguments(job, "1-2", 144)
    payload = [str(tmp_path / "snapshot.pdf"), "1-2", "144", str(tmp_path / "output")]
    if frozen:
        assert arguments == ["--png-export-worker", *payload]
    else:
        assert arguments == ["-m", "neoview.ui.background_png_export", "--worker", *payload]


def test_worker_renders_without_standard_error_stream(tmp_path, monkeypatch):
    from neoview.ui import background_png_export

    source = tmp_path / "snapshot.pdf"
    output = tmp_path / "output"
    with document() as doc:
        doc.save(str(source))
    monkeypatch.setattr(background_png_export.sys, "stderr", None)
    assert background_png_export.run_worker([str(source), "2", "72", str(output)]) == 0
    assert [p.name for p in output.iterdir()] == ["page-0002.png"]
    assert not (tmp_path / "error.txt").exists()


def test_worker_failure_writes_utf8_error_without_standard_error_stream(tmp_path, monkeypatch):
    from neoview.ui import background_png_export

    monkeypatch.setattr(background_png_export.sys, "stderr", None)
    source = tmp_path / "snapshot.pdf"
    output = tmp_path / "output"
    with document() as doc:
        doc.save(str(source))
    monkeypatch.setattr(page_pngs, "export_pages_png",
                        lambda *_: (_ for _ in ()).throw(ValueError("Invalid caf\u00e9 page")))
    assert background_png_export.run_worker([str(source), "2", "72", str(output)]) == 1
    assert "caf\u00e9" in (tmp_path / "error.txt").read_text(encoding="utf-8")
    assert not output.exists()


def test_worker_failure_uses_error_file_when_process_stderr_is_empty(tmp_path):
    from PySide6.QtCore import QProcess

    from neoview.ui.background_png_export import PngExportJob

    (tmp_path / "error.txt").write_text("Useful worker error", encoding="utf-8")
    results = []
    job = SimpleNamespace(done=False, cancelled=False, work=tmp_path,
                          process=SimpleNamespace(readAllStandardError=lambda: b""),
                          _complete=lambda error=None: results.append(error))
    PngExportJob._finished(job, 1, QProcess.ExitStatus.NormalExit)
    assert results == ["Useful worker error"]
