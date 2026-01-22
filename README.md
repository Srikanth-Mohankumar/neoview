# NeoView

NeoView is a production-quality PDF viewer with a rectangular crop/measure tool for Ubuntu 22.04 GNOME (Wayland/X11).

## Features

- **PDF Viewing**: Open and navigate multi-page PDFs
- **Zoom**: Pinch gestures, Ctrl+wheel, Fit Width, Actual Size
- **Selection Tool**: Click+drag to create measurement rectangle
- **Precise Adjustment**: Drag edges/corners to resize, keyboard nudges
- **Measurements**: Live display in points, picas, and millimeters
- **Export**: Save selection as PNG at 150/300/600 DPI
- **Auto-reload**: Watch file for external changes
- **Container-ready**: Works with Wayland or X11 forwarding

## Requirements

- Python 3.10+
- PySide6
- PyMuPDF

## Installation

```bash
pip install neoview
```

### Install from source (launchable)

```bash
pip install .
```

This installs a `neoview` launcher. Run it to open the app, then use File → Open to choose a PDF.

Optional desktop launcher (Linux):

```bash
./install_desktop.sh
```

## Usage

### Direct Run

```bash
# Open with file dialog
python pdf_crop_measure.py

# Open specific PDF
python pdf_crop_measure.py /path/to/document.pdf
```

### Installed App

```bash
# Open the app
neoview

# Open specific PDF
neoview /path/to/document.pdf
```

### Container Run

**Build:**
```bash
docker build -t pdf-measure .
```

**Wayland (GNOME Wayland - preferred):**
```bash
docker run -it --rm \
  -e XDG_RUNTIME_DIR=/run/user/$(id -u) \
  -e WAYLAND_DISPLAY=$WAYLAND_DISPLAY \
  -e QT_QPA_PLATFORM=wayland \
  -v $XDG_RUNTIME_DIR/$WAYLAND_DISPLAY:/run/user/$(id -u)/$WAYLAND_DISPLAY \
  -v /path/to/pdfs:/pdfs \
  pdf-measure /pdfs/document.pdf
```

**X11 (fallback, most compatible):**
```bash
xhost +local:docker
docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -e QT_QPA_PLATFORM=xcb \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /path/to/pdfs:/pdfs \
  pdf-measure /pdfs/document.pdf
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Open PDF file |
| `Ctrl+Q` | Exit application |
| `Ctrl+C` | Copy measurements to clipboard |
| `Ctrl+S` | Export selection as PNG |
| `PgUp` / `PgDn` | Previous / Next page |
| `Ctrl+Wheel` | Zoom in/out |
| `W` | Fit to width |
| `1` | Actual size (100%) |
| `Arrow` | Move selection by 1 pt |
| `Shift+Arrow` | Move selection by 10 pt |
| `Ctrl+Arrow` | Resize selection by 1 pt |
| `Ctrl+Shift+Arrow` | Resize selection by 10 pt |
| `Escape` | Clear selection |

## Selection Tool

1. **Create**: Click and drag on the PDF page
2. **Move**: Drag inside the selection
3. **Resize**: Drag edges or corners
4. **Fine-tune**: Use arrow keys with modifiers
5. **Measure**: See live measurements in status bar

All measurements are in PDF coordinate space (points) and remain accurate at any zoom level.

## Export

1. Create a selection
2. Press `Ctrl+S` or click Export button
3. Choose DPI (150/300/600)
4. Save as PNG

## Auto-reload

Enable "Auto-reload on file change" in Options menu to automatically refresh when the PDF is modified externally. Selection and page position are preserved.

## License

MIT
