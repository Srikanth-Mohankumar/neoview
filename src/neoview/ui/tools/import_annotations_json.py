"""Strict, all-or-nothing import of transferable editable annotation records."""
from __future__ import annotations

import copy
import json
import math
import re
import uuid
from dataclasses import fields

from PySide6.QtWidgets import QFileDialog

from neoview.models.view_state import ANNOTATION_TYPES, AnnotationRecord
from neoview.ui.tool_support import apply_state

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 10_000
_COLOR = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?")


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _json_values(value):
    if value is None or isinstance(value, (str, bool)):
        return True
    if type(value) in (int, float):
        return _finite(value)
    if isinstance(value, list):
        return all(_json_values(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_values(item) for key, item in value.items())
    return False


def parse_annotations(payload, page_count):
    """Validate every record before returning fresh-ID annotations; mutate nothing."""
    if (not isinstance(payload, dict) or set(payload) != {"version", "annotations"}
            or type(payload["version"]) is not int or payload["version"] != 1):
        raise ValueError("Choose a version 1 NeoView annotation export.")
    records = payload["annotations"]
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        raise ValueError("An annotation import must contain at most 10000 records.")
    allowed = {field.name for field in fields(AnnotationRecord)}
    result = []
    for item in records:
        if (not isinstance(item, dict) or set(item) - allowed
                or not {"id", "type", "page", "rect"} <= set(item)):
            raise ValueError("An annotation record has missing or unsupported fields.")
        if (not isinstance(item["id"], str) or not isinstance(item["type"], str)
                or item["type"] not in ANNOTATION_TYPES):
            raise ValueError("Annotation IDs must be text and annotation types must be supported.")
        if type(item["page"]) is not int or not 0 <= item["page"] < page_count:
            raise ValueError("An annotation refers to a page outside the current PDF.")
        rect = item["rect"]
        if (not isinstance(rect, (list, tuple)) or len(rect) != 4
                or not all(_finite(number) for number in rect) or rect[2] < 0 or rect[3] < 0):
            raise ValueError("Annotation bounds must be four finite numbers with nonnegative sizes.")
        for key in ("contents", "created_at", "updated_at", "color", "border_color"):
            if key in item and not isinstance(item[key], str):
                raise ValueError(f"Annotation {key} must be text.")
        for key in ("color", "border_color"):
            color = item.get(key, "")
            if color and not _COLOR.fullmatch(color):
                raise ValueError("Annotation colors must be hexadecimal RGB colors.")
        for key, default in (("opacity", .25), ("border_width", 2.), ("font_size", 12.)):
            value = item.get(key, default)
            if not _finite(value) or value < 0 or (key == "opacity" and value > 1):
                raise ValueError("Annotation opacity, border width, and font size must be valid numbers.")
            if key == "font_size" and value == 0:
                raise ValueError("Annotation font size must be positive.")
        points = item.get("points", [])
        if (not isinstance(points, list) or len(points) > 50_000
                or any(not isinstance(point, (list, tuple)) or len(point) != 2
                       or not all(_finite(number) for number in point) for point in points)):
            raise ValueError("Annotation paths must contain finite two-coordinate points.")
        extra = item.get("extra", {})
        if (not isinstance(extra, dict) or not _json_values(extra)
                or len(json.dumps(extra)) > 65_536):
            raise ValueError("Annotation extra data must be a small finite JSON object.")
        values = copy.deepcopy(item)
        values.update(id=uuid.uuid4().hex, rect=tuple(rect))
        result.append(AnnotationRecord(**values))
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object fields are not allowed.")
        result[key] = value
    return result


def load_annotations(path, page_count):
    with open(path, "rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("The annotation import exceeds the 10 MB size limit.")
    try:
        payload = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        return parse_annotations(payload, page_count)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise ValueError("The annotation import is not valid finite UTF-8 JSON.") from exc


def run(window):
    context = window.current_context()
    source = context.file_path
    path, _ = QFileDialog.getOpenFileName(window, "Import Annotations", "", "JSON (*.json)")
    if not path:
        return None
    if window.current_context() is not context or context.file_path != source:
        raise ValueError("The active document changed while choosing the annotation import.")
    document = window.current_view().document
    if document is None:
        raise ValueError("Open a PDF before importing annotations.")
    records = load_annotations(path, document.page_count)
    if len(context.sidecar_state.annotations) + len(records) > MAX_RECORDS:
        raise ValueError("The combined document would exceed 10000 editable annotations.")
    if records:
        state = copy.deepcopy(context.sidecar_state)
        state.annotations.extend(records)
        apply_state(window, state)
    window._status.showMessage(f"Imported {len(records)} annotations", 3000)
    return None
