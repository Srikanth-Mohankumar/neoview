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

## PdfView additions (Phase B)

### Page mode

```python
PdfView.set_page_mode(mode: str) -> None   # "single" | "continuous" | "two-page" | "two-page-cover"
PdfView.page_mode() -> str                 # default "continuous"
PdfView.page_mode_changed = Signal(str)
```

- Unknown modes raise `ValueError`. Setting the current mode is a no-op (no signal).
- The current page stays visible across a mode change.
- `"continuous"` keeps today's layout exactly (`layout_pages(..., viewport_width=0)` reproduces
  `_layout_pages`).
- `"single"` uses the continuous geometry, but the view shows one page: the scene rect is
  clamped to `PageLayout.row_bounds(row_of(current_page))` and next/previous page, PageUp/
  PageDown and scrolling past the page edge move one page.
- Two-page modes: pages side by side, rows centred; in `"two-page-cover"` page 1 is alone on
  the right. `next_page()`/`prev_page()` move by a row (two pages).
- Fit width / fit page fit the widest row, not a single page, in two-page modes.
- Persisted per document with the other view state (QSettings), not in the sidecar.

### Reading colour mode

```python
PdfView.set_color_mode(mode: str) -> None  # "normal" | "night" | "sepia"
PdfView.color_mode() -> str                # default "normal"
PdfView.color_mode_changed = Signal(str)
```

- Applied in the render path (`apply_color_mode` on the rendered page image before it becomes
  a pixmap); the colour mode is part of the pixmap cache key. Changing it re-renders visible
  pages.
- Only page content changes; selections, search highlights, annotations and the measure
  rectangle keep their colours. The scene background stays theme-controlled;
  `page_background(mode)` gives the matching paper colour for placeholders.
- Thumbnails follow the view's colour mode. Printing and presentation always use normal
  colours.

### Back / forward history

```python
PdfView.go_back() -> bool         # False when there is nothing to go back to
PdfView.go_forward() -> bool
PdfView.can_go_back() -> bool
PdfView.can_go_forward() -> bool
PdfView.history_changed = Signal(bool, bool)   # (can_go_back, can_go_forward)
```

- Jumps record history: link clicks, outline/bookmark clicks, search results, go-to-page
  (dialog or page box), first/last page and thumbnail clicks. Plain scrolling, zooming and
  next/previous page do not.
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
ok = print_document(self, view.doc_path(), view.current_page(), view.document_password())
```

Disabled when the tab has no document. `print_document` shows the dialog and returns False
when cancelled. It re-opens the file from disk, so it can raise in normal use: during a LaTeX
rebuild the PDF may be truncated or missing (fitz errors), or re-encrypted (`PermissionError`).
Wrap the call in `try/except Exception` and report the error on the status bar or in a
message box. No message on cancel.

### Presentation (F5, View > Presentation, toolbar `maximize` icon)

```python
from neoview.ui.presentation import PresentationWindow
win = PresentationWindow(view.doc_path(), view.current_page(), view.document_password())
win.closed.connect(lambda page: (view.go_to_page(page), win.deleteLater()))
self._presentation = win   # keep a reference while open
win.present()
```

The constructor also re-opens the file from disk and can raise for the same reasons as
printing (`PermissionError`, fitz errors, `ValueError` for a PDF with no pages); wrap it the
same way. Disabled when the tab has no document. Only one presentation at a time; F5 while one is open
focuses it. Esc inside the window closes it and the viewer follows to the last shown page.

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
| Page layout | `action_page_mode_single`, `_continuous`, `_two_page`, `_two_page_cover` | View > Page Layout, overflow menu | - | Waiting for Phase B: disabled until the view has `set_page_mode` and `page_mode` |
| Reading mode | `action_color_mode_normal`, `_night`, `_sepia` | View > Reading Mode, overflow menu | - | Waiting for Phase B: disabled until the view has `set_color_mode` and `color_mode` |
| Back / forward | `action_go_back`, `action_go_forward` | Go > Back / Forward, overflow menu | Alt+Left / Alt+Right | Waiting for Phase B: disabled until the view has `go_back`, `go_forward`, `can_go_back`, `can_go_forward`; enabled per `can_go_*()` |
| Password | - | prompt on open | - | Waiting for Phase B: used when the view has `password_required` |

How the Phase B hooks work, so the methods only need to appear on `PdfView`:

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

