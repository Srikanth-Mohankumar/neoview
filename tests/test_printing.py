from pathlib import Path

import fitz
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QDialog

from neoview.ui import printing
from neoview.ui.printing import (
    MAX_PRINT_DPI,
    fit_page,
    page_sequence,
    print_document,
    printer_pages,
    render_dpi,
    render_pages,
    selected_pages,
)

A4 = (595.0, 842.0)


def _make_pdf(path: Path, sizes, password: str | None = None) -> Path:
    doc = fitz.open()
    for i, (w, h) in enumerate(sizes):
        page = doc.new_page(width=w, height=h)
        page.draw_rect(fitz.Rect(10, 10, w - 10, h - 10), color=(1, 0, 0), fill=(0.2, 0.4, 0.9))
        page.insert_text((40, 60), f"Page {i + 1}", fontsize=36)
    if password:
        doc.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=password,
                 owner_pw=password + "-owner")
    else:
        doc.save(str(path))
    doc.close()
    return path


def _pdf_printer(out: Path) -> QPrinter:
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(out))
    return printer


def _page_count(path: Path) -> int:
    doc = fitz.open(str(path))
    try:
        return doc.page_count
    finally:
        doc.close()


# -- page selection --------------------------------------------------------------------


def test_selected_pages_all():
    assert selected_pages("all", 4) == [0, 1, 2, 3]
    assert selected_pages("all", 0) == []


def test_selected_pages_current_is_clamped():
    assert selected_pages("current", 5, current_page=2) == [2]
    assert selected_pages("current", 5, current_page=9) == [4]
    assert selected_pages("current", 5, current_page=-1) == [0]


def test_selected_pages_range():
    assert selected_pages("range", 10, from_page=2, to_page=4) == [1, 2, 3]
    assert selected_pages("range", 10, from_page=4, to_page=2) == [1, 2, 3]  # reversed
    assert selected_pages("range", 5, from_page=3, to_page=99) == [2, 3, 4]  # clamped
    assert selected_pages("range", 5, from_page=0, to_page=2) == [0, 1]  # open start
    assert selected_pages("range", 5, from_page=4, to_page=0) == [3, 4]  # open end
    assert selected_pages("range", 5, from_page=0, to_page=0) == [0, 1, 2, 3, 4]
    assert selected_pages("range", 3, from_page=7, to_page=9) == []


def test_printer_pages_reads_print_range():
    printer = QPrinter()
    printer.setFromTo(2, 3)
    printer.setPrintRange(QPrinter.PrintRange.PageRange)
    assert printer_pages(printer, 5) == [1, 2]
    printer.setPrintRange(QPrinter.PrintRange.CurrentPage)
    assert printer_pages(printer, 5, current_page=4) == [4]
    printer.setPrintRange(QPrinter.PrintRange.AllPages)
    assert printer_pages(printer, 3) == [0, 1, 2]


def test_page_sequence_copies_and_collation():
    assert page_sequence([0, 1], 1) == [0, 1]
    assert page_sequence([0, 1], 2, collate=True) == [0, 1, 0, 1]
    assert page_sequence([0, 1], 2, collate=False) == [0, 0, 1, 1]
    assert page_sequence([3], 0) == [3]


# -- geometry ------------------------------------------------------------------------


def test_fit_page_portrait_on_portrait_keeps_aspect_and_centres():
    target = QRectF(0, 0, 1000, 2000)
    rect, rotate = fit_page(*A4, target)
    assert not rotate
    assert rect.width() == pytest.approx(1000)
    assert rect.height() == pytest.approx(1000 * 842 / 595)
    assert rect.center().y() == pytest.approx(1000)
    assert rect.width() / rect.height() == pytest.approx(595 / 842)


def test_fit_page_landscape_on_portrait_rotates():
    target = QRectF(50, 50, 1000, 1400)
    rect, rotate = fit_page(842, 595, target)
    assert rotate
    # Rotated page has portrait aspect 595:842; 1000/1400 is wider than that, so the
    # height is the limiting side.
    assert rect.width() / rect.height() == pytest.approx(595 / 842)
    assert rect.height() == pytest.approx(1400)
    assert rect.width() == pytest.approx(1400 * 595 / 842)
    assert target.contains(rect)


def test_fit_page_landscape_on_landscape_does_not_rotate():
    rect, rotate = fit_page(842, 595, QRectF(0, 0, 1400, 1000))
    assert not rotate
    assert rect.width() / rect.height() == pytest.approx(842 / 595)
    assert rect.height() <= 1000 + 1e-6


def test_fit_page_square_never_rotates():
    _, rotate = fit_page(500, 500, QRectF(0, 0, 100, 300))
    assert not rotate


def test_render_dpi_is_capped():
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    assert printer.resolution() > MAX_PRINT_DPI
    assert render_dpi(printer) == MAX_PRINT_DPI
    printer.setResolution(150)
    assert render_dpi(printer) == 150


# -- rendering into a PDF printer --------------------------------------------------------


