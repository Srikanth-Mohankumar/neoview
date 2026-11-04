"""Menu registration for focused document, report, transfer and tab tools."""
from __future__ import annotations

from importlib import import_module

from PySide6.QtWidgets import QMessageBox

TOOLS = (
    ("pages", "reverse_pages", "Reverse Pages into Copy..."),
    ("pages", "duplicate_pages", "Duplicate Page Ranges..."),
    ("pages", "blank_page", "Insert Blank Page..."),
    ("pages", "split_pages", "Split into One-Page PDFs..."),
    ("exports", "optimize_pdf", "Save Optimized PDF Copy..."),
    ("exports", "page_report", "Export Page Geometry as CSV..."),
    ("exports", "export_text", "Export Document Text..."),
    ("exports", "extract_images", "Extract Embedded Images..."),
    ("exports", "page_pngs", "Export Pages as PNG..."),
    ("exports", "outline_json", "Export Outline as JSON..."),
    ("annotations", "export_annotations_json", "Export Editable Annotations as JSON..."),
    ("annotations", "import_annotations_json", "Import Editable Annotations from JSON..."),
    ("annotations", "annotations_markdown", "Export Annotation Report as Markdown..."),
    ("bookmarks", "export_bookmarks_json", "Export Bookmarks as JSON..."),
    ("bookmarks", "import_bookmarks_json", "Import Bookmarks from JSON..."),
    ("files", "copy_path", "Copy PDF File Path"),
    ("files", "reveal_folder", "Open Containing Folder"),
    ("tabs", "close_other_tabs", "Close Other Tabs"),
    ("tabs", "close_tabs_right", "Close Tabs to the Right"),
    ("tabs", "reopen_closed_tab", "Reopen Closed Tab"),
)


def invoke(window, slug):
    try:
        result = import_module(f"neoview.ui.tools.{slug}").run(window)
        if isinstance(result, str) and result.lower().endswith(".pdf"):
            window._open_saved_pdf_copy(result)
    except Exception as exc:
        QMessageBox.warning(window, "Document Tool Failed", str(exc))


def install_tools(window, file_menu, pages_menu):
    menus = {
        "pages": pages_menu,
        "exports": file_menu.addMenu("Document Exports"),
        "annotations": file_menu.addMenu("Annotation Transfer"),
        "bookmarks": file_menu.addMenu("Bookmark Transfer"),
        "files": file_menu.addMenu("File Location"),
        "tabs": file_menu.addMenu("Tab Actions"),
    }
    window._extra_tool_actions = {}
    for group, slug, title in TOOLS:
        action = window._action(title, lambda _checked=False, s=slug: invoke(window, s),
                                name="action_" + slug)
        menus[group].addAction(action)
        window._extra_tool_actions[slug] = action
        if slug == "reopen_closed_tab":
            action.setShortcut("Ctrl+Shift+W")
            action.setEnabled(bool(window._closed_pdf_paths))
        else:
            window._doc_actions.append(action)
