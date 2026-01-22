# Contributing

Thanks for your interest in improving NeoView.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .[dev]
```

## Quality checks

```bash
ruff check .
pytest
```

## Pull requests

- Keep changes focused and well-described.
- Add tests for new behavior where practical.
- Avoid large refactors without discussion.
