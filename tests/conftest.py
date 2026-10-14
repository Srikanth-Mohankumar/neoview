import gc
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
def _isolated_qsettings(tmp_path, monkeypatch, _qt_app):
    """Give every test its own empty settings store.

    MainWindow builds QSettings("NeoView", "NeoView"), which is NativeFormat: the real
    ~/.config/NeoView/NeoView.conf on Linux and the registry on Windows. setPath cannot
    redirect the registry, so MainWindow gets an INI file under tmp_path instead.
    """
    import neoview.ui.main_window as main_window

    config_dir = tmp_path / "qsettings"
    config_dir.mkdir(parents=True, exist_ok=True)
    ini_path = str(config_dir / "NeoView.ini")

    # Belt and braces for any other QSettings(org, app) on Unix-like systems.
    for fmt in (QSettings.Format.NativeFormat, QSettings.Format.IniFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, str(config_dir))

    monkeypatch.setattr(
        main_window,
        "QSettings",
        lambda *_args, **_kwargs: QSettings(ini_path, QSettings.Format.IniFormat),
    )
    yield


@pytest.fixture(autouse=True)
def _release_page_pixmap_cache():
    """Drop the shared PageItem pixmap LRU between tests so back-to-back
    tests that each open a multi-page PDF don't pile up cached QPixmaps."""
    yield
    try:
        from neoview.ui.page_item import PageItem
        PageItem._PIXMAP_CACHE.clear()
    except Exception:
        pass
    gc.collect()
