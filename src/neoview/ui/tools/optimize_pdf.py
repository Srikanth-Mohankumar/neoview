"""Save a losslessly compressed PDF copy without changing the source."""
from __future__ import annotations

from neoview.ui.tool_support import choose_file, save_copy, snapshot


def optimize_pdf(document, state, source_path: str, output_path: str) -> str:
    """Save with garbage collection and lossless stream compression.

    Content, metadata, native annotations, outlines and editable sidecar records
    are retained. Already optimized inputs may not become smaller.
    """
    return save_copy(document, state, source_path, output_path)


def run(window) -> str | None:
    """Ask for a separate output PDF and return its path after successful saving."""
    with snapshot(window, unprotected=True) as (document, state, source):
        target = choose_file(window, source, "-optimized", ".pdf", "Save Optimized PDF")
        if not target:
            return None
        return optimize_pdf(document, state, source, target)
