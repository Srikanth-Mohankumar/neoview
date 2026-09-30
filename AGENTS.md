# NeoView — agent notes

NeoView is a PySide6/PyMuPDF PDF viewer with measurement tools, text selection, annotations,
bookmarks, and auto-reload for LaTeX workflows. It targets Linux and Windows. Code lives in
`src/neoview/` (src layout); the CLI entry point is `neoview.app:main`. See `ARCHITECTURE.md`
for the package layout.

## Commands

```bash
./run.sh                                                   # run the app (auto-creates .venv)
python3 -m venv .venv && . .venv/bin/activate && pip install -e .[dev]   # manual setup
.venv/bin/python -m pytest                                 # all tests
.venv/bin/python -m pytest tests/test_units.py::test_pt_to_mm           # one test
.venv/bin/ruff check .                                     # lint
.venv/bin/python -m build --sdist --wheel                  # build distributions
```

`twine` is not in the `dev` extras; `./publish.sh` installs it, runs `twine check`, and uploads.

## Architecture

- `app.py:main()` creates the `QApplication`, applies `LIGHT_STYLE` or `DARK_STYLE` from
  `theme.py` (light by default, dark when `NEOVIEW_THEME=dark`), and opens `MainWindow` with an
  optional PDF path from argv.
- `ui/main_window.py` — `MainWindow`: menus, toolbar, status bar, tabs (`QTabWidget`, one
  `PdfView` per tab), and the dock panels (Search, Navigation, Thumbnails, Inspector).
- `ui/pdf_view.py` — `PdfView` (a `QGraphicsView`): rendering, input, zoom, and tool modes
  (`ToolMode`). Its scene holds one `PageItem` per page (`ui/page_item.py`, PyMuPDF render at
  2x with a shared LRU pixmap cache), the measurement `SelectionRect` (`ui/selection.py`), and
  highlight/annotation items.
- `PdfView` communicates with `MainWindow` only through Qt signals, which `MainWindow` connects to
  `_on_view_*` handlers. `PdfView` never references `MainWindow` directly; keep it that way.
- `models/view_state.py` — dataclasses (`TabContext`, `AnnotationRecord`, `BookmarkRecord`,
  `DocumentSidecarState`, `SearchMatch`).
- `persistence/sidecar_store.py` — reads/writes `<pdf>.neoview.json` sidecars (annotations,
  bookmarks); corrupt files are renamed to `.broken.<stamp>`. Sidecar saves are debounced with
  per-view `QTimer`s. `QSettings` holds window geometry, recent files, session and per-document
  view state.

Where to add things: UI elements (menus, toolbar buttons, docks) in `main_window.py`; viewer
behaviour in `pdf_view.py`; data models in `models/view_state.py`; persistence in
`persistence/sidecar_store.py`; unit helpers in `utils/units.py`.

## Tests

- `tests/conftest.py` provides a session-scoped `_qt_app` and autouse `_isolated_qsettings`.
- Integration tests build temporary PDFs with `fitz.open()` and flush the event loop with
  `QApplication.processEvents()`; external calls (QDesktopServices, dialogs) are mocked with
  `monkeypatch`.
- Keep tests fast — no heavy GUI rendering.

## Packaging and CI

- `pyproject.toml` is the canonical metadata source, including the version. `setup.py` exists
  only for older editable-install tooling. PyPI does not allow re-uploading a version.
- CI (`.github/workflows/ci.yml`): ruff + pytest + build on Ubuntu (3.10/3.11/3.12) and
  Windows (3.10).
- Windows `.exe`: PyInstaller (`neoview.spec`) in `.github/workflows/windows-build.yml`, attached
  to GitHub Releases on tag push. Build it on Windows or via Actions.

## Conventions

- Keep core logic cross-platform; no Linux-only paths or APIs.
- Avoid blocking UI calls on large PDFs.
- `pdf_crop_measure.py` is a legacy entry-point shim — keep it, don't extend it.
- Keep edits ASCII-only unless the file already contains Unicode.
