#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_dir"

if [[ ! -f "$HOME/.pypirc" ]]; then
  echo "Error: ~/.pypirc not found. Create it with your PyPI token." >&2
  exit 1
fi

python3 -m pip install --upgrade build twine >/dev/null

rm -rf dist build src/*.egg-info

python3 -m build
python3 -m twine check dist/*
python3 -m twine upload dist/*

echo "Publish complete."
