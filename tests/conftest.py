import os
import sys

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def _qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path, _qt_app):
    config_dir = tmp_path / "qsettings"
    config_dir.mkdir(parents=True, exist_ok=True)

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(config_dir))

    settings = QSettings("NeoView", "NeoView")
    settings.clear()
    settings.sync()
    yield
    settings.clear()
    settings.sync()
