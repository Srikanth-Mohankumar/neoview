# Release Checklist

## Before first public release
- Set repository URLs in `pyproject.toml` under `[project.urls]` (Repository, Issues, Homepage).
- Confirm project name availability on PyPI (currently `neoview`).
- Verify the license holder name in `LICENSE`.
- Ensure the README title/description matches the public repo name.
- Run the test suite: `pytest`.

## Build + upload to PyPI
```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

## Tag release
```bash
git tag -a v0.1.0 -m "NeoView v0.1.0"
git push --tags
```