def test_render_pages_writes_selected_pages(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf", [A4] * 5)
    out = tmp_path / "out.pdf"
    printer = _pdf_printer(out)
    printed = render_pages(printer, str(src), selected_pages("range", 5, from_page=2, to_page=4))
    assert printed == 3
    assert _page_count(out) == 3


def test_render_pages_output_has_content(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf", [A4])
    out = tmp_path / "out.pdf"
    assert render_pages(_pdf_printer(out), str(src), [0]) == 1
    doc = fitz.open(str(out))
    try:
        assert doc[0].get_images(), "page image was not drawn"
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
        # Centre of the page is the blue fill, not blank paper.
        r, g, b = pix.pixel(pix.width // 2, pix.height // 2)
        assert b > r and b > 150
    finally:
        doc.close()


def test_render_pages_landscape_page_is_rotated_onto_portrait_paper(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf", [A4, (842.0, 595.0)])
    out = tmp_path / "out.pdf"
    printer = _pdf_printer(out)
    assert render_pages(printer, str(src), [0, 1]) == 2
    doc = fitz.open(str(out))
    try:
        assert doc.page_count == 2
        for page in doc:
            assert page.rect.height > page.rect.width  # paper stays portrait
            (info,) = page.get_image_info()
            bbox = fitz.Rect(info["bbox"])
            assert bbox.height > bbox.width  # landscape content turned to fit
    finally:
        doc.close()


def test_render_pages_grayscale(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf", [A4])
    out = tmp_path / "out.pdf"
    printer = _pdf_printer(out)
    printer.setColorMode(QPrinter.ColorMode.GrayScale)
    assert render_pages(printer, str(src), [0]) == 1
    doc = fitz.open(str(out))
    try:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
        r, g, b = pix.pixel(pix.width // 2, pix.height // 2)
        assert abs(r - b) <= 2 and abs(r - g) <= 2
    finally:
        doc.close()


def test_render_pages_skips_out_of_range_and_empty(tmp_path):
    src = _make_pdf(tmp_path / "in.pdf", [A4] * 2)
    out = tmp_path / "out.pdf"
    assert render_pages(_pdf_printer(out), str(src), []) == 0
    assert render_pages(_pdf_printer(out), str(src), [1, 7]) == 1
    assert _page_count(out) == 1


def test_render_pages_encrypted(tmp_path):
    src = _make_pdf(tmp_path / "locked.pdf", [A4] * 2, password="pw")
    out = tmp_path / "out.pdf"
    with pytest.raises(PermissionError):
        render_pages(_pdf_printer(out), str(src), [0])
    assert render_pages(_pdf_printer(out), str(src), [0, 1], password="pw") == 2
    assert _page_count(out) == 2


# -- print_document with a mocked dialog ------------------------------------------------


def _fake_exec(out: Path, configure=None, result=QDialog.DialogCode.Accepted):
    seen = {}

    def fake(self):
        printer = self.printer()
        seen["min_max"] = (self.minPage(), self.maxPage())
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(out))
        if configure:
            configure(printer)
        return result

    return fake, seen


def test_print_document_all_pages(tmp_path, monkeypatch):
    src = _make_pdf(tmp_path / "in.pdf", [A4] * 3)
    out = tmp_path / "printed.pdf"
    fake, seen = _fake_exec(out)
    monkeypatch.setattr(QPrintDialog, "exec", fake)
    assert print_document(None, str(src)) is True
    assert seen["min_max"] == (1, 3)
    assert _page_count(out) == 3


def test_print_document_current_page(tmp_path, monkeypatch):
    src = _make_pdf(tmp_path / "in.pdf", [A4] * 3)
    out = tmp_path / "printed.pdf"
    calls = []
    real = printing.render_pages
    monkeypatch.setattr(
        printing, "render_pages",
        lambda printer, path, pages, pw=None: calls.append(list(pages)) or real(
            printer, path, pages, pw
        ),
    )
    fake, _ = _fake_exec(out, lambda p: p.setPrintRange(QPrinter.PrintRange.CurrentPage))
    monkeypatch.setattr(QPrintDialog, "exec", fake)
    assert print_document(None, str(src), current_page=2) is True
    assert calls == [[2]]
    assert _page_count(out) == 1


def test_print_document_copies_are_made_for_pdf_output(tmp_path, monkeypatch):
    src = _make_pdf(tmp_path / "in.pdf", [A4] * 2)
    out = tmp_path / "printed.pdf"

    def configure(printer):
        printer.setCopyCount(2)

    fake, _ = _fake_exec(out, configure)
    monkeypatch.setattr(QPrintDialog, "exec", fake)
    assert print_document(None, str(src)) is True
    printer = _pdf_printer(tmp_path / "probe.pdf")
    expected = 4 if not printer.supportsMultipleCopies() else 2
    assert _page_count(out) == expected


def test_print_document_cancelled(tmp_path, monkeypatch):
    src = _make_pdf(tmp_path / "in.pdf", [A4] * 2)
    out = tmp_path / "printed.pdf"
    fake, _ = _fake_exec(out, result=QDialog.DialogCode.Rejected)
    monkeypatch.setattr(QPrintDialog, "exec", fake)
    assert print_document(None, str(src)) is False
    assert not out.exists()


def test_print_document_encrypted(tmp_path, monkeypatch):
    src = _make_pdf(tmp_path / "locked.pdf", [A4] * 2, password="pw")
    out = tmp_path / "printed.pdf"
    fake, _ = _fake_exec(out)
    monkeypatch.setattr(QPrintDialog, "exec", fake)
    with pytest.raises(PermissionError):
        print_document(None, str(src))
    assert print_document(None, str(src), password="pw") is True
    assert _page_count(out) == 2
