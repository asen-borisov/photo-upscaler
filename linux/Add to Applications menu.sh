#!/usr/bin/env bash
# Adds "Photo Upscaler" to the Linux applications menu (run once; run again if you move the folder).
set -e
here="$(cd "$(dirname "$0")" && pwd)"
chmod +x "$here/PhotoUpscaler" "$here/engine/upscayl-bin"
apps="$HOME/.local/share/applications"
mkdir -p "$apps"
cat > "$apps/photo-upscaler.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Photo Upscaler
Comment=Make photos bigger and sharper with AI, on this computer
Exec="$here/PhotoUpscaler"
Icon=$here/icon.png
Terminal=false
Categories=Graphics;Photography;
EOF
chmod +x "$apps/photo-upscaler.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$apps" || true
if command -v zenity >/dev/null; then
  zenity --info --title="Photo Upscaler" --text="Done! Photo Upscaler is now in your applications menu." || true
else
  echo "Done! Photo Upscaler is now in your applications menu."
fi
