---
name: release
description: Cut a NeoView release end to end - version bump in pyproject.toml, quality gate, smoke test, tag, PyPI upload, and verifying the GitHub release with the Windows exe. Run only when the user asks to release, publish, ship or tag a new version.
disable-model-invocation: true
argument-hint: "[version, e.g. 0.5]"
---

# Release NeoView

Releasing is mostly irreversible: PyPI never accepts the same version twice, and a pushed tag
triggers the Windows build and creates the public GitHub release. So the gate runs before
anything leaves the machine, and each outward step waits for the user's go-ahead.

`RELEASE_CHECKLIST.md` is the human version of this procedure. If it and this skill disagree,
say so rather than silently picking one.

## 1. Preflight

1. Version: use `$ARGUMENTS` if given, else ask. Match the existing scheme - tags so far are
   `v0.2`, `v0.3`, `v0.4` (two-part); confirm with the user before switching to `X.Y.Z`.
   Check it is unused: `git tag -l v<version>` and `pip index versions neoview`.
2. `git status` clean, on `main`, and `git fetch && git status -sb` shows not behind `origin/main`.
3. CI is green on HEAD: `gh run list --branch main --limit 3`. A red or running CI is a stop.

## 2. Quality gate (all local, nothing published yet)

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
rm -rf dist && .venv/bin/python -m build --sdist --wheel
.venv/bin/python -m pip install -q twine && .venv/bin/python -m twine check dist/*
```

`twine` is not in the `dev` extras, hence the install. Then run the `smoke-test-ui` skill and
look at the screenshots - the test suite does not render the real window.

Any failure stops the release; report it with the output.

## 3. Bump, commit, tag - confirm first

Show the user the diff of `pyproject.toml` (`version = "<version>"`, the only place it lives)
and the commit/tag you are about to push, then on their go-ahead:

```bash
git commit -am "release: v<version>"
git push origin main
git tag -a v<version> -m "NeoView v<version>"
git push origin v<version>
```

Pushing the tag starts `.github/workflows/windows-build.yml`, which builds `neoview.exe` and
**creates the GitHub release itself** (softprops/action-gh-release). Do not also run
`gh release create`: that is how a duplicate "NeoView v0.4" draft release appeared.

## 4. PyPI - confirm first

Rebuild from the tagged commit so the artifacts match the version, then upload. This needs
`~/.pypirc`; never print or copy its contents.

```bash
./publish.sh
```

It cleans `dist/`, builds with the repo `.venv`, runs `twine check`, and uploads everything in
`dist/` without pausing. So before running it, confirm `git describe --tags` is `v<version>`
and `pyproject.toml` says `version = "<version>"`.

## 5. Verify

- `gh run watch` the Windows Build run for the tag; then `gh release view v<version>` lists
  `neoview.exe`. Add release notes with `gh release edit v<version> --notes-file <file>`
  (features, fixes, known limitations - draft them from `git log v<previous>..v<version>`).
- Fresh install in a throwaway venv (scratchpad, not the repo):
  `python -m pip install neoview==<version>` then
  `python -c "import importlib.metadata as m; print(m.version('neoview'))"`.
  Do not run `neoview --help`: the app has no argument parser and treats it as a file path.

## If something fails midway

- Upload failed and nothing reached PyPI: fix the cause and republish the same version.
- Anything reached PyPI and the release is bad: never delete/reuse the version; bump and ship
  a patch release.
- Report exactly which steps completed (pushed? tagged? uploaded?) so the user knows the state.
