# NeoView

NeoView is a free all-in-one desktop PDF viewer for Linux and Windows. It brings together font inspection, measurement, crop/export, annotations, search, bookmarks, thumbnails, and reload in one practical workspace.

It started as a precise crop and measurement tool, and has grown into a practical review app for LaTeX, proofreading, QA, layout checks, and document-inspection workflows where a normal PDF reader is not enough.

## Why NeoView

Most free PDF viewers only cover part of the workflow. NeoView is built for the moments where you need more than reading:

- inspect fonts and text details
- measure layout regions precisely
- crop/export selected areas
- annotate and review in place
- search, bookmark, and navigate longer PDFs
- reload changing PDFs without losing your session

## Highlights

- Free all-in-one PDF viewer for technical review workflows
- Live PDF reload while external tools rebuild the file
- Multi-tab viewing with per-document session restore
- Text find panel with live results, search navigation, and highlight overlays
- Outline, bookmarks, thumbnails, and page info side panels
- Measurement and rectangular selection tools with pt, pica, and mm readouts
- Crop/export workflow for selected regions as PNG
- Annotation workflows:
  - highlight, underline, note
  - rectangle, ellipse, text-box, line, arrow, freehand
  - on-canvas drawing and properties editing
  - export a PDF copy with annotations embedded
- Native PDF annotation visibility in the viewer
- Font inspection for text under the cursor
- PNG export from selections at multiple DPI values
- Keyboard-driven navigation, editing, and selection adjustment
- Automated test coverage for logic and Qt interaction flows

## Repo Overview

### Main code areas

- [src/neoview/ui](src/neoview/ui)  
  Qt main window, viewer widget, dialogs, annotation UI, toolbars, and page rendering.
- [src/neoview/models](src/neoview/models)  
  Typed state records for annotations, bookmarks, search results, and per-tab state.
- [src/neoview/persistence](src/neoview/persistence)  
  Sidecar storage for annotations and bookmarks.
- [src/neoview/utils](src/neoview/utils)  
  Small helpers such as unit formatting.
- [src/neoview/assets](src/neoview/assets)  
  Packaged icons and app assets.
- [tests](tests)  
  Fast pytest coverage, including `pytest-qt` interaction tests.

### Important entry points

- App entry: [src/neoview/app.py](src/neoview/app.py)
- Main window: [src/neoview/ui/main_window.py](src/neoview/ui/main_window.py)
- Viewer widget: [src/neoview/ui/pdf_view.py](src/neoview/ui/pdf_view.py)
- Legacy shim: [pdf_crop_measure.py](pdf_crop_measure.py)
- Website page: [docs/index.html](docs/index.html)

## Feature Overview

NeoView is designed to reduce tool switching. Instead of opening one app for reading, another for measuring, another for markup, and another for export, it keeps the common PDF review tasks in one place.

### Viewing and navigation

- Open one or many PDFs in tabs
- Reuse an already-open tab for the same file
- Page navigation with page combo, PgUp/PgDn, Home/End
- Fit Width, Fit Page, Actual Size, custom zoom, Ctrl+wheel, and pinch zoom
- Rotation controls and fullscreen mode
- Outline panel for PDF table of contents
- Thumbnail panel for quick page jumping
- Page info / document info panel

### Search

- Find panel with live typing updates
- Explicit next/previous search navigation
- Highlight overlays for current and visible-page matches
- Search state preserved per tab
- Batched search execution to keep the UI responsive on larger PDFs

### Selection and measurement

- Drag to create a selection rectangle
- Resize by handles or keyboard
- Move by drag or keyboard
- Measurements in points, picas, and millimeters
- Copy measurement values to the clipboard
- Export selection as PNG at multiple DPI levels

### Annotations

- Create annotations from a selection or directly on the canvas
- Supported types include:
  - highlight
  - underline
  - note
  - text-box
  - rectangle
  - ellipse
  - line
  - arrow
  - freehand
