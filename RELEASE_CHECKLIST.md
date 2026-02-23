# Release Checklist

Use this checklist for every public release.

## 1. Preflight
- Confirm working tree is clean: `git status`
- Choose next version (PyPI does not allow re-uploading an existing version)
- Update version in `pyproject.toml`
- Review user-facing changes and docs (`README.md`, release notes)

## 2. Quality Gate
- Run lint: `.venv/bin/ruff check .`
- Run tests: `.venv/bin/python -m pytest`
- Build distributions: `.venv/bin/python -m build --sdist --wheel`
- Verify metadata: `.venv/bin/python -m twine check dist/*`

## 3. Commit + Tag
```bash
git add -A
git commit -m "release: vX.Y.Z"
git push origin main

git tag -a vX.Y.Z -m "NeoView vX.Y.Z"
git push origin vX.Y.Z
```

## 4. Publish to PyPI
Requires valid credentials in `~/.pypirc`.

```bash
.venv/bin/python -m twine upload dist/neoview-X.Y.Z.tar.gz dist/neoview-X.Y.Z-py3-none-any.whl
```

## 5. GitHub Release
- Create GitHub release for `vX.Y.Z`
- Add release notes (features, fixes, known limitations)
- Verify Windows build workflow attached `dist/neoview.exe` to the release tag

## 6. Post-release Verification
- Confirm package is visible on PyPI
- Fresh install check:
  - `python -m pip install -U neoview`
  - `neoview --help` (or launch app)
- Smoke test open PDF, zoom, search, hyperlinks, measure, export, auto-reload

## 7. Roll-forward Notes
- If publish fails after tag push, fix credentials/issues and republish same tag/version only if upload did not succeed
- If upload succeeded but release is bad, bump version and publish a follow-up patch release
