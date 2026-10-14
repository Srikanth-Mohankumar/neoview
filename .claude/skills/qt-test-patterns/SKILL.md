---
name: qt-test-patterns
description: NeoView's conventions for pytest and pytest-qt tests of PySide6 widgets - fixtures in tests/conftest.py, building PDFs with fitz, flushing the event loop, qtbot waits, mocking dialogs, and cleanup that keeps the suite from leaking memory. Use whenever writing, fixing or reviewing anything under tests/, or when a Qt test is flaky, hangs, or passes alone but fails in the full run.
---

# NeoView Qt test patterns

The suite (`.venv/bin/python -m pytest`, ~120 tests, under a minute) runs offscreen on Linux
and Windows in CI. Keep new tests in that shape: fast, no real rendering waits, no dialogs.

## What conftest.py already gives you (autouse)

- `_qt_app` (session): one `QApplication`, `QT_QPA_PLATFORM=offscreen` by default.
- `_isolated_qsettings`: meant to give each test empty settings.
  **Known gap:** it redirects only `IniFormat`, but `MainWindow` uses
  `QSettings("NeoView", "NeoView")`, which is NativeFormat, so tests currently read and clear
  the developer's real `~/.config/NeoView/NeoView.conf` (the registry on Windows). Until that
  is fixed, don't add tests that depend on pre-existing settings, and don't "fix" a test by
  writing settings it expects to find.
- `_release_page_pixmap_cache`: clears `PageItem._PIXMAP_CACHE` and runs `gc` after each test.

Don't re-create these per test, and don't instantiate a second `QApplication`.

## Build inputs, never ship fixtures

Generate PDFs in `tmp_path` with PyMuPDF; there are no checked-in PDF fixtures.

```python
def _make_pdf(path: Path, n_pages: int = 3) -> None:
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"page {i + 1} search-target")
    doc.save(str(path))
    doc.close()
```

Size pages explicitly when the test is about geometry (zoom, fit, measurement): the expected
numbers then follow from the page size, not from whatever the default was.

## Drive widgets, then flush

- A widget must be shown and the loop flushed before geometry is meaningful:
  `view.resize(800, 600); view.show(); QApplication.processEvents()`.
- After any action that schedules work (zoom, open, search), call
  `QApplication.processEvents()` again before asserting.
- When the result arrives via a timer or debounce, use pytest-qt instead of sleeping:
  `qtbot.waitUntil(lambda: <condition>, timeout=3000)`. `time.sleep` makes tests slow and
  still flaky on a loaded CI runner.
- Simulated input: `qtbot.keyClicks(win._search_input, "text")`,
  `qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)`. Register top-level windows with
  `qtbot.addWidget(win)` so they are closed even when the test fails.

## Isolate side effects with monkeypatch

- Modal dialogs would block an offscreen run forever. Patch them:
  `monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Mark A", True))`.
  Same for `QFileDialog`, `QMessageBox`, `QDesktopServices.openUrl`.
- To assert *that* something was requested without doing it, record calls:
  `monkeypatch.setattr(view, "go_to_page", lambda idx: jumps.append(idx))`.
- Simulate I/O failure by patching the primitive (e.g. `os.replace`) rather than corrupting
  real files.

## Clean up what you open

Open documents and windows hold PageItems, effects and pixmaps; a suite that forgets to close
them runs out of memory when tests run together. Close in `try/finally` (or use
`qtbot.addWidget`):

```python
view = PdfView(); view.show(); view.open_document(str(pdf))
try:
    ...
finally:
    view.close_document()
    view.close()
```

## Assertions

- Derive expected values from the input (page size x zoom, number of pages containing the
  query), never from running the code and pasting what it printed - that freezes bugs in.
- Compare floats with tolerance (`pytest.approx`, or "within 2 viewport pixels" for
  view-mapping tests as `tests/test_zoom_anchor.py` does).
- Test through the public `PdfView`/`MainWindow` API where one exists; private helpers
  (`_open_file`, `_create_selection_on_page`) are fine when the UI path has no public method.
- A new test should fail on the code before the fix and pass after; check both.

## Where to put it

Follow the existing split: `test_units.py` (pure helpers), `test_selection.py`,
`test_sidecar_store.py` (persistence), `test_keyboard_navigation.py`, `test_zoom_anchor.py`,
`test_qt_interactions.py` (qtbot-driven flows), `test_ui_behavior.py` (MainWindow behaviour),
`test_performance_mode.py`, `test_professional_features.py` (feature flows: tabs, drag and
drop, rulers, layout grid, bookmarks, highlights, reload, session restore).
Run one file while iterating: `.venv/bin/python -m pytest -q tests/<file>.py`; run the full
suite before finishing - order-dependent leaks only show up there.
