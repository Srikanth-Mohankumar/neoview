# NeoView v0.5 feature inventory

Source of truth for what the website, README and demo may claim. Every row was checked in the
code on `redesign/v0.5` (commit 268b8ef). "Where" names the module and function, or the menu
and shortcut a user reaches it from. "Demo" is how to show it (and what the demo video does).
Paths are relative to `src/neoview/`.

## Opening and documents

| # | Capability | Where | Demo |
|---|---|---|---|
| 1 | Multi-tab viewing; the tab strip appears with two or more documents; opening an already-open file switches to its tab | `ui/main_window.py` `_create_tab`, `_find_open_view`; Ctrl+Tab / Ctrl+Shift+Tab, Ctrl+PgDn / Ctrl+PgUp | Open two PDFs, switch tabs |
| 2 | Welcome screen with Open button, drop hint and up to 6 recent files | `ui/welcome.py` `WelcomePanel` (`MAX_RECENT = 6`) | Start with no document |
| 3 | Drag and drop one or more PDFs onto the window | `main_window.py` `dragEnterEvent` / `dropEvent`, `_extract_pdf_paths_from_urls` | Drop a file |
| 4 | Open Recent menu | File > Open Recent (`_rebuild_recent_menu`) | Menu |
| 5 | Password-protected PDFs: prompt with up to 3 attempts; the password stays in memory only and is reused for reload, print and presentation | `ui/password.py` `PasswordDialog`, `MAX_ATTEMPTS`; `PdfView.open_document(path, password)`; `main_window._unlock_and_open` | Open an encrypted PDF |
| 6 | Auto-reload when the file changes on disk (file watcher plus a 500 ms poll); page, zoom and scroll position kept; old renders stay on screen until the new ones arrive (no blank flash); waits out zero-byte files mid-rebuild; toggle in the inspector; manual reload Ctrl+Shift+R | `main_window._on_change`, `_poll_check`, `_do_reload`; `PdfView.reload_document`; Inspector > Document > "Auto-reload on change" | Rewrite the PDF in place while it is open |
| 7 | Per-document session restore: page, zoom, zoom mode, page layout and reading mode remembered per file; the last active file reopens at startup | `main_window._save_document_session_for_view`, `_restore_document_session`; QSettings `documents/session`, `session/last_active_file` | Close and reopen |
| 8 | Window geometry, sidebar/inspector/search-panel visibility, sidebar page, tool, unit, theme remembered | `main_window._restore_persistent_ui`, `_save_persistent_ui` | Restart |
| 9 | Document metadata in the inspector: file, page, zoom, title, author, subject, keywords, creator, producer, PDF format, created/modified dates, encryption, file size | `ui/inspector.py` DOCUMENT section; `main_window._refresh_document_info` | Open the inspector |

## Reading and navigation

