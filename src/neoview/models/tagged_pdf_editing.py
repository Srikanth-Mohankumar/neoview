"""Conservative edits for existing structure tags on caller-owned PDF copies.

These helpers mutate the supplied document in memory. The caller must supply a
private writable copy and provide an explicit Save Copy workflow; opening and
saving the source document is deliberately outside this module.
"""
from __future__ import annotations

import re

import fitz

from neoview.models.tagged_pdf import _Name, _Parser, _Ref, inspect_tagged_pdf

STANDARD_ROLES = frozenset({
    "Document", "Part", "Art", "Sect", "Div", "BlockQuote", "Caption", "TOC", "TOCI",
    "Index", "NonStruct", "Private", "P", "H", "H1", "H2", "H3", "H4", "H5", "H6",
    "L", "LI", "Lbl", "LBody", "Table", "TR", "TH", "TD", "THead", "TBody", "TFoot",
    "Span", "Quote", "Note", "Reference", "BibEntry", "Code", "Link", "Annot", "Ruby",
    "RB", "RT", "RP", "Warichu", "WT", "WP", "Figure", "Formula", "Form",
})
_TEXT_LIMIT = 65536


def _object(document, xref):
    if not isinstance(xref, int) or isinstance(xref, bool) or not 0 < xref < document.xref_length():
        raise ValueError("Invalid PDF object reference")
    raw = document.xref_object(xref, compressed=False).encode("latin1")
    if len(raw) > 4_000_000:
        raise ValueError("Structure object exceeds editing size limit")
    return _Parser(raw).value()


def _resolve(document, value):
    if isinstance(value, _Ref):
        return _object(document, value.xref)
    return value


def _require_tag(document, xref):
    """Only edit indirect tags actually reachable in the current structure tree."""
    if getattr(document, "is_closed", False) or not getattr(document, "is_pdf", False):
        raise ValueError("An open PDF copy is required")
    if getattr(document, "name", None):
        raise ValueError("Tag editing requires an unnamed private PDF copy")
    if getattr(document, "is_encrypted", False) or (document.metadata or {}).get("encryption"):
        raise ValueError("Protected PDFs are not supported for tag editing")
    if document.get_sigflags() > 0:
        raise ValueError("PDFs with signature fields are not supported for tag editing")
    if not isinstance(xref, int) or isinstance(xref, bool) or xref <= 0:
        raise ValueError("Select an indirect structure tag")
    # Avoid content scanning when checking tree membership. The report still
    # traverses tags; its page limit affects only optional page association.
    report = inspect_tagged_pdf(document, max_pages=0)
    if not any(node.xref == xref for node in report.reading_order):
        raise ValueError("The selected object is not a reachable structure tag")
    item = _object(document, xref)
    if not isinstance(item, dict) or not isinstance(item.get("S"), _Name):
        raise ValueError("The selected object is not a structure tag")
    return item


def _text_entry(value):
    if not isinstance(value, str):
        raise ValueError("Tag properties must be text")
    if len(value) > _TEXT_LIMIT:
        raise ValueError("Tag property exceeds 65536 characters")
    if "\x00" in value or any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise ValueError("Tag properties contain invalid Unicode characters")
    return "null" if value == "" else fitz.get_pdf_str(value)


def edit_tag(document, xref: int, *, role: str | None = None,
             alt_text: str | None = None, actual_text: str | None = None,
             language: str | None = None, title: str | None = None) -> None:
    """Edit one existing indirect tag; omitted fields stay unchanged.

    A blank optional string removes that property. Roles are PDF 1.7 standard
    structure roles. Changing a role does not infer content or repair semantics.
    All arguments and membership are validated before any mutation.
    """
    _require_tag(document, xref)
    updates = {}
    if role is not None:
        if not isinstance(role, str) or role not in STANDARD_ROLES:
            raise ValueError("Choose a standard PDF structure role")
        updates["S"] = "/" + role
    for key, value in (("Alt", alt_text), ("ActualText", actual_text),
                       ("Lang", language), ("T", title)):
        if value is not None:
            updates[key] = _text_entry(value)
    # Preserve the exact object for rollback if the PDF engine rejects a write.
    original = document.xref_object(xref, compressed=False)
    try:
        for key, value in updates.items():
            document.xref_set_key(xref, key, value)
    except Exception:
        document.update_object(xref, original)
        raise


