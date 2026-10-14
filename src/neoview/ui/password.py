"""Password-protected PDF support: detection, unlocking and the prompt dialog.

The dialog only collects one password; the caller owns the retry loop (NeoView allows
three attempts) and calls ``set_error`` between attempts::

    dlg = PasswordDialog(parent, file_name)
    for _ in range(MAX_ATTEMPTS):
        if dlg.exec() != QDialog.DialogCode.Accepted:
            break
        if unlock(doc, dlg.password()):
            ...
        dlg.set_error("Incorrect password. Try again.")
"""

from __future__ import annotations

import fitz
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MAX_ATTEMPTS = 3


def needs_password(path: str) -> bool:
    """True if opening ``path`` requires a password before its pages can be read.

    Files with only an owner password (permissions, no open password) return False.
    Missing or unreadable files raise the same exception ``fitz.open`` raises.
    """
    doc = fitz.open(path)
    try:
        return bool(doc.needs_pass)
    finally:
        doc.close()


def unlock(doc: fitz.Document, password: str) -> bool:
    """Authenticate ``doc`` with ``password`` (user or owner). True on success.

    A document that does not need a password is reported as unlocked.
    """
    if not doc.needs_pass:
        return True
    return bool(doc.authenticate(password or ""))


def open_document(path: str, password: str | None = None) -> fitz.Document:
    """Open ``path`` and unlock it with ``password`` if needed.

    Raises ``PermissionError`` when the document is encrypted and the password is missing
    or wrong. Used by the printing and presentation modules, which each own a document.
    """
    doc = fitz.open(path)
    if doc.needs_pass and not unlock(doc, password or ""):
        doc.close()
        raise PermissionError(f"Password required to open {path}")
    return doc


class PasswordDialog(QDialog):
    """Asks for a document password. Masked by default, with a Show/Hide toggle."""

    def __init__(self, parent: QWidget | None = None, file_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Password Required")
        self.setModal(True)

        layout = QVBoxLayout(self)
        name = file_name or "This document"
        self._prompt = QLabel(f"{name} is password protected.\nEnter the password to open it.")
        self._prompt.setWordWrap(True)
        layout.addWidget(self._prompt)

        row = QHBoxLayout()
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setPlaceholderText("Password")
        self._edit.setAccessibleName("Password")
        row.addWidget(self._edit, 1)
        self._toggle = QPushButton("Show")
        self._toggle.setCheckable(True)
        self._toggle.setAutoDefault(False)
        self._toggle.setToolTip("Show or hide the password")
        self._toggle.toggled.connect(self._on_toggle)
        row.addWidget(self._toggle)
        layout.addLayout(row)

        self._error = QLabel("")
        self._error.setObjectName("passwordError")
        self._error.setStyleSheet("color: #c62828;")
        self._error.setWordWrap(True)
        self._error.hide()
        layout.addWidget(self._error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._buttons = buttons
        layout.addWidget(buttons)

        self._edit.setFocus()

    def password(self) -> str:
        return self._edit.text()

    def password_edit(self) -> QLineEdit:
        return self._edit

    def toggle_button(self) -> QPushButton:
        return self._toggle

    def is_password_visible(self) -> bool:
        return self._edit.echoMode() == QLineEdit.EchoMode.Normal

    def set_error(self, message: str) -> None:
        """Show ``message`` under the field (empty hides it) and clear the field."""
        self._error.setText(message)
        self._error.setVisible(bool(message))
        if message:
            self._edit.clear()
            self._edit.setFocus()

    def error_text(self) -> str:
        return self._error.text() if not self._error.isHidden() else ""

    def _on_toggle(self, checked: bool) -> None:
        self._edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self._toggle.setText("Hide" if checked else "Show")