- Annotation list with filtering
- Annotation properties editing
- Delete annotations from the list, keyboard, or context menu
- Export annotated PDF copies
- Read-only viewing of annotations already embedded in the source PDF

### Bookmarking and session behavior

- Add custom bookmarks per document
- Rename and delete bookmarks
- Restore last page and zoom per file
- Auto-reload on file changes for LaTeX / Typst / generated PDF workflows

## Requirements

- Python 3.10+
- PySide6
- PyMuPDF

## Installation

### Install from PyPI

```bash
pip install neoview
```

### Install from source

```bash
python3 -m pip install .
```

### Editable development install

```bash
python3 -m pip install -e .[dev]
```

### Recommended local launcher

```bash
./run.sh
```

This bootstraps a virtual environment and launches NeoView.

## Running NeoView

### Installed command

```bash
neoview
neoview /path/to/document.pdf
```

### Module entry

```bash
python -m neoview
```

### Legacy shim

```bash
python pdf_crop_measure.py
python pdf_crop_measure.py /path/to/document.pdf
```

## Windows

### Install via pip

```powershell
py -m pip install neoview
neoview
```

### Standalone executable

Tagged releases can include a prebuilt `neoview.exe` from GitHub Releases.

### Build the Windows executable yourself

```powershell
py -m pip install .[dev]
pyinstaller neoview.spec
```

Output:

```text
dist\neoview.exe
```

## Advanced Usage

Container usage exists for niche reproducible-environment or development scenarios, but it is not a primary installation path for NeoView. Most users should prefer the native Linux install or the Windows executable.

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Open PDF |
| `Ctrl+Q` | Quit |
| `Ctrl+F` | Find |
| `Ctrl+Shift+F` | Toggle search panel |
| `Ctrl+Shift+O` | Toggle navigation panel |
| `Ctrl+Shift+T` | Toggle thumbnails panel |
| `Ctrl+Shift+I` | Toggle page info panel |
| `Ctrl+D` | Add bookmark |
| `Ctrl+Wheel` | Zoom in or out |
| `W` | Fit width |
| `F` | Fit page |
| `Ctrl+1` | Actual size |
| `PgUp` / `PgDn` | Previous / next page |
| `Home` / `End` | First / last page |
| `Ctrl+L` / `Ctrl+R` | Rotate left / right |
| `Ctrl+0` | Reset rotation |
| `Ctrl+C` | Copy measurements or selected text context |
| `Ctrl+S` | Export selection as PNG |
| `Ctrl+Shift+H` | Add highlight from selection |
| `Ctrl+Shift+U` | Add underline from selection |
| `Ctrl+Shift+N` | Add note from selection |
| `Arrow` | Move selection by 1 pt |
| `Shift+Arrow` | Move selection by 10 pt |
| `Ctrl+Arrow` | Resize selection by 1 pt |
| `Ctrl+Shift+Arrow` | Resize selection by 10 pt |
| `Delete` / `Backspace` | Delete selected annotation |
| `Escape` | Clear selection |

## Development

### Install dependencies

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e .[dev]
```

### Run tests

```bash
PYTHONPATH=src pytest -q
```

On Windows PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
```

### Current automated coverage

- Unit tests for measurement and state helpers
- Sidecar persistence tests
- UI behavior tests for reload, session restore, and navigation
- `pytest-qt` interaction tests for:
  - search
  - reload
  - thumbnails
  - outline navigation
  - bookmarks
  - annotation create/edit/delete flows
  - export flows
  - text selection and copy

The suite is intended to stay fast enough for local development and CI.

## Packaging

- Canonical metadata: [pyproject.toml](/data/neopage/repos/neoview/pyproject.toml)
- Older editable-install support: [setup.py](/data/neopage/repos/neoview/setup.py)
- Windows build spec: [neoview.spec](/data/neopage/repos/neoview/neoview.spec)
- Publish helper: [publish.sh](/data/neopage/repos/neoview/publish.sh)

## License

MIT
