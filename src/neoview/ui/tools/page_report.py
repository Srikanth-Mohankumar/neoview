"""Export displayed page geometry and annotation counts as a CSV report."""
from __future__ import annotations

import csv
import io
from collections import Counter

import fitz

from neoview.models.view_state import DocumentSidecarState
from neoview.ui.tool_support import atomic_text, choose_file, snapshot

FIELDS = (
    "page", "width_pt", "height_pt", "width_mm", "height_mm", "rotation_degrees",
    "native_annotation_count", "editable_annotation_count",
)


def geometry_csv(document: fitz.Document, state: DocumentSidecarState) -> str:
    """Report displayed crop dimensions, including the page's stored rotation."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(FIELDS)
    editable_counts = Counter(annotation.page for annotation in state.annotations)
    for index, page in enumerate(document):
        width, height = page.rect.width, page.rect.height
        writer.writerow((
            index + 1, width, height, width * 25.4 / 72, height * 25.4 / 72,
            page.rotation, sum(1 for _ in page.annots()), editable_counts[index],
        ))
    return output.getvalue()


def export_page_report(document, state, source, destination) -> None:
    """Atomically save the report without overwriting either source file."""
    atomic_text(source, destination, geometry_csv(document, state))


def run(window) -> None:
    with snapshot(window) as (document, state, source):
        destination = choose_file(window, source, "-page-geometry", ".csv",
                                  "Export Page Geometry Report")
        if destination:
            export_page_report(document, state, source, destination)
