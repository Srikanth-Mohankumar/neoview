from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from PySide6.QtWidgets import QFileDialog

from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import load_sidecar, save_sidecar
from neoview.ui.tools.split_pages import run, split_pdf


def make_pdf(path):
    with fitz.open() as document:
        for label in ("First", "Second", "Third"):
            document.new_page().insert_text((72, 72), label)
        document.set_metadata({"title": "Split source", "author": "Author"})
        document.set_toc([[1, "First", 1], [2, "Second", 2], [1, "Third", 3]])
        page = document[1]
        page.add_text_annot((25, 25), "Native note")
        document.save(str(path))


def state():
    return DocumentSidecarState(
        annotations=[AnnotationRecord("annotation", "note", 1, (10, 20, 30, 40))],
        bookmarks=[BookmarkRecord("bookmark", "Third", 2, 14)],
    )


def test_split_preserves_pages_metadata_native_annotations_and_remaps_state(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    records = state()
    save_sidecar(source, records)
    before_pdf = source.read_bytes()
    before_state = Path(str(source) + ".neoview.json").read_bytes()
    with fitz.open(source) as document:
        target = Path(split_pdf(document, records, str(source), str(tmp_path)))
        assert document.page_count == 3
    assert target == tmp_path / "source-split"
    assert len(list(target.iterdir())) == 6
    for index, label in enumerate(("First", "Second", "Third")):
        path = target / f"page-{index + 1:03d}.pdf"
        with fitz.open(path) as output:
            assert output.page_count == 1
            assert output[0].get_text().strip() == label
            assert output.metadata["title"] == "Split source"
            assert output.metadata["author"] == "Author"
            assert output.get_toc() == [[1, label, 1]]
            if index == 1:
                page = output[0]
                assert list(page.annots())[0].info["content"] == "Native note"
        result = load_sidecar(path)
        if index == 1:
            assert result.annotations[0].page == 0
        else:
            assert not result.annotations
        if index == 2:
            assert result.bookmarks[0].page == 0
            assert result.bookmarks[0].y == 14
        else:
            assert not result.bookmarks
    assert records.annotations[0].page == 1
    assert records.bookmarks[0].page == 2
    assert source.read_bytes() == before_pdf
    assert Path(str(source) + ".neoview.json").read_bytes() == before_state


def test_existing_destination_is_never_changed(tmp_path):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    target = tmp_path / "source-split"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep")
    with fitz.open(source) as document, pytest.raises(FileExistsError):
        split_pdf(document, state(), str(source), str(tmp_path))
    assert marker.read_text() == "keep"
    assert list(target.iterdir()) == [marker]
    assert not list(tmp_path.glob(".neoview-split-*"))


def test_failed_sidecar_staging_cleans_every_partial_output(tmp_path, monkeypatch):
    from neoview.ui.tools import split_pages

    source = tmp_path / "source.pdf"
    make_pdf(source)
    monkeypatch.setattr(split_pages, "save_sidecar", lambda *_: None)
    with fitz.open(source) as document, pytest.raises(OSError, match="stage"):
        split_pdf(document, state(), str(source), str(tmp_path))
    assert not (tmp_path / "source-split").exists()
    assert not list(tmp_path.glob(".neoview-split-*"))


def test_publish_failure_removes_reserved_directory(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    original_rename = Path.rename
    calls = []

    def fail_second(path, destination):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("publish failed")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_second)
    with fitz.open(source) as document, pytest.raises(OSError, match="publish failed"):
        split_pdf(document, state(), str(source), str(tmp_path))
    assert not (tmp_path / "source-split").exists()
    assert not list(tmp_path.glob(".neoview-split-*"))


def test_run_cancellation_does_not_write(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    with fitz.open(source) as document:
        window = SimpleNamespace(
            current_view=lambda: SimpleNamespace(document=document),
            current_context=lambda: SimpleNamespace(file_path=str(source), sidecar_state=state()),
        )
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_: "")
        assert run(window) is None
    assert list(tmp_path.glob("*.pdf")) == [source]
    assert not (tmp_path / "source-split").exists()
    assert not list(tmp_path.glob(".neoview-split-*"))


def test_run_uses_snapshot_when_viewer_reloads(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    make_pdf(source)
    document = fitz.open(source)
    records = state()
    window = SimpleNamespace(
        current_view=lambda: SimpleNamespace(document=document),
        current_context=lambda: SimpleNamespace(file_path=str(source), sidecar_state=records),
    )

    def choose(*_):
        document.close()
        records.annotations.clear()
        return str(tmp_path)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", choose)
    assert run(window) is None
    assert load_sidecar(tmp_path / "source-split" / "page-002.pdf").annotations[0].page == 0


def test_protected_pdf_rejected(tmp_path):
    source = tmp_path / "encrypted.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(str(source), encryption=fitz.PDF_ENCRYPT_AES_256,
                      owner_pw="owner", user_pw="reader")
    with fitz.open(source) as document:
        document.authenticate("reader")
        with pytest.raises(ValueError, match="password-protected"):
            split_pdf(document, state(), str(source), str(tmp_path))
    assert not (tmp_path / "encrypted-split").exists()


def test_concurrent_destination_creation_is_preserved(tmp_path, monkeypatch):
    source = tmp_path / "source.pdf"
    target = tmp_path / "source-split"
    make_pdf(source)
    original_mkdir = Path.mkdir

    def reserve(path, *args, **kwargs):
        if path == target:
            original_mkdir(path)
            (path / "other.txt").write_text("concurrent owner")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", reserve)
    with fitz.open(source) as document, pytest.raises(FileExistsError):
        split_pdf(document, state(), str(source), str(tmp_path))
    assert (target / "other.txt").read_text() == "concurrent owner"
    assert list(target.iterdir()) == [target / "other.txt"]
    assert not list(tmp_path.glob(".neoview-split-*"))
