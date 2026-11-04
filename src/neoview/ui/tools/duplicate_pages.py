"""Duplicate selected pages in a separately saved PDF and remap editable records."""
from __future__ import annotations

import copy
import uuid
from dataclasses import replace

import fitz
from PySide6.QtWidgets import QInputDialog

from neoview.models.page_extraction import parse_page_ranges
from neoview.ui.tool_support import choose_file, save_copy, snapshot


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
    remapped = copy.deepcopy(state)
    for kind in ("annotations", "bookmarks"):
        records = getattr(state, kind)
        originals = [replace(record, page=original_positions[record.page]) for record in records
                     if record.page in original_positions]
        duplicates = [replace(record, id=uuid.uuid4().hex, page=copy_positions[record.page])
                      for record in records if record.page in copy_positions]
        setattr(remapped, kind, originals + duplicates)
    with fitz.open(stream=document.tobytes(), filetype="pdf") as output:
        toc = output.get_toc()
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
        remapped_toc = [[level, title, original_positions[page - 1] + 1]
                        for level, title, page in toc if page - 1 in original_positions]
        previous_level = 0
        for level, title, page in toc:
            if page - 1 not in copy_positions:
                continue
            level = min(level, previous_level + 1)
            remapped_toc.append([level, title + " (copy)", copy_positions[page - 1] + 1])
            previous_level = level
        output.set_toc(remapped_toc)
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
