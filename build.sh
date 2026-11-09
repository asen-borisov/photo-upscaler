#!/usr/bin/env bash
# Builds the standalone Linux app folder + .tar.gz (no Python needed on the computer that runs it).
# Build on the OLDEST Linux version you want to support (Ubuntu 22.04, see linux/Dockerfile).
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || python3 -m venv .venv
"$PY" -m pip install -q -r requirements-dev.txt
"$PY" scripts/setup_engine.py
"$PY" -m pytest -q

"$PY" -m PyInstaller --noconfirm --clean --windowed --name PhotoUpscaler \
    --add-data "photo_upscaler/web:photo_upscaler/web" \
    --add-data "photo_upscaler/models.json:photo_upscaler" \
    --collect-all webview --collect-submodules uvicorn app.py

out="dist/Photo Upscaler"
rm -rf "$out"
mv dist/PhotoUpscaler "$out"
cp -r engine "$out/engine"
cp "linux/READ ME FIRST.txt" "linux/Add to Applications menu.sh" LICENSES.md assets/icon.png "$out/"
chmod +x "$out/PhotoUpscaler" "$out/engine/upscayl-bin" "$out/Add to Applications menu.sh"
# Leave out libraries that must come from the user's own system (graphics driver, fonts, sound,
# security, C++ runtime), as AppImage does: every desktop Linux has them, and the build machine's
# copies can clash with a newer graphics driver (e.g. libgbm pulls in Wayland libraries).
for lib in libgbm.so.1 libX11.so.6 libX11-xcb.so.1 libxcb.so.1 libxcb-glx.so.0 libxcb-render.so.0 \
           libxcb-shm.so.0 libxcb-sync.so.1 libxcb-xfixes.so.0 libxcb-xkb.so.1 libxcb-randr.so.0 \
           libxcb-shape.so.0 libfontconfig.so.1 libfreetype.so.6 libnss3.so libnssutil3.so \
           libasound.so.2 libdbus-1.so.3 libexpat.so.1 libz.so.1 libuuid.so.1 libstdc++.so.6 libgcc_s.so.1; do
    rm -f "$out/_internal/$lib"
done
version=$("$PY" -c "import photo_upscaler; print(photo_upscaler.__version__)")
tar -C dist -czf "dist/PhotoUpscaler-$version-linux.tar.gz" "Photo Upscaler"   # tar keeps the "can run" flags
echo "Built dist/PhotoUpscaler-$version-linux.tar.gz"
