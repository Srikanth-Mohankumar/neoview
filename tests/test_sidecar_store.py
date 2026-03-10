import json
import os
from pathlib import Path

from neoview.models.view_state import ANNOTATION_TYPES, AnnotationRecord, BookmarkRecord, DocumentSidecarState
from neoview.persistence.sidecar_store import (
    SCHEMA_VERSION,
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
    assert loaded.version == SCHEMA_VERSION
    assert len(loaded.annotations) == 1
    assert len(loaded.bookmarks) == 1
    assert loaded.annotations[0].id == "ann-1"
    assert loaded.bookmarks[0].title == "Intro"

    # Ensure JSON is valid and versioned.
    payload = json.loads((tmp_path / "sample.pdf.neoview.json").read_text(encoding="utf-8"))
    assert payload["version"] == SCHEMA_VERSION


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


def test_all_annotation_types_round_trip(tmp_path):
    """Every ANNOTATION_TYPES value should survive a save/load cycle."""
    pdf_path = tmp_path / "multi.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    annotations = []
    for i, t in enumerate(sorted(ANNOTATION_TYPES)):
        rec = AnnotationRecord(
            id=f"ann-{i}",
            type=t,
            page=0,
            rect=(float(i), 0.0, 10.0, 10.0),
            color="#ff0000",
            opacity=0.5,
            contents=f"test {t}",
            border_width=2.5,
            font_size=14.0,
            points=[[1.0, 2.0], [3.0, 4.0]] if t == "freehand" else [],
        )
        annotations.append(rec)

    state = DocumentSidecarState(annotations=annotations)
    save_sidecar(str(pdf_path), state)
    loaded = load_sidecar(str(pdf_path))

    assert len(loaded.annotations) == len(ANNOTATION_TYPES)
    for rec in loaded.annotations:
        assert rec.type in ANNOTATION_TYPES
        assert rec.opacity == 0.5
        assert rec.border_width == 2.5
        assert rec.font_size == 14.0

    freehand_rec = next(r for r in loaded.annotations if r.type == "freehand")
    assert freehand_rec.points == [[1.0, 2.0], [3.0, 4.0]]


def test_unknown_annotation_type_is_dropped(tmp_path):
    """Types not in ANNOTATION_TYPES should be silently discarded on load."""
    pdf_path = tmp_path / "unk.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    sidecar_file = tmp_path / "unk.pdf.neoview.json"
    sidecar_file.write_text(
        json.dumps({
            "version": SCHEMA_VERSION,
            "annotations": [
                {"id": "x1", "type": "stamp", "page": 0, "rect": [0, 0, 10, 10]},
                {"id": "x2", "type": "highlight", "page": 0, "rect": [0, 0, 10, 10]},
            ],
            "bookmarks": [],
        }),
        encoding="utf-8",
    )
    loaded = load_sidecar(str(pdf_path))
    assert len(loaded.annotations) == 1
    assert loaded.annotations[0].id == "x2"


def test_annotation_record_extra_fields_preserved(tmp_path):
    """Extra dict and new fields (border_color, border_width) survive round-trip."""
    pdf_path = tmp_path / "extra.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    rec = AnnotationRecord(
        id="e1",
        type="rectangle",
        page=0,
        rect=(5.0, 5.0, 50.0, 30.0),
        color="#00ff00",
        border_color="#0000ff",
        border_width=3.0,
        extra={"custom": "value"},
    )
    state = DocumentSidecarState(annotations=[rec])
    save_sidecar(str(pdf_path), state)
    loaded = load_sidecar(str(pdf_path))

    assert loaded.annotations[0].border_color == "#0000ff"
    assert loaded.annotations[0].border_width == 3.0
    assert loaded.annotations[0].extra == {"custom": "value"}


def test_save_sidecar_write_error_is_fail_soft(tmp_path: Path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    state = DocumentSidecarState(
        annotations=[AnnotationRecord(id="ann-1", type="highlight", page=0, rect=(0, 0, 1, 1))]
    )

    def broken_replace(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)

    # Should not raise on write/replace failure.
    save_sidecar(str(pdf_path), state)
