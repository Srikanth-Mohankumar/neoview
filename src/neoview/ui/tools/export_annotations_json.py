"""Export editable NeoView annotation records in a versioned transfer format."""
from __future__ import annotations

import copy
import json
from dataclasses import asdict

from PySide6.QtWidgets import QMessageBox

from neoview.ui.tool_support import atomic_text, choose_file


def annotation_json(annotations) -> str:
    """Preserve all record fields; pages remain zero-based as in NeoView sidecars."""
    return json.dumps(
        {"version": 1, "annotations": [asdict(record) for record in annotations]},
        ensure_ascii=False, allow_nan=False, indent=2,
    ) + "\n"


def run(window) -> None:
    context = window.current_context()
    if window.current_view().document is None or not context.file_path:
        raise ValueError("Open a PDF first.")
    # A save dialog enters a nested event loop; the active view can reload while
    # it is open. Retain a complete independent copy of the editable records.
    source = context.file_path
    annotations = copy.deepcopy(context.sidecar_state.annotations)
    if not annotations:
        QMessageBox.information(window, "Export Annotations", "No editable annotations to export.")
        return
    text = annotation_json(annotations)
    target = choose_file(window, source, "-annotations", ".json", "Export Annotations as JSON")
    if target:
        atomic_text(source, target, text)
