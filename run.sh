#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_dir="$repo_dir/.venv"

if [[ ! -d "$venv_dir" ]]; then
  echo "Creating venv at $venv_dir"
  python3 -m venv "$venv_dir"
fi

# shellcheck disable=SC1091
source "$venv_dir/bin/activate"

python -m pip install -e "$repo_dir" >/dev/null

exec neoview "$@"
