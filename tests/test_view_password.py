"""PdfView.open_document / reload_document with encrypted PDFs."""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from neoview.ui.pdf_view import PdfView


def _make_pdf(path: Path, n_pages: int = 2, user_pw: str | None = None) -> Path:
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f"page {i + 1}")
    if user_pw:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=user_pw,
                 owner_pw=user_pw + "-owner")
    else:
        doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def view(qtbot, monkeypatch):
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **k: errors.append(a))
    v = PdfView()
    qtbot.addWidget(v)
    v.resize(600, 500)
    v.errors = errors
    yield v
    v.close_document()


def test_plain_pdf_has_no_password(view, tmp_path):
    path = _make_pdf(tmp_path / "plain.pdf")
    assert view.open_document(str(path)) is True
    assert view.document_password() is None
    # A password given for an unencrypted file is ignored, not remembered.
    assert view.open_document(str(path), "unused") is True
    assert view.document_password() is None


def test_encrypted_without_password_emits_signal(qtbot, view, tmp_path):
    path = _make_pdf(tmp_path / "locked.pdf", user_pw="pw")
    with qtbot.waitSignal(view.password_required, timeout=1000) as blocker:
        assert view.open_document(str(path)) is False
    assert blocker.args == [str(path)]
    assert view.errors == []  # no error box for a missing password
    assert view.document is None


def test_wrong_password_emits_signal_and_keeps_current_document(qtbot, view, tmp_path):
    plain = _make_pdf(tmp_path / "plain.pdf", n_pages=3)
    locked = _make_pdf(tmp_path / "locked.pdf", user_pw="pw")
    assert view.open_document(str(plain))
    with qtbot.waitSignal(view.password_required, timeout=1000):
        assert view.open_document(str(locked), "nope") is False
    assert view.page_count == 3
    assert view.doc_path == str(plain.resolve())
    assert view.errors == []


def test_correct_password_opens_and_is_remembered(view, tmp_path):
    path = _make_pdf(tmp_path / "locked.pdf", n_pages=2, user_pw="pw")
    assert view.open_document(str(path), "pw") is True
    assert view.page_count == 2
    assert view.document_password() == "pw"
    QApplication.processEvents()


def test_reload_reauthenticates_silently(qtbot, view, tmp_path):
    path = _make_pdf(tmp_path / "locked.pdf", n_pages=2, user_pw="pw")
    assert view.open_document(str(path), "pw")
    _make_pdf(path, n_pages=4, user_pw="pw")  # LaTeX rebuild, same password
    signals = []
    view.password_required.connect(signals.append)
    assert view.reload_document() is True
    assert view.page_count == 4
    assert signals == []


def test_reload_with_changed_password_asks_again(qtbot, view, tmp_path):
    path = _make_pdf(tmp_path / "locked.pdf", n_pages=2, user_pw="pw")
    assert view.open_document(str(path), "pw")
    _make_pdf(path, n_pages=3, user_pw="other")
    with qtbot.waitSignal(view.password_required, timeout=1000) as blocker:
        assert view.reload_document() is False
    assert blocker.args == [str(path.resolve())]
    assert view.page_count == 2  # still showing the old document


def test_close_forgets_password(view, tmp_path):
    path = _make_pdf(tmp_path / "locked.pdf", user_pw="pw")
    assert view.open_document(str(path), "pw")
    view.close_document()
    assert view.document_password() is None


def test_other_open_errors_still_report(view, tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    assert view.open_document(str(bad)) is False
    assert len(view.errors) == 1
