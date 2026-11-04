from contextlib import contextmanager

import fitz
import pytest

from neoview.ui.tools import extract_images as tool


def image_pdf(path):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), False)
    pix.clear_with(127)
    image = pix.tobytes("png")
    with fitz.open() as doc:
        page = doc.new_page()
        xref = page.insert_image(fitz.Rect(10, 10, 50, 50), stream=image)
        page.insert_image(fitz.Rect(60, 10, 100, 50), xref=xref)
        doc.new_page().insert_image(fitz.Rect(10, 10, 50, 50), xref=xref)
        doc.save(path)
    return xref


def test_extract_unique_resources_preserves_bytes_and_source(tmp_path):
    source = tmp_path / "source.pdf"
    xref = image_pdf(source)
    before = source.read_bytes()
    destination = tmp_path / "source-images"
    with fitz.open(source) as document:
        expected = document.extract_image(xref)
        assert tool.image_xrefs(document) == [xref]
        paths = tool.extract_embedded_images(document, str(destination))
    assert [p.name for p in paths] == [f"image-0001-xref-{xref}.{expected['ext']}"]
    assert paths[0].read_bytes() == expected["image"]
    assert source.read_bytes() == before
    assert not list(tmp_path.glob(".neoview-images-*"))


def test_existing_destination_is_untouched(tmp_path):
    source = tmp_path / "source.pdf"
    image_pdf(source)
    target = tmp_path / "existing"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep")
    with fitz.open(source) as doc, pytest.raises(FileExistsError):
        tool.extract_embedded_images(doc, str(target))
    assert sentinel.read_text() == "keep"


def test_empty_pdf_has_no_output(tmp_path):
    with fitz.open() as doc:
        doc.new_page()
        assert tool.extract_embedded_images(doc, str(tmp_path / "empty-images")) == []
    assert not (tmp_path / "empty-images").exists()


def test_extraction_failure_cleans_staging(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    image_pdf(source)
    target = tmp_path / "images"
    with fitz.open(source) as doc:
        monkeypatch.setattr(doc, "extract_image", lambda *_: {"ext": "../bad", "image": b"x"})
        with pytest.raises(ValueError, match="extension"):
            tool.extract_embedded_images(doc, str(target))
    assert not target.exists()
    assert not list(tmp_path.glob(".neoview-images-*"))


def test_publish_failure_removes_new_output(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    image_pdf(source)
    target = tmp_path / "images"
    monkeypatch.setattr(tool.os, "rename", lambda *_: (_ for _ in ()).throw(OSError("write failed")))
    with fitz.open(source) as doc, pytest.raises(OSError, match="write failed"):
        tool.extract_embedded_images(doc, str(target))
    assert not target.exists()
    assert not list(tmp_path.glob(".neoview-images-*"))


def mock_snapshot(monkeypatch, document, source):
    @contextmanager
    def fake(_window):
        yield document, None, str(source)
    monkeypatch.setattr(tool, "snapshot", fake)


def test_run_cancellation_does_not_create_output(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    image_pdf(source)
    monkeypatch.setattr(tool.QFileDialog, "getExistingDirectory", lambda *_: "")
    with fitz.open(source) as doc:
        mock_snapshot(monkeypatch, doc, source)
        assert tool.run(None) is None
    assert not (tmp_path / "source-images").exists()


def test_run_empty_pdf_informs_without_prompt(tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(tool.QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(tool.QFileDialog, "getExistingDirectory", lambda *_: pytest.fail("unexpected prompt"))
    with fitz.open() as doc:
        doc.new_page()
        mock_snapshot(monkeypatch, doc, tmp_path / "empty.pdf")
        tool.run(None)
    assert messages == ["This PDF has no embedded images."]


def test_run_extracts_into_named_child(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    image_pdf(source)
    messages = []
    monkeypatch.setattr(tool.QMessageBox, "information", lambda *args: messages.append(args[2]))
    monkeypatch.setattr(tool.QFileDialog, "getExistingDirectory", lambda *_: str(tmp_path))
    with fitz.open(source) as doc:
        mock_snapshot(monkeypatch, doc, source)
        assert tool.run(None) is None
    assert len(list((tmp_path / "source-images").iterdir())) == 1
    assert "Saved 1" in messages[0]


def test_extracts_soft_mask_as_separate_resource(tmp_path):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), True)
    pix.clear_with(127)
    with fitz.open() as doc:
        doc.new_page().insert_image(fitz.Rect(10, 10, 50, 50), stream=pix.tobytes("png"))
        resources = doc.get_page_images(0, full=True)[0]
        assert resources[1] > 0
        paths = tool.extract_embedded_images(doc, str(tmp_path / "images"))
        assert len(paths) == 2
        assert {path.read_bytes() for path in paths} == {
            doc.extract_image(xref)["image"] for xref in resources[:2]
        }