def _serialize(value):
    """Serialize parsed PDF objects without confusing strings with operators."""
    if isinstance(value, _Ref):
        return f"{value.xref} 0 R"
    if isinstance(value, _Name):
        raw = value.value.encode("latin1")
        return "/" + "".join(
            chr(c) if 33 <= c <= 126 and chr(c) not in "()<>[]{}/%#" else f"#{c:02X}"
            for c in raw
        )
    if isinstance(value, bytes):
        return "<" + value.hex() + ">"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + " ".join(_serialize(item) for item in value) + "]"
    if isinstance(value, dict):
        return "<< " + " ".join(
            _serialize(_Name(key)) + " " + _serialize(item) for key, item in value.items()
        ) + " >>"
    if isinstance(value, str) and (
        value in {"null", "true", "false"} or re.fullmatch(r"[+-]?(?:\d*\.\d+|\d+\.?\d*)", value)
    ):
        return value
    raise ValueError("Unsupported PDF object in structure children")


def move_tag(document, xref: int, direction: int) -> bool:
    """Move an existing tag past the adjacent sibling tag within its parent.

    MCIDs, marked-content references and object references retain their exact
    positions in /K. Only the two indirect structure-tag references are swapped.
    Returns False at the first/last tag. Direct tags and ambiguous/reused children
    are refused rather than rewritten. This changes logical order, not page ink.
    """
    if not isinstance(direction, int) or isinstance(direction, bool) or direction not in (-1, 1):
        raise ValueError("Direction must be -1 or 1")
    selected = _require_tag(document, xref)
    parent_ref = selected.get("P")
    if not isinstance(parent_ref, _Ref):
        raise ValueError("The selected tag has no indirect parent")
    parent = _object(document, parent_ref.xref)
    if not isinstance(parent, dict):
        raise ValueError("The tag parent is malformed")
    # Parent itself must be an actual reachable tag or the catalog's tree root.
    catalog = _object(document, document.pdf_catalog())
    root_ref = catalog.get("StructTreeRoot")
    if parent_ref != root_ref:
        _require_tag(document, parent_ref.xref)
    # The shared inspection parser intentionally stores xref numbers only. It
    # cannot round-trip nonzero reference generations, so refuse those inputs
    # instead of silently replacing their generation with zero during /K writes.
    raw_objects = [document.xref_object(parent_ref.xref, compressed=False)]
    if isinstance(parent.get("K"), _Ref):
        raw_objects.append(document.xref_object(parent["K"].xref, compressed=False))
    if any(re.search(r"\b\d+\s+[1-9]\d*\s+R\b", raw) for raw in raw_objects):
        raise ValueError("Nonzero-generation references cannot be reordered safely")
    children = _resolve(document, parent.get("K"))
    if isinstance(children, _Ref):
        raise ValueError("Unsupported nested indirect children")
    if not isinstance(children, list):
        children = [parent.get("K")]
    selected_positions = [i for i, value in enumerate(children) if value == _Ref(xref)]
    if len(selected_positions) != 1:
        raise ValueError("Parent must contain the selected tag exactly once")
    siblings = []
    refs = set()
    for index, value in enumerate(children):
        child = _resolve(document, value)
        if isinstance(child, dict) and isinstance(child.get("S"), _Name):
            if not isinstance(value, _Ref):
                raise ValueError("Direct structure children cannot be reordered")
            if value.xref in refs:
                raise ValueError("Repeated structure children cannot be reordered")
            if child.get("P") != parent_ref:
                raise ValueError("A sibling has an inconsistent parent association")
            refs.add(value.xref)
            siblings.append(index)
    position = selected_positions[0]
    if position not in siblings:
        raise ValueError("The selected child is not a reorderable tag")
    target = siblings.index(position) + direction
    if not 0 <= target < len(siblings):
        return False
    other = siblings[target]
    updated = list(children)
    updated[position], updated[other] = updated[other], updated[position]
    encoded = _serialize(updated)  # Complete validation before touching the PDF.
    document.xref_set_key(parent_ref.xref, "K", encoded)
    return True