| # | Capability | Where | Demo |
|---|---|---|---|
| 10 | Page layouts: single page, continuous, two pages, two pages with cover | View > Page Layout, overflow menu; `PdfView.set_page_mode` (`ui/page_modes.py`) | Switch layouts |
| 11 | In single-page mode the wheel turns the page at the page edge | `PdfView._flip_page_at_edge` | Scroll in single mode |
| 12 | Reading modes: normal, night (luminance inverted, hue kept), sepia; applied in the render path, thumbnails follow | View > Reading Mode; `PdfView.set_color_mode`; `page_modes.apply_color_mode` | Switch modes |
| 13 | Zoom: Fit Width (Ctrl+1 / W), Fit Page (Ctrl+2 / F), Actual Size (Ctrl+0), zoom in/out (Ctrl+= or Ctrl++ / Ctrl+-), presets 50-400 % plus typed values in the zoom box | `ui/toolbar.py` `ZoomBox`, `ZOOM_PRESETS`; `PdfView.fit_width/fit_page/actual_size/zoom_by` | Zoom box |
| 14 | Ctrl+wheel and touchpad pinch zoom around the cursor (the point under the cursor stays put); buttons zoom around the view centre | `PdfView.wheelEvent`, `_native_gesture`, `_zoom_at_viewport_point`, `_apply_zoom` | Pinch on a word |
| 15 | Page navigation: page field "n / N", PgUp/PgDn, Home/End, Go to Page (Ctrl+G) | `ui/toolbar.py` `PageField`; Go menu | Type a page number |
| 16 | Back / forward history across jumps (outline, links, search results, page field, bookmarks), restoring page, in-page scroll and zoom | `ui/navigation_history.py`; `PdfView.go_back/go_forward`; Go > Back/Forward, Alt+Left / Alt+Right | Jump, then Alt+Left |
| 17 | Internal links followed (with a hover badge showing the target); external URLs open in the browser | `PdfView._update_link_hover`, `_follow_link` | Click a cross-reference |
| 18 | Rotate left / right (Ctrl+L / Ctrl+R), reset rotation | View > Rotate | Menu |
| 19 | Full screen (F11) | View > Full Screen | |
| 20 | Presentation mode: full-screen pages; Right/Space/PgDn/Enter/N next, Left/Backspace/PgUp/P previous, Home/End, B or . black screen, Esc exits and the viewer follows to the last shown page | `ui/presentation.py` `PresentationWindow`; View > Presentation, F5 | F5 |
| 21 | Print with page range, current page, copies/collate and print to file; pages rendered and fitted to the printable area | `ui/printing.py` `build_print_dialog`, `print_document`; File > Print, Ctrl+P | Ctrl+P |

## Sidebar and panels

| # | Capability | Where | Demo |
|---|---|---|---|
| 22 | Sidebar (F9) with four panels: Thumbnails (Ctrl+Shift+T), Outline (Ctrl+Shift+O), Bookmarks (Ctrl+Shift+B), Annotations (Ctrl+Shift+A) | `ui/sidebar.py`; `main_window._setup_sidebar` | Open each panel |
| 23 | Outline tree with a filter box; the current section is followed while scrolling | `main_window._populate_outline` (`_outline_filter`), `_sync_outline_current_page` | Type in "Filter outline" |
| 24 | Thumbnails rendered lazily (only while the panel is visible) in the reading colours | `main_window._populate_thumbnails`, `_render_thumbnail_batch` | Thumbnails panel |
| 25 | Bookmarks: add (Ctrl+D), rename, delete (context menu); stored in the sidecar | `main_window._add_bookmark`, `_on_bookmarks_context_menu` | Ctrl+D |
| 26 | Inspector (Ctrl+Shift+I) with MEASUREMENT, TEXT and DOCUMENT sections | `ui/inspector.py` `InspectorPanel` | Ctrl+Shift+I |
| 27 | Status bar: file name, measurement W x H, "Page n of N", zoom | `ui/statusbar.py` | |

## Search

| # | Capability | Where | Demo |
|---|---|---|---|
| 28 | Inline find field with live results while typing, match count, match-case toggle, previous/next (F3 / Shift+F3, Enter / Shift+Enter) | `ui/toolbar.py` `SearchField`; `main_window._on_search_text_changed`, `_execute_search_current` | Type a word |
| 29 | Search results panel (Ctrl+Shift+F) listing every match with page number and a text snippet from the matching line; click to jump | `main_window._setup_search_dock`, `_search_snippet`, `_jump_to_search_item` | Open results |
| 30 | Highlights on the current and visible matches; search state kept per tab; large documents searched in batches so the UI stays responsive | `main_window._update_search_highlights`, `_process_search_batch` | |

## Inspect and measure

