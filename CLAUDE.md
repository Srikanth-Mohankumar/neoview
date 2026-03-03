# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is NeoView

NeoView is a PySide6/PyMuPDF PDF viewer with measurement tools, text selection, annotations, bookmarks, and auto-reload for LaTeX workflows. It targets Linux and Windows.

## Common commands

```bash
# Run the app (auto-creates venv)
./run.sh

# Manual setup
python3 -m venv .venv && . .venv/bin/activate && pip install -e .[dev]

# Run all tests
.venv/bin/python -m pytest

# Run a single test
.venv/bin/python -m pytest tests/test_units.py::test_pt_to_mm

# Lint
.venv/bin/ruff check .

# Build distributions
.venv/bin/python -m build --sdist --wheel

# Verify build metadata
.venv/bin/python -m twine check dist/*
```

## Architecture

### Entry point and bootstrap

`app.py:main()` creates QApplication, applies theme (light/dark via `NEOVIEW_THEME` env var), loads the app icon, and opens `MainWindow` with an optional PDF path from argv.

### Core widget hierarchy

```
MainWindow (main_window.py ~2200 lines)
 └─ QTabWidget (multi-tab support)
     └─ PdfView (pdf_view.py ~1450 lines) — one per tab
         └─ QGraphicsScene
             ├─ PageItem (page_item.py) — one per PDF page, renders via PyMuPDF at 2x
             ├─ SelectionRect (selection.py) — measurement rectangle with drag handles
             └─ QGraphicsRectItems — search highlights, annotations, text selection, link hovers
```

`MainWindow` orchestrates menus, toolbar, status bar, and four dock panels (Search, Outline, Thumbnails, Page Info). `PdfView` handles all rendering, input, zoom, and tool modes (Select/Hand/Measure). `PageItem` manages per-page pixmap rendering with an LRU cache (96 items).

### Signal/slot communication

PdfView emits signals (`selection_changed`, `zoom_changed`, `page_changed`, `text_info_changed`, `text_selected`, `annotation_clicked`, `document_loaded`) that MainWindow connects to `_on_view_*` handler methods. This is the primary communication pattern — PdfView never references MainWindow directly.

### Data model and persistence

- `models/view_state.py` — dataclasses: `TabContext` (per-tab state), `AnnotationRecord`, `BookmarkRecord`, `DocumentSidecarState`, `SearchMatch`
- `persistence/sidecar_store.py` — reads/writes `{pdf_path}.neoview.json` sidecar files for annotations and bookmarks. Handles corrupt files by renaming to `.broken.*`.
- `QSettings` stores window geometry, recent files, session state, and per-document view state.
- Sidecar saves are debounced via QTimer to avoid rapid I/O.

### Theme

`theme.py` defines `LIGHT_STYLE` and `DARK_STYLE` Qt stylesheets. Light uses Segoe UI; dark uses JetBrains Mono.

## Where to add things

- **New UI elements** (menus, toolbar buttons, docks): `main_window.py`
- **Viewer behavior** (input handling, rendering, tool modes): `pdf_view.py`
- **New data models**: `models/view_state.py`
- **New persistence**: `persistence/sidecar_store.py`
- **Unit conversions / helpers**: `utils/units.py`

## Testing patterns

- Tests use a session-scoped `_qt_app` fixture and autouse `_isolated_qsettings` for isolation (see `tests/conftest.py`).
- Integration tests create temporary PDFs via `fitz.open()` and use `QApplication.processEvents()` to flush the Qt event loop.
- External calls (QDesktopServices, dialogs) are mocked via `monkeypatch`.
- Tests should remain fast — no heavy GUI rendering.

## Packaging and CI

- `pyproject.toml` is the canonical metadata source. Version lives there.
- `setup.py` exists only for older editable-install tooling.
- CI (`.github/workflows/ci.yml`): lint (ruff) + test (pytest) + build on Ubuntu (3.10/3.11/3.12) and Windows (3.10).
- Windows .exe: built via PyInstaller (`neoview.spec`) in `.github/workflows/windows-build.yml`, attached to GitHub Releases on tag push.
- PyPI publishing: `./publish.sh` (requires `~/.pypirc`). PyPI does not allow re-upload of the same version.

## Cross-platform notes

- Avoid Linux-only paths or APIs in core logic.
- `pdf_crop_measure.py` is a legacy entry-point shim — keep but don't extend.
- Maintain ASCII-only edits unless the existing file already contains Unicode.
