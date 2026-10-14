# Viewer API contract (v0.5)

This is the API that menus, toolbar buttons and shortcuts are wired against. Phase A added
the building blocks as standalone modules under `src/neoview/ui/`; Phase B adds the
`PdfView` methods and signals below on top of them. Names, argument types and signal
signatures here are stable; wire against them, not against the private helpers.

Everything is per view (per tab). `MainWindow` talks to `PdfView` through these methods and
signals only; `PdfView` never references `MainWindow`.

## Building blocks (Phase A, available now)

| Module | Public API |
| --- | --- |
| `neoview.ui.page_modes` | `PAGE_MODES`, `COLOR_MODES`, `page_rows(mode, n)`, `layout_pages(page_sizes, viewport_width, zoom, spacing, mode) -> PageLayout`, `PageLayout.rects / rows / scene_width / scene_height / paged / row_of(i) / row_bounds(row)`, `apply_color_mode(image, mode) -> QImage`, `page_background(mode) -> QColor` |
| `neoview.ui.navigation_history` | `HistoryEntry(page_index, scroll_y, zoom)`, `NavigationHistory(limit=100, on_change=None)` with `push`, `back(current)`, `forward(current)`, `replace_current`, `can_go_back`, `can_go_forward`, `current`, `clear` |
| `neoview.ui.password` | `needs_password(path)`, `unlock(doc, password)`, `open_document(path, password)`, `PasswordDialog(parent, file_name)`, `MAX_ATTEMPTS = 3` |
| `neoview.ui.printing` | `print_document(parent, path, current_page=0, password=None) -> bool` |
| `neoview.ui.presentation` | `PresentationWindow(path, start_page=0, password=None, parent=None)`, `present()`, signals `page_changed(int)`, `closed(int)` |

None of these import `MainWindow` or `PdfView`.

## PdfView additions (Phase B, implemented)

All of the methods and signals below exist on `PdfView` now. Note that `doc_path`, `current_page`,
`page_count` and `zoom` are existing *properties* (no parentheses); the new API is methods.

### Page mode

```python
PdfView.set_page_mode(mode: str) -> None   # "single" | "continuous" | "two-page" | "two-page-cover"
PdfView.page_mode() -> str                 # default "continuous"
PdfView.page_mode_changed = Signal(str)
```

- Unknown modes raise `ValueError`. Setting the current mode is a no-op (no signal).
- The current page stays visible across a mode change; reload keeps the mode.
- `"continuous"` is the previous layout bit-for-bit (tested against the old formula).
- `"single"` uses the continuous geometry, but the view shows one page: the other pages are
  hidden and the scene rect is clamped to the current row. `next_page()`/`prev_page()` (and so
  the PgUp/PgDown actions) change page, and the mouse wheel turns the page when it scrolls
  past the page's top or bottom edge (at most one page per 300 ms).
- Two-page modes: pages side by side, rows centred; in `"two-page-cover"` page 1 is alone on
  the right. `next_page()`/`prev_page()` move by a spread, and `current_page` is the first
  (left) page of the spread in view.
- Fit width / fit page fit the current spread (a lone page keeps its half) in two-page modes.
- Not persisted by the view: storing it per document with the other view state is
  MainWindow's job (`page_mode()` on save, `set_page_mode()` on restore).

### Reading colour mode

```python
PdfView.set_color_mode(mode: str) -> None  # "normal" | "night" | "sepia"
PdfView.color_mode() -> str                # default "normal"
PdfView.color_mode_changed = Signal(str)
```

- Applied in the render path (`apply_color_mode` on each page image as it arrives from the
  render scheduler); the colour mode is part of the pixmap cache key, under the same byte
  budget. Changing it re-renders visible pages; until a re-render arrives the page keeps its
  old colours, and switching back to a mode still in the cache is instant.
- Only page content changes; selections, search highlights, annotations and the measure
  rectangle keep their colours. Placeholders use `page_background(mode)`. Night mode also
  switches the canvas to the dark theme's `canvas` token (even in the light theme).
