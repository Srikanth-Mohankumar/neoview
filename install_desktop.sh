#!/usr/bin/env bash
set -euo pipefail

app_name="neoview"
desktop_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop_path="${desktop_dir}/${app_name}.desktop"
icon_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
icon_path="${icon_dir}/neoview.png"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p "$desktop_dir"
mkdir -p "$icon_dir"

if [[ -f "${script_dir}/src/neoview/assets/feather-logo.png" ]]; then
  cp "${script_dir}/src/neoview/assets/feather-logo.png" "$icon_path"
elif [[ -f "${script_dir}/feather-logo.png" ]]; then
  cp "${script_dir}/feather-logo.png" "$icon_path"
fi

cat > "$desktop_path" <<'EOF'
[Desktop Entry]
Type=Application
Name=NeoView
Comment=Measure and export regions from PDFs
Exec=neoview %f
Icon=neoview
Terminal=false
Categories=Office;Graphics;
MimeType=application/pdf;
EOF

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
fi

echo "Installed desktop entry at: ${desktop_path}"
