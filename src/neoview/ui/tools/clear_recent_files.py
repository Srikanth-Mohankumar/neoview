"""Clear the recent-files list without changing open documents or sessions."""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QMessageBox


def run(window) -> None:
    if not window._recent_files:
        window._status.showMessage("The recent files list is already empty", 2000)
        return
    answer = QMessageBox.question(
        window,
        "Clear Recent Files",
        "Clear the recent files list? Open documents stay open.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if answer != QMessageBox.StandardButton.Yes:
        return
    previous = list(window._recent_files)
    window._settings.setValue("recent_files", [])
    window._settings.sync()
    if window._settings.status() != QSettings.Status.NoError:
        window._settings.setValue("recent_files", previous)
        window._status.showMessage("Could not save the cleared recent files list", 4000)
        return
    window._recent_files = []
    window._rebuild_recent_menu()
    window._welcome.set_recent_files([])
    window._status.showMessage("Recent files list cleared", 2000)
