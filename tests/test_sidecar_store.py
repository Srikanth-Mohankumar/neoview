import json
from pathlib import Path

from neoview.models.view_state import AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import (
    clamp_sidecar_for_page_count,
    load_sidecar,
    save_sidecar,
    sidecar_path_for,
)


def test_sidecar_path_for():
    path = sidecar_path_for("/tmp/demo.pdf")
    assert path.endswith("demo.pdf.neoview.json")


def test_sidecar_round_trip(tmp_path: Path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    state = DocumentSidecarState(
        annotations=[
            AnnotationRecord(
                id="ann-1",
                type="highlight",
                page=0,
                rect=(10.0, 20.0, 30.0, 40.0),
                contents="hello",
            )
        ],
        bookmarks=[BookmarkRecord(id="bm-1", title="Intro", page=0, y=100.0)],
    )
    save_sidecar(str(pdf_path), state)

    loaded = load_sidecar(str(pdf_path))
    assert loaded.version == 1
    assert len(loaded.annotations) == 1
    assert len(loaded.bookmarks) == 1
    assert loaded.annotations[0].id == "ann-1"
    assert loaded.bookmarks[0].title == "Intro"

    # Ensure JSON is valid and versioned.
    payload = json.loads((tmp_path / "sample.pdf.neoview.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1


def test_sidecar_corrupt_file_falls_back_and_renames(tmp_path: Path):
    pdf_path = tmp_path / "broken.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    sidecar = tmp_path / "broken.pdf.neoview.json"
    sidecar.write_text("{ not-json", encoding="utf-8")

    loaded = load_sidecar(str(pdf_path))
    assert loaded.annotations == []
    assert loaded.bookmarks == []

    broken_files = list(tmp_path.glob("broken.pdf.neoview.json.broken.*"))
    assert broken_files, "Corrupt sidecar should be renamed with .broken suffix."




def test_sidecar_load_accepts_extended_annotation_types(tmp_path: Path):
    pdf_path = tmp_path / "extended.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    payload = {
        "version": 1,
        "annotations": [
            {"id": "a1", "type": "strikeout", "page": 0, "rect": [0, 0, 10, 10]},
            {"id": "a2", "type": "squiggly", "page": 0, "rect": [0, 0, 10, 10]},
        ],
        "bookmarks": [],
    }
    (tmp_path / "extended.pdf.neoview.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_sidecar(str(pdf_path))
    assert [ann.type for ann in loaded.annotations] == ["strikeout", "squiggly"]

def test_clamp_sidecar_for_page_count():
    state = DocumentSidecarState(
        annotations=[
            AnnotationRecord(id="a1", type="highlight", page=0, rect=(0, 0, 10, 10)),
            AnnotationRecord(id="a2", type="note", page=4, rect=(0, 0, 10, 10)),
        ],
        bookmarks=[
            BookmarkRecord(id="b1", title="ok", page=1, y=5.0),
            BookmarkRecord(id="b2", title="drop", page=7, y=9.0),
        ],
    )
    clamped = clamp_sidecar_for_page_count(state, 3)
    assert [a.id for a in clamped.annotations] == ["a1"]
    assert [b.id for b in clamped.bookmarks] == ["b1"]
