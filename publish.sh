#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo_dir"

if [[ ! -f "$HOME/.pypirc" ]]; then
  echo "Error: ~/.pypirc not found. Create it with your PyPI token." >&2
  exit 1
fi

# Use the repo venv: pip-installing into the system python3 is blocked by PEP 668
# ("externally-managed-environment") on current Debian/Ubuntu.
venv_dir="$repo_dir/.venv"
if [[ ! -d "$venv_dir" ]]; then
  echo "Creating venv at $venv_dir"
  python3 -m venv "$venv_dir"
fi
py="$venv_dir/bin/python"

"$py" -m pip install --upgrade build twine >/dev/null

rm -rf dist build src/*.egg-info

"$py" -m build
"$py" -m twine check dist/*
"$py" -m twine upload dist/*

echo "Publish complete."
