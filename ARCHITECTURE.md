# Architecture

NeoView is organized as a small, modular Qt application with clear separation
between rendering, interaction, and UI orchestration.

## Package layout

- `neoview/app.py`: CLI entry point and app bootstrap.
- `neoview/theme.py`: Qt stylesheet.
- `neoview/resources.py`: packaged assets (icons).
- `neoview/utils/units.py`: unit conversions and formatting.
- `neoview/ui/page_item.py`: PDF page rendering (PyMuPDF -> QPixmap).
- `neoview/ui/selection.py`: measurement selection behavior.
- `neoview/ui/pdf_view.py`: core viewer and input handling.
- `neoview/ui/dialogs.py`: export/find dialogs.
- `neoview/ui/main_window.py`: actions, menus, tabs and orchestration of the chrome below.
- `neoview/ui/toolbar.py`, `sidebar.py`, `inspector.py`, `statusbar.py`, `welcome.py`: main
  toolbar widgets, left sidebar, right inspector, status bar, empty state.
- `neoview/ui/chrome.py`: icon re-tinting on theme switch and the stylesheet for those widgets.
- `neoview/ui/annotation_io.py`: native PDF annotations in, annotated PDF out.

## Data flow

- `MainWindow` owns the `PdfView` and coordinates menus/toolbars.
- `PdfView` emits signals for UI updates (zoom/page/selection).
- Rendering is driven by `PageItem` and re-rendered on zoom changes.
- Selection state is maintained in `SelectionRect` and surfaced via signals.
