"""Preserve detailed outline destinations across edits that retain page xrefs."""
from __future__ import annotations

import copy

import fitz


def capture_outline(document):
    """Capture detailed rows and original PDF action/style fields before editing."""
    toc = document.get_toc(simple=False)
    keys = [
        {key: document.xref_get_key(xref, key)[1] for key in ("A", "Dest", "C", "F", "Count")}
        for xref in document.get_outline_xrefs()
    ]
    if len(toc) != len(keys):
        raise ValueError("The PDF outline cannot be read without losing destinations.")
    return toc, keys


def write_preserved_outline(document, toc, original_keys):
    """Install rows, preserving original raw actions when supplied for a row.

    Existing page xrefs must remain unchanged. Raw actions preserve named targets
    and remote destination details unsupported by some PyMuPDF TOC writers.
    A None key entry denotes a newly created local outline destination.
    """
    rows = []
    for row, keys in zip(toc, original_keys):
        entry = copy.deepcopy(row)
        destination = entry[3]
        if keys is not None and destination.get("kind") != fitz.LINK_GOTO:
            style = {key: destination[key] for key in ("color", "bold", "italic", "collapse")
                     if key in destination}
            entry[2:] = [-1, {"kind": fitz.LINK_NONE, **style}]
        rows.append(entry)
    document.set_toc(rows)
    for xref, keys in zip(document.get_outline_xrefs(), original_keys):
        if keys is not None:
            for key, value in keys.items():
                document.xref_set_key(xref, key, value)


def remap_retained_outline(document, toc, original_keys, mapping):
    """Map known local pages, retain nonlocal entries and normalize orphan levels."""
    rows = []
    kept_keys = []
    previous_level = 0
    for row, keys in zip(toc, original_keys):
        entry = copy.deepcopy(row)
        destination = entry[3]
        if destination.get("kind") == fitz.LINK_GOTO:
            original_page = destination.get("page", entry[2] - 1)
            if original_page not in mapping:
                continue
            destination["page"] = mapping[original_page]
            entry[2] = mapping[original_page] + 1
        entry[0] = min(entry[0], previous_level + 1)
        previous_level = entry[0]
        rows.append(entry)
        kept_keys.append(keys)
    if len(rows) != len(toc):
        # Deleted entries can change their ancestors' child counts. Let the new
        # outline tree compute valid counts instead of restoring stale values.
        kept_keys = [{key: value for key, value in keys.items() if key != "Count"}
                     for keys in kept_keys]
    write_preserved_outline(document, rows, kept_keys)
