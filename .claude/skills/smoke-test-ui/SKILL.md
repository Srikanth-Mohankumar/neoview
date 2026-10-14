---
name: smoke-test-ui
description: Launch the real NeoView window offscreen on a PDF, drive open/zoom/navigate/search/measure/reload, and save a screenshot per step. Use after any change to main_window.py, pdf_view.py, page_item.py, selection.py, theme.py or dialogs, when asked to "run the app", "check it works", "take a screenshot", or before a release - pytest alone never renders the window.
---

# Smoke-test the NeoView UI

The pytest suite exercises logic with minimal rendering, so a change can pass every test and
still draw a blank page, a broken dock or an unreadable dark theme. This skill runs the real
`MainWindow` and gives you pictures to look at.

## Run

```bash
.venv/bin/python .claude/skills/smoke-test-ui/scripts/smoke.py --out <scratchpad>/smoke-light
.venv/bin/python .claude/skills/smoke-test-ui/scripts/smoke.py --out <scratchpad>/smoke-dark --theme dark
```

Options: `--pdf <file>` to use a real document instead of the generated 3-page one (the
search step then only reports the hit count); `--visible` to show a real window when the user
wants to watch.

Write screenshots to the session scratchpad, never into the repo.

The script swaps `MainWindow`'s `QSettings` for a temp INI file. That matters: NeoView's
`QSettings("NeoView", "NeoView")` is NativeFormat (`~/.config/NeoView/NeoView.conf` on Linux,
the registry on Windows), and `QSettings.setPath(IniFormat, ...)` does not redirect it. If you
launch the app any other way for testing, isolate settings the same way or you will overwrite
the user's recent files and session.

## Read the result

The script prints one JSON line per step (`ok`, `detail`, `shot`) and a final summary;
exit code 1 means a step failed. A pass is necessary, not sufficient - open the screenshots
with the Read tool and check what the change was supposed to affect:

- page content rendered (not blank or grey), one tab per opened file
- zoom percentage in the toolbar and status bar agree
- search hits highlighted on the page and listed in the Search dock
- the measure rectangle and its W/H/X/Y badge drawn on the page
- in the dark theme: text readable in docks, toolbar and dialogs

## Extend

When a change adds a user-visible flow (new tool mode, dock, dialog), add a step to
`scripts/smoke.py` mirroring the existing ones - call the same method the UI action calls, pump
events, assert on state, screenshot. The script uses some private `MainWindow`/`PdfView`
methods (`_open_file`, `_execute_search_current`, `_create_selection_on_page`); if a step fails
with `AttributeError`, the internals were renamed - update the script, it is not an app bug.

Report: the summary line, any failed step with its error, and the screenshots that show the
change (paths), plus anything that looks wrong in them even if the step passed.
