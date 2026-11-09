#!/usr/bin/env bash
# One-time setup when running from source on Linux: Python environment + engine + AI models.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/setup_engine.py
echo
echo "Setup finished. Run ./start.sh to open the app."
