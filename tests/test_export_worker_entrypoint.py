"""Frozen application exports enter worker mode without creating another GUI."""
import sys

import pytest

from neoview import app
from neoview.ui import background_png_export


def test_worker_flag_dispatches_before_qapplication(monkeypatch):
    arguments = ["snapshot.pdf", "1-2", "144", "output"]
    monkeypatch.setattr(sys, "argv", ["neoview.exe", "--png-export-worker", *arguments])
    received = []
    monkeypatch.setattr(background_png_export, "run_worker", lambda args: received.append(args) or 0)
    monkeypatch.setattr(app, "QApplication", lambda *_: pytest.fail("Worker must not open the GUI"))
    with pytest.raises(SystemExit) as result:
        app.main()
    assert result.value.code == 0
    assert received == [arguments]


def test_worker_failure_exit_code_reaches_frozen_launcher(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["neoview.exe", "--png-export-worker"])
    monkeypatch.setattr(background_png_export, "run_worker", lambda _: 2)
    with pytest.raises(SystemExit) as result:
        app.main()
    assert result.value.code == 2
