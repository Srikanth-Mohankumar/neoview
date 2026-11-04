"""Export a spreadsheet-friendly annotation review report without changing the PDF."""
from __future__ import annotations

import csv
import math
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox

from neoview.models.view_state import AnnotationRecord
from neoview.persistence.sidecar_store import sidecar_path_for

CSV_FIELDS = (
    "source", "id", "page", "type", "contents", "color", "opacity",
    "x_pt", "y_pt", "width_pt", "height_pt",
)


def _spreadsheet_text(value: str) -> str:
    """Keep free text inert, including formulas hidden behind whitespace/BOMs."""
    text = str(value)
    probe = text
    while probe and (probe[0].isspace() or probe[0] == "\ufeff"):
        probe = probe[1:]
    return "'" + text if probe.startswith(("=", "+", "-", "@")) else text


def _check_destination(source_path: str, out_path: str) -> None:
    destination = Path(out_path)
    for protected in (Path(source_path), Path(sidecar_path_for(source_path))):
        same = destination.resolve() == protected.resolve()
        if not same and destination.exists() and protected.exists():
            same = os.path.samefile(destination, protected)
        if same:
            raise ValueError("Choose a CSV destination different from the PDF and its sidecar.")


def _number(value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Annotation bounds and opacity must be finite numbers.")
    return number


def write_annotations_csv(
    source_path: str,
    out_path: str,
    annotations: Iterable[AnnotationRecord],
    native_annotations: Iterable[AnnotationRecord],
) -> None:
    """Atomically write UTF-8 CSV; page numbers are one-based and bounds use points.

    Native and NeoView annotations remain distinct rows. Free text that could be
    interpreted as a spreadsheet formula is prefixed with an apostrophe.
    """
    _check_destination(source_path, out_path)
    target = Path(out_path)
    if target.suffix.lower() != ".csv":
        raise ValueError("The annotation report must have a .csv extension.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8-sig", newline="", prefix=".neoview-report-",
            suffix=".tmp", dir=target.absolute().parent, delete=False,
        ) as handle:
            temporary = handle.name
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for source, records in (("neoview", annotations), ("native", native_annotations)):
                for annotation in records:
                    if not isinstance(annotation.page, int) or annotation.page < 0:
                        raise ValueError("Annotation pages must be nonnegative integer indexes.")
                    x, y, width, height = annotation.rect
                    writer.writerow({
                        "source": source,
                        "id": _spreadsheet_text(annotation.id),
                        "page": annotation.page + 1,
                        "type": _spreadsheet_text(annotation.type),
                        "contents": _spreadsheet_text(annotation.contents),
                        "color": _spreadsheet_text(annotation.color),
                        "opacity": _number(annotation.opacity),
                        "x_pt": _number(x), "y_pt": _number(y),
                        "width_pt": _number(width), "height_pt": _number(height),
                    })
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def export_annotations_csv(
    parent,
    source_path: str,
    annotations: Iterable[AnnotationRecord],
    native_annotations: Iterable[AnnotationRecord],
) -> str | None:
    """Prompt for a CSV report destination and return it only after a successful write."""
    annotations = list(annotations)
    native_annotations = list(native_annotations)
    if not source_path or not (annotations or native_annotations):
        QMessageBox.information(parent, "Export Annotations", "No annotations to export.")
        return None
    default = str(Path(source_path).with_name(Path(source_path).stem + "-annotations.csv"))
    path, _ = QFileDialog.getSaveFileName(
        parent, "Export Annotations as CSV", default, "CSV Files (*.csv)"
    )
    if not path:
        return None
    try:
        # Check the user's exact choice before normalizing its extension.
        _check_destination(source_path, path)
        if not path.lower().endswith(".csv"):
            path += ".csv"
            _check_destination(source_path, path)
            if Path(path).exists() and QMessageBox.question(
                parent, "Replace Report?", f"Replace the existing report {Path(path).name}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) != QMessageBox.StandardButton.Yes:
                return None
        write_annotations_csv(source_path, path, annotations, native_annotations)
    except (OSError, ValueError) as exc:
        QMessageBox.warning(parent, "Could Not Export Annotations", str(exc))
        return None
    return path
