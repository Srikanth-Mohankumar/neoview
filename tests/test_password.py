from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit

from neoview.ui.password import PasswordDialog, needs_password, open_document, unlock


def _make_pdf(path: Path, user_pw: str | None = None, owner_pw: str | None = None) -> Path:
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"secret page {i + 1}")
    if user_pw is None and owner_pw is None:
        doc.save(str(path))
    else:
        doc.save(
            str(path),
            encryption=fitz.PDF_ENCRYPT_AES_256,
            user_pw=user_pw or "",
            owner_pw=owner_pw or "",
        )
    doc.close()
    return path


@pytest.fixture
def encrypted_pdf(tmp_path):
    return _make_pdf(tmp_path / "locked.pdf", user_pw="user123", owner_pw="owner456")


def test_plain_pdf_needs_no_password(tmp_path):
    path = _make_pdf(tmp_path / "plain.pdf")
    assert needs_password(str(path)) is False
    doc = fitz.open(str(path))
    try:
        assert unlock(doc, "") is True
    finally:
        doc.close()


def test_encrypted_pdf_needs_password(encrypted_pdf):
    assert needs_password(str(encrypted_pdf)) is True


def test_owner_only_pdf_opens_without_password(tmp_path):
    path = _make_pdf(tmp_path / "owner.pdf", user_pw="", owner_pw="owner456")
    assert needs_password(str(path)) is False


def test_needs_password_raises_for_missing_file(tmp_path):
    with pytest.raises(Exception):
        needs_password(str(tmp_path / "missing.pdf"))


def test_unlock_rejects_wrong_password(encrypted_pdf):
    doc = fitz.open(str(encrypted_pdf))
    try:
        assert unlock(doc, "nope") is False
        assert unlock(doc, "") is False
        assert doc.needs_pass
    finally:
        doc.close()


@pytest.mark.parametrize("password", ["user123", "owner456"])
def test_unlock_accepts_user_or_owner_password(encrypted_pdf, password):
    doc = fitz.open(str(encrypted_pdf))
    try:
        assert unlock(doc, password) is True
        assert doc.page_count == 2
        assert "secret page 1" in doc[0].get_text()
    finally:
        doc.close()


def test_open_document_helper(encrypted_pdf):
    with pytest.raises(PermissionError):
        open_document(str(encrypted_pdf))
    with pytest.raises(PermissionError):
        open_document(str(encrypted_pdf), "wrong")
    doc = open_document(str(encrypted_pdf), "user123")
    try:
        assert doc.page_count == 2
    finally:
        doc.close()


def test_dialog_is_masked_and_toggle_reveals(qtbot):
    dlg = PasswordDialog(None, "locked.pdf")
    qtbot.addWidget(dlg)
    edit = dlg.password_edit()
    assert edit.echoMode() == QLineEdit.EchoMode.Password
    assert not dlg.is_password_visible()

    qtbot.keyClicks(edit, "user123")
    assert dlg.password() == "user123"

    qtbot.mouseClick(dlg.toggle_button(), Qt.MouseButton.LeftButton)
    assert edit.echoMode() == QLineEdit.EchoMode.Normal
    assert dlg.toggle_button().text() == "Hide"

    qtbot.mouseClick(dlg.toggle_button(), Qt.MouseButton.LeftButton)
    assert edit.echoMode() == QLineEdit.EchoMode.Password
    assert dlg.toggle_button().text() == "Show"


def test_dialog_error_line(qtbot):
    dlg = PasswordDialog(None, "locked.pdf")
    qtbot.addWidget(dlg)
    assert dlg.error_text() == ""
    qtbot.keyClicks(dlg.password_edit(), "bad")
    dlg.set_error("Incorrect password. Try again.")
    assert dlg.error_text() == "Incorrect password. Try again."
    assert dlg.password() == ""  # cleared for the next attempt
    dlg.set_error("")
    assert dlg.error_text() == ""


def test_dialog_retry_loop_with_unlock(qtbot, encrypted_pdf, monkeypatch):
    """The caller-owned retry loop: two wrong passwords, then the right one."""
    from PySide6.QtWidgets import QDialog

    attempts = iter(["a", "b", "user123"])
    dlg = PasswordDialog(None, "locked.pdf")
    qtbot.addWidget(dlg)

    def fake_exec():
        dlg.password_edit().setText(next(attempts))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dlg, "exec", fake_exec)
    doc = fitz.open(str(encrypted_pdf))
    errors = []
    try:
        unlocked = False
        for _ in range(3):
            if dlg.exec() != QDialog.DialogCode.Accepted:
                break
            if unlock(doc, dlg.password()):
                unlocked = True
                break
            dlg.set_error("Incorrect password.")
            errors.append(dlg.error_text())
        assert unlocked
        assert errors == ["Incorrect password.", "Incorrect password."]
    finally:
        doc.close()
