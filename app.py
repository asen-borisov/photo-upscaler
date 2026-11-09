"""Photo Upscaler: starts the local engine server and opens the app window."""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

LOG = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PhotoUpscaler" / "app.log"
if sys.stdout is None or sys.stderr is None:  # windowed .exe has no console: log to a file instead
    LOG.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)

import uvicorn  # noqa: E402  (must come after the stdout fix)

from photo_upscaler import pipeline
from photo_upscaler.server import app, queue

IMAGE_TYPES = ("Photos (" + ";".join(f"*{e}" for e in sorted(pipeline.SUPPORTED)) + ")", "All files (*.*)")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server


class Bridge:
    """Functions the web page can call (native file dialogs)."""

    def __init__(self):
        self._window = None

    def _dialog(self, kind, **kw):
        import webview
        fd = getattr(webview, "FileDialog", None)
        dtype = getattr(fd, kind) if fd else getattr(webview, f"{kind}_DIALOG")
        res = self._window.create_file_dialog(dtype, **kw)
        return list(res) if res else []

    def pick_files(self):
        return self._dialog("OPEN", allow_multiple=True, file_types=IMAGE_TYPES)

    def pick_folder(self):
        return self._dialog("FOLDER")

    def pick_output(self):
        r = self._dialog("FOLDER")
        return r[0] if r else ""


def on_loaded(window):
    from webview.dom import DOMEventHandler

    def on_drop(e):
        files = (e.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            threading.Thread(target=queue.add_paths, args=(paths,), daemon=True).start()

    window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)


def main():
    port = free_port()
    serve(port)
    url = f"http://127.0.0.1:{port}/"
    if "--browser" in sys.argv:
        webbrowser.open(url)
        print(f"Photo Upscaler running at {url} (Ctrl+C to stop)")
        threading.Event().wait()
    try:
        import webview
    except ImportError:
        webbrowser.open(url)
        threading.Event().wait()
    bridge = Bridge()
    window = webview.create_window("Photo Upscaler", url, js_api=bridge, width=1360, height=820, maximized=True,
                                   min_size=(1100, 680), background_color="#161616")
    bridge._window = window
    webview.start(on_loaded, window)
    queue.stop()  # window closed: stop any running job


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"Photo Upscaler could not start.\n\n{traceback.format_exc()[-800:]}"
                                             f"\n\nDetails: {LOG}", "Photo Upscaler", 0x10)
        raise
