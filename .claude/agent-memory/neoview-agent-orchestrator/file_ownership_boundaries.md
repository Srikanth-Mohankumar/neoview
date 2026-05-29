---
name: file-ownership-boundaries
description: Which NeoView files each specialist subagent owns — used to keep agent responsibilities non-overlapping.
metadata:
  type: project
---

Crisp file-to-agent ownership for the NeoView suite. Use this when emitting agent specs so two agents don't both claim the same file and produce conflicting patches.

- `pdf_view.py` (~1450 lines): primary owner render-auditor; secondary interaction-auditor (input paths), bug-sweeper (signal/slot, shutdown), perf-profiler (instrumentation only).
- `page_item.py`: render-auditor (LRU cache, lazy placeholder, 2x scale), perf-profiler (cache hit-rate counters).
- `main_window.py` (~2200 lines): ui-polish-reviewer (menus/toolbar/docks/theme), interaction-auditor (shortcuts), bug-sweeper (signal connections in __init__).
- `persistence/sidecar_store.py`: persistence-auditor only.
- `models/view_state.py`: persistence-auditor (schema), render-auditor (TabContext zoom/rotation fields).
- `theme.py`: ui-polish-reviewer only.
- `app.py`: cross-platform-checker (HiDPI attrs), ui-polish-reviewer (theme env var), security-scanner (argv handling).
- `neoview.spec` + `.github/workflows/windows-build.yml`: cross-platform-checker (audit), build-packager (validate build).
- `pyproject.toml`: lint-checker (ruff config), security-scanner (dependency CVEs), build-packager (metadata). Version field is release-coordinator-only.
- `tests/conftest.py` and `tests/*`: regression-tester writes new tests; fix-implementer extends as fixes warrant.

**Why:** in a prior pass overlapping responsibilities caused two agents to patch the same lines differently. The implementer then had to reconcile, wasting a wave.

**How to apply:** when drafting any agent's `filesOfInterest` list, cross-check this boundary table. If two agents must read the same file, ensure their concerns are orthogonal (e.g., render-auditor reads pdf_view.py for rendering math; interaction-auditor reads it for event handlers).

Related: [[composition-premium-hardening]].
