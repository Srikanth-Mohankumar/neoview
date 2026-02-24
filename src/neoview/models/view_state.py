"""Typed records used by UI state and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


RectTuple = Tuple[float, float, float, float]


@dataclass
class AnnotationRecord:
    """Application-side annotation item."""

    id: str
    type: str
    page: int
    rect: RectTuple
    color: str = "#f7c948"
    opacity: float = 0.25
    contents: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class BookmarkRecord:
    """User bookmark entry."""

    id: str
    title: str
    page: int
    y: float
    created_at: str = ""


@dataclass
class DocumentSidecarState:
    """On-disk sidecar payload."""

    version: int = 1
    annotations: List[AnnotationRecord] = field(default_factory=list)
    bookmarks: List[BookmarkRecord] = field(default_factory=list)


@dataclass
class SearchMatch:
    """Single search hit with UI preview."""

    page_idx: int
    rect: RectTuple
    snippet: str


@dataclass
class TabContext:
    """Per-tab mutable state."""

    file_path: Optional[str] = None
    search_query: str = ""
    search_index: int = -1
    search_results: List[SearchMatch] = field(default_factory=list)
    sidecar_state: DocumentSidecarState = field(default_factory=DocumentSidecarState)
    sidecar_error: str = ""