- Not persisted by the view (MainWindow's choice: global or per document). The thumbnail
  panel belongs to MainWindow and does not follow the colour mode yet. Printing and
  presentation always use normal colours.

### Theme

```python
PdfView.apply_theme_colors() -> None   # re-read canvas colour and badge font from the theme
PdfView.canvas_color() -> QColor
```

- The canvas uses `theme.tokens()["canvas"]` and updates by itself when `apply_theme()`
  changes the application palette (PaletteChange/StyleChange); calling `apply_theme_colors()`
  after switching themes is harmless but not required.
- The measurement badge uses the application font (Inter) with tabular figures (`tnum`); a
  widget-level rule overrides the stylesheet's monospace `font-family` for it.

### Back / forward history

```python
PdfView.go_back() -> bool         # False when there is nothing to go back to
PdfView.go_forward() -> bool
PdfView.can_go_back() -> bool
PdfView.can_go_forward() -> bool
PdfView.history_changed = Signal(bool, bool)   # (can_go_back, can_go_forward)
```

- Jumps record history: every `go_to_page()` (outline, page box, thumbnails, go-to dialog),
  `first_page()`, `last_page()`, `scroll_to_rect()` (search results), `scroll_to_page_y()`
  (bookmarks, annotations) and internal link clicks. Plain scrolling, zooming and
  `next_page()`/`prev_page()` do not. A jump that does not move the view records nothing.
- MainWindow's session restore calls `go_to_page()` after opening, so a restored document
  starts with one Back entry (to the top of the document).
- Each jump does `push(location_before)` then `push(location_after)`; consecutive duplicates
  collapse, so repeated jumps to the same spot add nothing.
- `go_back()`/`go_forward()` pass the current location (`back(current=...)`) so returning
  restores where the user actually was, and restore the entry's page, in-page scroll and
  zoom. Restoring must not push: the view sets a `_restoring_history` guard around it.
- History is cleared when a different document is opened; `reload_document()` keeps it,
  clamping page indices to the new page count.
- Suggested shortcuts: Alt+Left / Alt+Right (and the mouse back/forward buttons).

### Opening encrypted documents

```python
PdfView.open_document(path: str, password: str | None = None) -> bool
PdfView.password_required = Signal(str)   # path
PdfView.document_password() -> str | None # the password the open document was unlocked with
```

- `open_document` checks `doc.needs_pass` before anything touches pages (today's
  `page_count == 0` check comes after authentication).
- Encrypted and `password` is None or wrong: close the handle, show no error box, emit
  `password_required(path)` and return False. The current document stays open.
- Correct password: open normally and remember it for `reload_document()` (auto-reload of an
  encrypted file re-authenticates silently; if that fails it emits `password_required`).
- The password is kept in memory only, never in QSettings, the sidecar or the session.

MainWindow handles the signal with the retry loop:

```python
def _on_view_password_required(self, path):
    dlg = PasswordDialog(self, os.path.basename(path))
    for _ in range(MAX_ATTEMPTS):
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return  # cancelled: close the empty tab if one was created for it
        if view.open_document(path, dlg.password()):
            return
        dlg.set_error("Incorrect password. Try again.")
    # three failures: status bar message, tab closed
```

Session restore and recent files must not prompt for several files at once on startup;
prompt when the tab is first shown.

## MainWindow-level calls (Phase B / layout agent)

### Print (Ctrl+P, File > Print..., toolbar `printer` icon)

```python
from neoview.ui.printing import print_document
ok = print_document(self, view.doc_path, view.current_page, view.document_password())
```

Disabled when the tab has no document. `print_document` shows the dialog and returns False
when cancelled. It re-opens the file from disk, so it can raise in normal use: during a LaTeX
rebuild the PDF may be truncated or missing (fitz errors), or re-encrypted (`PermissionError`).
Wrap the call in `try/except Exception` and report the error on the status bar or in a
message box. No message on cancel.

### Presentation (F5, View > Presentation, toolbar `maximize` icon)

```python
from neoview.ui.presentation import PresentationWindow
win = PresentationWindow(view.doc_path, view.current_page, view.document_password())
win.closed.connect(lambda page: (view.go_to_page(page), win.deleteLater()))
self._presentation = win   # keep a reference while open
win.present()
```

The constructor also re-opens the file from disk and can raise for the same reasons as
printing (`PermissionError`, fitz errors, `ValueError` for a PDF with no pages); wrap it the
same way. Disabled when the tab has no document. Only one presentation at a time; F5 while
one is open focuses it. Esc inside the window closes it and the viewer follows to the last shown page.

### Suggested menu/toolbar wiring

| Action | Call | Enabled when | Checked state from |
| --- | --- | --- | --- |
| View > Page Layout > Single / Continuous / Two Pages / Two Pages (Cover) | `set_page_mode` | document open | `page_mode_changed` |
| View > Reading Mode > Normal / Night / Sepia | `set_color_mode` | document open | `color_mode_changed` |
| Go > Back / Forward | `go_back` / `go_forward` | `history_changed` args | - |
| File > Print... | `print_document` | document open | - |
| View > Presentation | `PresentationWindow` | document open | - |

Glyphs: use `printer`, `maximize`, `chevron-left`, `chevron-right` from the bundled Lucide set
(`neoview.ui.icons`, added by the theme work); the Phase A modules do not import it.

## Wiring status

How `MainWindow` (v0.5 layout) is wired against this contract. Every action has a stable
`objectName` so tests and future code can find it with `findChild(QAction, name)`.

| Capability | Action (`objectName`) | Where | Shortcut | Status |
| --- | --- | --- | --- | --- |
| Print | `action_print` | File > Print..., toolbar `printer` | Ctrl+P | Live: `printing.print_document(self, view.doc_path, view.current_page, password)`; errors go to the status bar |
| Presentation | `action_presentation` | View > Presentation, overflow menu | F5 | Live: `PresentationWindow(...).present()`; one at a time, F5 again raises it; on close the viewer goes to the last shown page |
| Page layout | `action_page_mode_single`, `_continuous`, `_two_page`, `_two_page_cover` | View > Page Layout, overflow menu | - | Live: checked state follows `page_mode_changed`; persisted per document |
| Reading mode | `action_color_mode_normal`, `_night`, `_sepia` | View > Reading Mode, overflow menu | - | Live: checked state follows `color_mode_changed`; persisted per document; thumbnails re-render in the reading colours |
| Back / forward | `action_go_back`, `action_go_forward` | Go > Back / Forward, overflow menu | Alt+Left / Alt+Right | Live: enabled from `history_changed` / `can_go_*()` |
| Password | - | prompt on open | - | Live: `PasswordDialog`, up to `MAX_ATTEMPTS`; the password reaches print and presentation via `document_password()` |

How the wiring works (it still degrades to disabled actions for a view without the API):

- `MainWindow._update_capability_actions()` runs on every status update (tab switch, open,
  zoom, page change). Each group is enabled only when the current view has the methods
  (`callable(getattr(view, name, None))`) and a document is open; checked states come from
  `page_mode()` / `color_mode()`, back/forward enablement from `can_go_back()` /
  `can_go_forward()`.
- `_create_tab` connects `page_mode_changed`, `color_mode_changed` and `history_changed` when
  the view has them; each refreshes the actions and schedules a session save.
- The slots (`_set_page_mode`, `_set_color_mode`, `_go_back`, `_go_forward`) are no-ops when
  the method is missing. `ValueError` from a setter is shown on the status bar.
- Page and colour mode are saved per document in `documents/session` (QSettings) next to
  page and zoom, and restored on open before the zoom is applied.
- Password: when `open_document(path)` returns False, the view has `password_required` and
  `password.needs_password(path)` is true, `_open_file` runs the `PasswordDialog` loop inline
  (`MAX_ATTEMPTS`) calling `open_document(path, password)`; a cancelled or failed prompt
  closes the tab that was created for it. `password_required` emitted outside an open (e.g.
  auto-reload of a re-encrypted file) runs the same loop. Print and presentation pass
  `view.document_password()` when the view has it, else None.

