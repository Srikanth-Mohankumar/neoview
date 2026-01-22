# CLAUDE.md

Notes for automated agents working in this repository.

## Repo overview
- NeoView is a PDF viewer with measurement and text selection tools.
- Primary code lives in `src/neoview/` (src layout).
- Main entry point: `neoview.app:main`.
- Legacy shim: `pdf_crop_measure.py` (kept for backward compatibility).

## Key directories
- `src/neoview/ui/` — Qt UI widgets, viewer, dialogs.
- `src/neoview/utils/` — small helpers (units).
- `src/neoview/assets/` — icons and packaged assets.
- `tests/` — pytest tests (lightweight UI logic, no heavy GUI).

## Development setup
- Recommended local run:
  - `./run.sh` (auto-creates venv and launches app).
- Manual venv:
  - `python3 -m venv .venv`
  - `. .venv/bin/activate`
  - `python -m pip install -e .[dev]`

## Tests
- Run: `.venv/bin/python -m pytest`
- Tests are minimal and should remain fast.

## Packaging
- `pyproject.toml` is canonical metadata.
- `setup.py` exists for editable installs on older tooling.
- `publish.sh` builds, checks, and uploads to PyPI using `~/.pypirc`.
- Version is in `pyproject.toml`; PyPI does not allow re-upload of the same version.

## Windows executable
- PyInstaller spec: `neoview.spec`.
- CI build workflow: `.github/workflows/windows-build.yml` builds `dist/neoview.exe` on Windows and attaches to GitHub Releases for tags.
- Building `.exe` should be done on Windows (or via GitHub Actions).

## UI notes
- Theme is light (`src/neoview/theme.py`).
- Status bar includes a subtle credit label.
- Docks: Search, Outline, Thumbnails, Page Info.
- Avoid heavy UI blocking calls on large PDFs.

## Quality/compatibility
- Linux and Windows are supported in docs; ensure changes remain cross-platform.
- Avoid Linux-only paths in core logic.

## Style guidance
- Keep changes modular; prefer adding new UI elements in `main_window.py` and view logic in `pdf_view.py`.
- Maintain ASCII-only edits unless existing file contains Unicode.