| # | Capability | Where | Demo |
|---|---|---|---|
| 31 | Font inspection: with the Select tool (1), hovering text outlines the span and the inspector shows its font name, size (pt) and style (bold/italic) | `PdfView.mouseMoveEvent` -> `PageItem.get_text_info_at`, `_update_text_inspection`, `text_info_changed`; `main_window._on_view_text_info` | Hover a heading, body text, code |
| 32 | Measure tool (3): drag a rectangle; on-canvas badge and inspector show width, height, X and Y | `ui/selection.py` `SelectionRect`; `PdfView._update_measure_badge`; inspector MEASUREMENT | Drag a box |
| 33 | Measurement units: points, picas, millimetres, inches (Tools > Measurement Units or the inspector combo) | `utils/units.py` `UNITS = ("pt", "pc", "mm", "in")`; `main_window._set_unit` | Switch pt -> mm |
| 34 | Resize by handles; move by drag; keyboard: Arrow moves 1 pt, Shift+Arrow 10 pt, Ctrl+Arrow resizes 1 pt, Ctrl+Shift+Arrow 10 pt | `PdfView.keyPressEvent`; `SelectionRect.nudge`, `resize_by` | Arrow keys |
| 35 | Copy measurements (Ctrl+C or the inspector Copy button): width and height in pt, pc and mm, whatever the display unit | `main_window._copy` -> `utils.units.format_size` | Ctrl+C |
| 36 | Export the measured area as PNG at 150, 300 or 600 DPI (Ctrl+S) | `ui/dialogs.py` `ExportDialog`; `main_window._export` | Ctrl+S |
| 37 | Rulers along the top and left edges, in points, ticks scale with zoom | View > Show Rulers; `PdfView._paint_rulers` | Toggle |
| 38 | Layout grid overlay with settings: line spacing (width/height), offsets from left/top, subdivisions, corner mark length, line colour | View > Show Layout Grid, Layout Grid Settings...; `ui/dialogs.py` `LayoutGridDialog`; `PdfView._paint_layout_grid` | Toggle and adjust |
| 39 | Text selection with the Select tool: drag to select, the text is copied to the clipboard; context menu Copy Text / Select All on Page | `PdfView._highlight_text_in_rect`, `contextMenuEvent`; `main_window._on_view_text_selected` | Drag over text |

## Annotate and review

| # | Capability | Where | Demo |
|---|---|---|---|
| 40 | Annotate tool (4) with ten types: highlight, underline, strikethrough, sticky note, text box, rectangle, ellipse, line, arrow, freehand | `ui/annotation_toolbar.py` `_ANNOTATION_TOOLS`; `PdfView._commit_annotate_rect`, `_commit_annotate_freehand` | Draw a few |
| 41 | Colour, opacity and stroke width on the annotation toolbar | `AnnotationToolbar` | |
| 42 | Highlight / underline / note from a measure selection (Ctrl+Shift+H / U / N) | `main_window._add_highlight`, `_add_underline`, `_add_note` | |
| 43 | Annotation list in the sidebar with a type filter; click to jump; Delete key or context menu deletes; double-click or context menu opens properties (text, colour, opacity, stroke width) | `main_window._populate_annotation_list`, `_annotation_filter`; `ui/dialogs.py` `AnnotationPropertiesDialog` | Annotations panel |
| 44 | Annotations and bookmarks saved in a `<file>.pdf.neoview.json` sidecar next to the PDF (the PDF is never modified); corrupt sidecars are set aside as `.broken.<stamp>` | `persistence/sidecar_store.py` | Look beside the PDF |
| 45 | Export a PDF copy with the annotations embedded as standard PDF annotations | File > Export PDF with Annotations...; `ui/annotation_io.py` `export_annotated_pdf` | |
| 46 | Annotations already in the PDF (e.g. from other tools) are shown and listed, read-only | `annotation_io.load_native_annotations` | Open an annotated PDF |

## Look, platform and performance

