"""Persistence helpers for document sidecar state."""

from .sidecar_store import (
    clamp_sidecar_for_page_count,
    load_sidecar,
    save_sidecar,
    sidecar_path_for,
)

__all__ = [
    "clamp_sidecar_for_page_count",
    "load_sidecar",
    "save_sidecar",
    "sidecar_path_for",
]
