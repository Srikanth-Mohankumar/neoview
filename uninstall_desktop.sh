#!/usr/bin/env bash
set -euo pipefail

app_name="neoview"
desktop_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop_path="${desktop_dir}/${app_name}.desktop"
icon_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
icon_path="${icon_dir}/neoview.png"

rm -f "$desktop_path" "$icon_path"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
fi

echo "Removed desktop entry: ${desktop_path}"