| # | Capability | Where | Demo |
|---|---|---|---|
| 47 | Light, dark or system theme, switched at runtime (View > Theme); `NEOVIEW_THEME` overrides at startup | `theme.py`; `main_window._set_theme` | Switch |
| 48 | Same look on Linux and Windows: bundled Inter font (SIL OFL 1.1) and Lucide icons (ISC), tinted per theme | `assets/fonts/`, `assets/icons/`, `ui/icons.py` | Compare CI screenshots per OS |
| 49 | Background banded rendering: pages render from a display list in cancellable bands a few ms at a time; visible pages first; a zoom or scroll cancels stale work | `ui/render_scheduler.py` `RenderScheduler`; commit 77ed433 | Open a long book |
| 50 | Bounded memory: 256 MB byte-budget pixmap cache, pages more than 4 away from the view drop their pixmap, memory returned to the OS when a document closes | `ui/page_item.py`; commits 77ed433, cb75dac | |
| 51 | Large documents: outline, thumbnails and native annotations are loaded lazily; link tables read on first hover | commits 7db82c7, 0011372, dfa0d4b, bb1fe20, 8afeff0 | |
| 52 | Performance Mode: pause rendering during zoom/scroll to save CPU | View > Performance Mode; `PdfView.set_performance_mode` | |
| 53 | Keyboard shortcuts for every action, tool switching with 1-4 | README "Keyboard Shortcuts"; `main_window._setup_actions` | |
| 54 | Reset Window Layout | View > Reset Window Layout | |
| 55 | Installs: `pip install neoview` (Python 3.10+), standalone Windows `neoview.exe` from GitHub Releases, `./run.sh` from source | README; `.github/workflows/windows-build.yml` | |

## Performance numbers (for the website)

From the rendering benchmark (`scripts/bench_render.py`) run while the
v0.5 rendering work was merged. "Before" is the v0.4 code (pyproject version 0.4); "after" is the
`redesign/v0.5` render path. Raw logs were kept outside the repository; the medians are copied here.

Conditions: Intel Core Ultra 5 225U (14 threads), Linux 6.17, Python 3.12.3, PyMuPDF 1.28.2,
PySide6 6.12.0, Qt offscreen platform. Test PDFs are generated by the harness: `vector`
(100 pages of text and vector shapes), `images` (the same plus a 2400x1800 image on every 10th
page), `book` (650 pages of dense text, 20 internal links per page) and `book-images` (the
same plus a distinct 1500x1000 image on every page).

Reading all 650 pages at fit width, waiting for each to be sharp (median of 3 runs):

| Document | v0.4 | v0.5 |
|---|---|---|
| book | aborted by the harness at its 3 GB cap after 46 pages (3,097 MB) | all 650 pages, peak 427 MB |
| book-images | aborted at the 3 GB cap after 43 pages (3,108 MB) | all 650 pages, peak 718 MB |

Open, zoom and scroll (median of 5 runs):

| Metric | vector | images | book | book-images |
|---|---|---|---|---|
| Open to responsive, v0.4 -> v0.5 (s) | 0.608 -> 0.011 | 0.779 -> 0.012 | 1.110 -> 0.106 | 1.147 -> 0.103 |
| Longest freeze while zooming, v0.4 -> v0.5 (ms) | 586 -> 25 | 655 -> 83 | 283 -> 28 | 402 -> 31 |
| Blank visible pages after wheel scrolling, v0.4 -> v0.5 | 1 -> 0 | 1 -> 0 | 2 -> 0 | 2 -> 0 |
| Peak memory in this run, v0.4 -> v0.5 (MB) | 1,655 -> 339 | 1,685 -> 350 | 1,820 -> 385 | 1,923 -> 513 |

One machine, synthetic documents; numbers on other hardware and real documents will differ.

## Not claimed

- Mouse back/forward buttons for history: suggested in `viewer-api.md`, not wired in `PdfView`.
- Editing PDF content, form filling, digital signatures, OCR: not present.
- macOS: not a target platform (no build, not tested in CI).
- Reopening every tab of the last session: only the last active file reopens.
- A "whole word" search option: only match case exists.
