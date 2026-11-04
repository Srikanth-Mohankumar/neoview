"""Extract ordered page ranges without modifying the source PDF or its sidecar."""
from __future__ import annotations

import os
import re
from pathlib import Path

import fitz

from neoview.models.page_organization import PageOrganization
from neoview.models.view_state import DocumentSidecarState
from neoview.persistence.sidecar_store import sidecar_path_for


def parse_page_ranges(text: str, page_count: int) -> list[int]:
    """Parse one-based inclusive ranges into ordered zero-based page indices.

    Comma-separated groups preserve their entered order; duplicates and descending
    ranges are rejected rather than silently changing the requested extraction.
    """
    if page_count < 1:
        raise ValueError("Open a nonempty PDF first.")
    if not text.strip():
        raise ValueError("Enter page numbers or ranges, for example 1-3, 5.")
    pages = []
    seen = set()
    for group in text.split(","):
        match = re.fullmatch(r"\s*([0-9]+)\s*(?:-\s*([0-9]+)\s*)?", group)
        if match is None:
            raise ValueError("Use comma-separated page numbers or ranges, for example 1-3, 5.")
        start = int(match[1])
        end = int(match[2] or match[1])
        if not 1 <= start <= end <= page_count:
            raise ValueError(f"Page ranges must run forwards and stay between 1 and {page_count}.")
        for number in range(start, end + 1):
            if number in seen:
                raise ValueError(f"Page {number} was selected more than once.")
            seen.add(number)
            pages.append(number - 1)
    return pages


def _same_path(first: str, second: str) -> bool:
    if os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second)):
        return True
    try:
        return os.path.samefile(first, second)
    except FileNotFoundError:
        return False


def validate_extraction_destination(source_path: str, output_path: str) -> str:
    """Reject aliases of either source file, including symlinks and hard links."""
    if not output_path:
        raise ValueError("Choose a destination PDF.")
    output = str(Path(output_path).absolute())
    source_files = [source_path, sidecar_path_for(source_path)]
    output_files = [output, sidecar_path_for(output)]
    if any(_same_path(src, dest) for src in source_files for dest in output_files):
        raise ValueError("Save the extracted PDF separately from the original PDF and its sidecar.")
    if _same_path(*output_files):
        raise ValueError("The output PDF and sidecar must be separate files.")
    return output


def extract_pdf_pages(
    document: fitz.Document,
    source_path: str,
    state: DocumentSidecarState,
    ranges: str,
    output_path: str,
) -> str:
    """Write a PDF and remapped sidecar; return the absolute saved PDF path.

    Native annotations, links, outlines, and editable NeoView records follow the
    selected pages. Password-protected PDFs are refused by the isolated session.
    """
    session = PageOrganization(document, state)
    try:
        return save_extraction(session, source_path, ranges, output_path)
    finally:
        session.close()


def save_extraction(
    session: PageOrganization, source_path: str, ranges: str, output_path: str,
) -> str:
    """Save an extraction from an isolated, caller-owned session."""
    pages = parse_page_ranges(ranges, session.document.page_count)
    output = validate_extraction_destination(source_path, output_path)
    selected = set(pages)
    removed = [idx for idx in session.order if idx not in selected]
    if removed:
        session.delete(removed)
    session.reorder(pages)
    session.save(output)
    return output
