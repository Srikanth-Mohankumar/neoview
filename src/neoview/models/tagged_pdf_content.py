"""Conservative whole-page artifact marking on caller-owned in-memory copies.

These commands do not tag meaningful content or repair existing structure trees.
"""
from __future__ import annotations

import hashlib

from neoview.models.tagged_pdf import _Parser, _Ref

_PREFIX = b"% NeoView whole-page artifact v1\n/Artifact BMC\n"
_SUFFIX = b"\nEMC\n% End NeoView whole-page artifact v1\n"
_MAX_BYTES = 8_000_000
_KEY = "NeoViewArtifact"


def _parse(raw):
    return _Parser(raw.encode("latin1")).value()


def _resolve(document, value):
    if isinstance(value, _Ref):
        return _parse(document.xref_object(value.xref, compressed=False))
    return value


def _validate_document(document, page_index):
    if document.name:
        raise ValueError("Artifact editing requires an in-memory PDF copy.")
    if document.is_encrypted or document.needs_pass:
        raise ValueError("Password-protected PDFs are not supported.")
    if document.get_sigflags() > 0:
        raise ValueError("Signed PDFs are not supported for artifact editing.")
    if isinstance(page_index, bool) or not isinstance(page_index, int):
        raise ValueError("Page index must be an integer.")
    if not 0 <= page_index < len(document):
        raise ValueError("Page index is outside this document.")
    catalog = document.pdf_catalog()
    root_kind, _ = document.xref_get_key(catalog, "StructTreeRoot")
    mark_kind, mark_raw = document.xref_get_key(catalog, "MarkInfo")
    mark = _resolve(document, _parse(mark_raw)) if mark_kind != "null" else {}
    if root_kind != "null" or (isinstance(mark, dict) and mark.get("Marked") == "true"):
        raise ValueError("Whole-page artifact marking cannot modify a tagged PDF.")
    return document[page_index]


def _contents(document, value):
    """Read only ordinary indirect content stream references, with a byte cap."""
    if value == "null":
        return b""
    refs = value if isinstance(value, list) else [value]
    if any(not isinstance(ref, _Ref) for ref in refs):
        raise ValueError("Unsupported page content representation.")
    result = bytearray()
    for ref in refs:
        if not document.xref_is_stream(ref.xref):
            raise ValueError("Page content does not reference a stream.")
        data = document.xref_stream(ref.xref)
        if len(result) + len(data) > _MAX_BYTES + len(_PREFIX) + len(_SUFFIX):
            raise ValueError("Page content exceeds the artifact editing size limit.")
        result.extend(data)
    return bytes(result)


def _validate_content(data):
    parser = _Parser(data)
    while True:
        parser._space()
        if parser.pos == len(data):
            return
        try:
            token = parser.value()
        except EOFError as exc:
            raise ValueError("Malformed page content cannot be marked safely.") from exc
        if isinstance(token, str) and token in {
            "BMC", "BDC", "EMC", "MP", "DP", "BI", "ID", "EI",
        }:
            raise ValueError(
                "Pages with existing marked content or inline images are not supported."
            )


def mark_page_as_artifact(document, page_index: int) -> None:
    """Mark the entire otherwise-untagged page as decorative, on an in-memory copy.

    The caller must explain that all meaningful page content is excluded from
    logical reading order, and save to a new PDF after explicit confirmation.
    Existing tags, marked content, Form XObjects and inline images are refused.
    """
    page = _validate_document(document, page_index)
    kind, _ = document.xref_get_key(page.xref, _KEY)
    if kind != "null":
        raise ValueError("This page already has NeoView artifact metadata.")
    if page.get_xobjects():
        raise ValueError("Pages using Form XObjects are not supported.")
    _, original_raw = document.xref_get_key(page.xref, "Contents")
    original = _contents(document, _parse(original_raw))
    if len(original) > _MAX_BYTES:
        raise ValueError("Page content exceeds the artifact editing size limit.")
    _validate_content(original)
    if not original.strip():
        raise ValueError("There is no page content to mark as an artifact.")
    wrapped = _PREFIX + original + _SUFFIX
    digest = hashlib.sha256(wrapped).hexdigest()
    wrapper = document.get_new_xref()
    document.update_object(wrapper, "<<>>")
    document.update_stream(wrapper, wrapped)
    metadata = (
        f"<< /Version 1 /OriginalContents {original_raw} /Wrapper {wrapper} 0 R "
        f"/Digest ({digest}) >>"
    )
    # All content and compatibility checks above precede page mutations.
    document.xref_set_key(page.xref, _KEY, metadata)
    document.xref_set_key(page.xref, "Contents", f"{wrapper} 0 R")


def unmark_page_artifact(document, page_index: int) -> None:
    """Undo only an unchanged whole-page artifact wrapper created by NeoView."""
    page = _validate_document(document, page_index)
    kind, raw = document.xref_get_key(page.xref, _KEY)
    if kind != "dict":
        raise ValueError("This page has no NeoView whole-page artifact wrapper.")
    metadata = _parse(raw)
    wrapper = metadata.get("Wrapper")
    if metadata.get("Version") != 1 or not isinstance(wrapper, _Ref):
        raise ValueError("Unsupported NeoView artifact metadata.")
    _, current_raw = document.xref_get_key(page.xref, "Contents")
    if _parse(current_raw) != wrapper:
        raise ValueError("Page content changed since artifact marking; refusing to unwrap.")
    wrapped = _contents(document, wrapper)
    digest = metadata.get("Digest")
    if not isinstance(digest, bytes) or digest.decode("ascii", errors="replace") != (
        hashlib.sha256(wrapped).hexdigest()
    ):
        raise ValueError("Artifact wrapper changed; refusing to unwrap.")
    original = metadata.get("OriginalContents")
    data = _contents(document, original)
    if wrapped != _PREFIX + data + _SUFFIX:
        raise ValueError("Original content changed; refusing to unwrap.")
    # PyMuPDF's dictionary lookup preserves a valid PDF serialization for this value.
    _, original_raw = document.xref_get_key(page.xref, f"{_KEY}/OriginalContents")
    document.xref_set_key(page.xref, "Contents", original_raw)
    document.xref_set_key(page.xref, _KEY, "null")
