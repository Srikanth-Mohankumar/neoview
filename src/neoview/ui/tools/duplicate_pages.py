"""Duplicate selected pages in a separately saved PDF and remap editable records."""
from __future__ import annotations

import copy
import uuid
from dataclasses import replace

import fitz
from PySide6.QtWidgets import QInputDialog

from neoview.models.outline_preservation import capture_outline, write_preserved_outline
from neoview.models.page_extraction import parse_page_ranges
from neoview.ui.tool_support import choose_file, save_copy, snapshot

SIDECAR_LIMITS = {"annotations": 10_000, "bookmarks": 5_000}


def _duplicate_toc(output, toc, original_positions, copy_positions, original_keys):
    """Keep original outline actions lossless and append remapped local copies.

    Reusing raw original actions also preserves URI, named and remote destinations
    that PyMuPDF's detailed-TOC writer cannot round-trip on every supported version.
    Original page xrefs stay unchanged when physical copies are inserted.
    """
    remapped = []
    for row in toc:
        entry = copy.deepcopy(row)
        destination = entry[3]
        if destination.get("kind") == fitz.LINK_GOTO:
            page = destination.get("page", entry[2] - 1)
            if page in original_positions:
                entry[2] = original_positions[page] + 1
                destination["page"] = original_positions[page]
                remapped.append(entry)
                continue
        remapped.append(entry)
    previous_level = 0
    for row in toc:
        level, title, page, destination = copy.deepcopy(row)
        if destination.get("kind") != fitz.LINK_GOTO or page - 1 not in copy_positions:
            continue
        level = min(level, previous_level + 1)
        destination.pop("xref", None)
        destination["page"] = copy_positions[page - 1]
        remapped.append([level, title + " (copy)", copy_positions[page - 1] + 1, destination])
        previous_level = level
    write_preserved_outline(output, remapped, original_keys + [None] * (len(remapped) - len(toc)))


def duplicate_pdf(document, source, state, ranges, target):
    """Append selected copies after their last selected original; retain entered order."""
    if (document.needs_pass or document.is_encrypted
            or (document.metadata or {}).get("encryption")):
        raise ValueError("Duplicating pages does not support password-protected PDFs.")
    selected = parse_page_ranges(ranges, document.page_count)
    insert_at = max(selected) + 1
    original_positions = {
        page: page if page < insert_at else page + len(selected)
        for page in range(document.page_count)
    }
    copy_positions = {page: insert_at + offset for offset, page in enumerate(selected)}
    # Sidecar loading caps records. Refuse an operation that would otherwise
    # appear successful but silently lose duplicated records after reopening.
    for kind, limit in SIDECAR_LIMITS.items():
        records = getattr(state, kind)
        count = sum(record.page in original_positions for record in records)
        count += sum(record.page in copy_positions for record in records)
        if count > limit:
            raise ValueError(f"Duplicating these pages would exceed {limit} {kind}.")
    remapped = copy.deepcopy(state)
    for kind in ("annotations", "bookmarks"):
        records = getattr(state, kind)
        originals = [replace(record, page=original_positions[record.page]) for record in records
                     if record.page in original_positions]
        duplicates = [replace(record, id=uuid.uuid4().hex, page=copy_positions[record.page])
                      for record in records if record.page in copy_positions]
        setattr(remapped, kind, originals + duplicates)
    with fitz.open(stream=document.tobytes(), filetype="pdf") as output:
        toc, original_keys = capture_outline(output)
        # Insert real page copies: select() can repeat the same page xref,
        # making outline destinations resolve to the original occurrence.
        for offset, page in enumerate(selected):
            output.insert_pdf(document, from_page=page, to_page=page,
                              start_at=insert_at + offset)
        # A one-page insert drops links to pages outside that slice. Recreate
        # copied links against the duplicated group (or retained originals).
        for page, destination in copy_positions.items():
            copied_page = output[destination]
            for link in copied_page.get_links():
                copied_page.delete_link(link)
            for link in document[page].get_links():
                link = dict(link)
                link.pop("xref", None)
                link.pop("id", None)
                if link["kind"] == fitz.LINK_GOTO:
                    target_page = link.get("page", -1)
                    if target_page not in original_positions:
                        continue
                    link["page"] = copy_positions.get(target_page, original_positions[target_page])
                copied_page.insert_link(link)
        _duplicate_toc(output, toc, original_positions, copy_positions, original_keys)
        return save_copy(output, remapped, source, target)


def run(window):
    with snapshot(window, unprotected=True) as (document, state, source):
        ranges, accepted = QInputDialog.getText(
            window, "Duplicate Pages",
            f"Pages to duplicate (1-{document.page_count}), for example 1-3, 5:\n"
            "Copies are inserted after the last selected original page.",
        )
        if not accepted:
            return None
        parse_page_ranges(ranges, document.page_count)
        target = choose_file(window, source, "-duplicated", ".pdf", "Save Duplicated PDF")
        if not target:
            return None
        return duplicate_pdf(document, source, state, ranges, target)
