"""Load/save JSON sidecar state for annotations and bookmarks."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from neoview.models.view_state import (
    ANNOTATION_TYPES,
    AnnotationRecord,
    BookmarkRecord,
    DocumentSidecarState,
)


SCHEMA_VERSION = 2


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sidecar_path_for(pdf_path: str) -> str:
    """Return sidecar location for a PDF file."""
    return f"{os.path.abspath(pdf_path)}.neoview.json"


def _coerce_rect(value: Any) -> Optional[tuple[float, float, float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, w, h = (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    except (TypeError, ValueError):
        return None
    if w < 0:
        w = 0.0
    if h < 0:
        h = 0.0
    return (x, y, w, h)


def _coerce_points(value: Any) -> List[List[float]]:
    """Coerce a raw value to a list of [x, y] float pairs."""
    if not isinstance(value, list):
        return []
    result = []
    for pt in value:
        if isinstance(pt, (list, tuple)) and len(pt) >= 2:
            try:
                result.append([float(pt[0]), float(pt[1])])
            except (TypeError, ValueError):
                pass
    return result


def _annotation_from_dict(item: Dict[str, Any]) -> Optional[AnnotationRecord]:
    if not isinstance(item, dict):
        return None
    rect = _coerce_rect(item.get("rect"))
    if rect is None:
        return None
    try:
        page = int(item.get("page", 0))
    except (TypeError, ValueError):
        return None
    if page < 0:
        return None

    kind = str(item.get("type", "")).strip().lower()
    if kind not in ANNOTATION_TYPES:
        return None

    aid = str(item.get("id", "")).strip()
    if not aid:
        return None

    color = str(item.get("color", "#f7c948")).strip() or "#f7c948"
    try:
        opacity = float(item.get("opacity", 0.25))
    except (TypeError, ValueError):
        opacity = 0.25
    opacity = max(0.0, min(1.0, opacity))

    try:
        border_width = float(item.get("border_width", 2.0))
    except (TypeError, ValueError):
        border_width = 2.0
    border_width = max(0.5, min(20.0, border_width))

    try:
        font_size = float(item.get("font_size", 12.0))
    except (TypeError, ValueError):
        font_size = 12.0
    font_size = max(6.0, min(72.0, font_size))

    border_color = str(item.get("border_color") or "").strip()
    points = _coerce_points(item.get("points", []))
    extra = item.get("extra", {})
    if not isinstance(extra, dict):
        extra = {}

    created = str(item.get("created_at") or _utc_now_iso())
    updated = str(item.get("updated_at") or created)
    contents = str(item.get("contents") or "")

    return AnnotationRecord(
        id=aid,
        type=kind,
        page=page,
        rect=rect,
        color=color,
        opacity=opacity,
        contents=contents,
        created_at=created,
        updated_at=updated,
        border_color=border_color,
        border_width=border_width,
        font_size=font_size,
        points=points,
        extra=extra,
    )


def _bookmark_from_dict(item: Dict[str, Any]) -> Optional[BookmarkRecord]:
    if not isinstance(item, dict):
        return None
    bid = str(item.get("id", "")).strip()
    title = str(item.get("title", "")).strip()
    if not bid or not title:
        return None
    try:
        page = int(item.get("page", 0))
        y = float(item.get("y", 0.0))
    except (TypeError, ValueError):
        return None
    if page < 0:
        return None
    if y < 0:
        y = 0.0

    created = str(item.get("created_at") or _utc_now_iso())
    return BookmarkRecord(id=bid, title=title, page=page, y=y, created_at=created)


def _annotation_to_dict(record: AnnotationRecord) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "id": record.id,
        "type": record.type,
        "page": int(record.page),
        "rect": [float(record.rect[0]), float(record.rect[1]), float(record.rect[2]), float(record.rect[3])],
        "color": record.color,
        "opacity": float(record.opacity),
        "contents": record.contents,
        "created_at": record.created_at or _utc_now_iso(),
        "updated_at": record.updated_at or _utc_now_iso(),
    }
    if record.border_color:
        d["border_color"] = record.border_color
    if record.border_width != 2.0:
        d["border_width"] = float(record.border_width)
    if record.font_size != 12.0:
        d["font_size"] = float(record.font_size)
    if record.points:
        d["points"] = [[float(p[0]), float(p[1])] for p in record.points]
    if record.extra:
        d["extra"] = record.extra
    return d


def _bookmark_to_dict(record: BookmarkRecord) -> Dict[str, Any]:
    return {
        "id": record.id,
        "title": record.title,
        "page": int(record.page),
        "y": float(record.y),
        "created_at": record.created_at or _utc_now_iso(),
    }


def _rename_broken(path: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    broken_path = f"{path}.broken.{stamp}"
    try:
        os.replace(path, broken_path)
    except OSError:
        # Fail-soft: keep original file untouched if rename fails.
        return


def _iter_records(source: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(source, list):
        return []
    return [item for item in source if isinstance(item, dict)]


def load_sidecar(pdf_path: str) -> DocumentSidecarState:
    """Load sidecar state for a document. Malformed files fail-soft to empty state."""
    path = sidecar_path_for(pdf_path)
    if not os.path.exists(path):
        return DocumentSidecarState(version=SCHEMA_VERSION)

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        _rename_broken(path)
        return DocumentSidecarState(version=SCHEMA_VERSION)

    if not isinstance(payload, dict):
        _rename_broken(path)
        return DocumentSidecarState(version=SCHEMA_VERSION)

    version = payload.get("version", SCHEMA_VERSION)
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = SCHEMA_VERSION

    annotations = []
    for item in _iter_records(payload.get("annotations", [])):
        parsed = _annotation_from_dict(item)
        if parsed is not None:
            annotations.append(parsed)

    bookmarks = []
    for item in _iter_records(payload.get("bookmarks", [])):
        parsed = _bookmark_from_dict(item)
        if parsed is not None:
            bookmarks.append(parsed)

    return DocumentSidecarState(version=version or SCHEMA_VERSION, annotations=annotations, bookmarks=bookmarks)


def save_sidecar(pdf_path: str, state: DocumentSidecarState) -> None:
    """Persist sidecar state atomically."""
    path = sidecar_path_for(pdf_path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    payload = {
        "version": SCHEMA_VERSION,
        "annotations": [_annotation_to_dict(item) for item in state.annotations],
        "bookmarks": [_bookmark_to_dict(item) for item in state.bookmarks],
    }

    fd, tmp_path = tempfile.mkstemp(prefix=".neoview.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def clamp_sidecar_for_page_count(state: DocumentSidecarState, page_count: int) -> DocumentSidecarState:
    """Drop out-of-range entries after document page count changes."""
    if page_count <= 0:
        return DocumentSidecarState(version=state.version)
    annotations = [item for item in state.annotations if 0 <= item.page < page_count]
    bookmarks = [item for item in state.bookmarks if 0 <= item.page < page_count]
    return DocumentSidecarState(version=state.version, annotations=annotations, bookmarks=bookmarks)
