---
name: lint-ratchet
description: Adopt stricter ruff rules in NeoView one rule family at a time - measure, autofix or hand-fix, test, then add the family to [tool.ruff.lint] select in its own commit so CI never goes red. Use when asked to tighten lint, enable new ruff rules, modernize type hints, sort imports, clean up ruff warnings, or when a ruff upgrade suddenly reports hundreds of errors.
---

# Lint ratchet

`pyproject.toml` pins the lint rules to ruff's classic defaults:

```toml
[tool.ruff.lint]
select = ["E4", "E7", "E9", "F"]
```

That pin exists because ruff 0.17 widened its defaults and CI (which installs the latest ruff)
failed with 221 findings overnight. The ratchet tightens the rule set deliberately instead:
one family per commit, each commit green, so a reviewer can read the diff and `git bisect`
still works.

## Before starting

- Compare versions: `.venv/bin/ruff --version` vs the version CI installs (the Lint step log in
  `gh run view <id> --log`). Rules and autofixes differ between versions; if they differ,
  measure with the CI version in a scratch venv (`python -m venv <scratchpad>/ruff && <scratchpad>/ruff/bin/pip install ruff==<ver>`).
- Start from a clean tree on a branch. Never mix a ratchet commit with feature work.

## One iteration

1. **Measure** the candidate family:
   `.venv/bin/ruff check . --select <FAMILY> --statistics`
2. **Fix**:
   - Safe autofixes: `.venv/bin/ruff check . --select <FAMILY> --fix`.
   - `--unsafe-fixes` only after reading what each one changes; they can alter behaviour.
   - Rules that flag a judgment call (e.g. `BLE001` blind except, `S110` try/except/pass)
     need a per-site decision: narrow the exception, log it, or keep it with a
     `# noqa: BLE001 - <reason>` when swallowing is intentional (UI must not crash on a
     malformed PDF). If most sites are intentional, ignore the rule in config with a comment
     rather than scattering noqa.
3. **Verify**: `.venv/bin/ruff check .` (with the family added) and
   `.venv/bin/python -m pytest -q`. For changes that touch UI code paths, run the
   `smoke-test-ui` skill as well.
4. **Ratchet**: add the family to `select` (or a specific code to `ignore` with a reason) in the
   same commit as the fixes:
   `lint: enable <FAMILY> (<n> fixes, <m> noqa)`.

Stop and ask before a family whose fixes touch more than a few hundred lines or change runtime
behaviour - the user may prefer to skip it.

## Suggested order (whole-family `--select` counts, ruff 0.15.21 and 0.17.0 agree, 2026-10-14; re-measure, numbers drift)

| Family | Findings then | Nature |
|---|---:|---|
| `I` (isort) | 24 | autofix, zero behaviour risk - start here |
| `UP` (pyupgrade) | 149 (mostly UP006, UP045, UP035) | autofix; target is inferred from `requires-python = ">=3.10"`, so `Optional[X]` -> `X \| None` is safe on all CI Pythons |
| `SIM`, `FURB`, `PLR1730` | 17 | mostly mechanical, review each |
| `RUF` | 11 | review; `RUF012` mutable class default may hint at a real bug |
| `BLE`, `S110` | 31 | judgment per site (see above) |
| `EXE001` | 1 | shebang on a non-executable file: fix the mode or drop the shebang |

`UP` is large; split it by code (`--select UP006`, then `UP045`, ...) if the diff gets hard to
review.

Report per iteration: family, counts before/after, autofixed vs hand-fixed vs noqa/ignored,
test result, and the commit hash.
