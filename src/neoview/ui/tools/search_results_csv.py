"""Export a completed search without re-reading or modifying its PDF."""
from __future__ import annotations

import copy
import csv
import io
import math

from PySide6.QtWidgets import QMessageBox

from neoview.ui.annotation_csv import _spreadsheet_text
from neoview.ui.tool_support import atomic_text, choose_file

FIELDS = ("page", "query", "snippet", "x_pt", "y_pt", "width_pt", "height_pt")


def search_results_csv(query, results, page_count) -> str:
    """Serialize validated page bounds and spreadsheet-safe search text."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(FIELDS)
    for match in results:
        if type(match.page_idx) is not int or not 0 <= match.page_idx < page_count:
            raise ValueError("Search result has an invalid page number.")
        try:
            bounds = tuple(float(value) for value in match.rect)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Search result has invalid bounds.") from exc
        if (len(bounds) != 4 or not all(math.isfinite(value) for value in bounds)
                or bounds[2] < 0 or bounds[3] < 0):
            raise ValueError("Search result has invalid bounds.")
        writer.writerow((match.page_idx + 1, _spreadsheet_text(query),
                         _spreadsheet_text(match.snippet), *bounds))
    return output.getvalue()


def run(window) -> None:
    context = window.current_context()
    document = window.current_view().document
    if document is None or not context.file_path:
        raise ValueError("Open a PDF first.")
    timer = getattr(window, "_search_timer", None)
    if (window._search_operation is not None or (timer is not None and timer.isActive())
            or window._active_search_text() != context.search_query):
        QMessageBox.information(window, "Export Search Results",
                                "Run or finish the current search before exporting.")
        return
    if not context.search_results:
        QMessageBox.information(window, "Export Search Results", "There are no search results to export.")
        return
    if not window._search_results_are_current():
        QMessageBox.information(window, "Export Search Results",
                                "Run or finish the current search before exporting.")
        return
    # Modal dialogs run a nested event loop: capture everything beforehand.
    source = context.file_path
    query, results = copy.deepcopy((context.search_query, context.search_results))
    report = search_results_csv(query, results, document.page_count)
    destination = choose_file(window, source, "-search-results", ".csv", "Export Search Results")
    if destination:
        atomic_text(source, destination, report)
        status = getattr(window, "_status", None)
        if status is not None:
            status.showMessage("Search results exported.", 3000)
