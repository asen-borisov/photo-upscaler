"""Thin wrapper around the bundled upscayl-bin (Real-ESRGAN ncnn-vulkan) engine.

The engine runs on any GPU through Vulkan (AMD, NVIDIA, Intel). It only ever runs a
model at its *native* scale: asking these engines for a scale with no matching model
silently drops slices of the picture, so any other size is done afterwards in Python.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path


def app_root() -> Path:
    """Folder that holds engine/ (works from source and from a PyInstaller build)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


ENGINE_DIR = app_root() / "engine"
EXE = ENGINE_DIR / ("upscayl-bin.exe" if os.name == "nt" else "upscayl-bin")
MODELS_DIR = ENGINE_DIR / "models"
CATALOG = Path(__file__).with_name("models.json")


class EngineError(RuntimeError):
    pass


class Cancelled(Exception):
    pass


@dataclass
class Model:
    id: str           # file stem, e.g. "4xNomos8kSC"
    label: str
    description: str
    scale: int        # native scale of the model file
    speed: str
    license: str


def native_scale(model_id: str) -> int:
    """Scale baked into a model file, read from its name ('-x2', '4x', '_x4'...)."""
    m = re.search(r"(?:^|[-_])x(\d)(?:$|[-_])", model_id) or re.search(r"(?:^|[-_])(\d)x(?:$|[-_])", model_id) \
        or re.match(r"(\d)x", model_id)
    return int(m.group(1)) if m else 4


def available_models() -> list[Model]:
    """Catalogue models whose .param and .bin files are actually on disk."""
    out = []
    for e in json.loads(CATALOG.read_text(encoding="utf-8")):
        if (MODELS_DIR / f"{e['id']}.param").exists() and (MODELS_DIR / f"{e['id']}.bin").exists():
            out.append(Model(scale=native_scale(e["id"]), **e))
    return out


def get_model(model_id: str) -> Model:
    for m in available_models():
        if m.id == model_id:
            return m
    raise EngineError(f"Model '{model_id}' is not installed (looked in {MODELS_DIR}).")


_PCT = re.compile(r"(\d+(?:\.\d+)?)%")


def run(src: Path, dst: Path, model: Model, on_progress=None, cancel: threading.Event | None = None,
        tile: int = 0, gpu: str = "auto") -> None:
    """Upscale PNG `src` to PNG `dst` with `model` at its native scale. Blocks until done."""
    if not EXE.exists():
        raise EngineError(f"Upscaling engine not found at {EXE}. Run scripts/setup_engine.py first.")
    cmd = [str(EXE), "-i", str(src), "-o", str(dst), "-m", str(MODELS_DIR), "-n", model.id,
           "-z", str(model.scale), "-s", str(model.scale), "-f", "png", "-t", str(tile)]
    if gpu != "auto":
        cmd += ["-g", gpu]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
    tail: list[str] = []

    def reader():
        buf = b""
        while True:
            ch = proc.stderr.read(1)
            if not ch:
                break
            if ch in b"\r\n":
                line = buf.decode("utf-8", "replace").strip()
                buf = b""
                m = _PCT.fullmatch(line)
                if m:
                    if on_progress:
                        on_progress(min(float(m.group(1)), 100.0) / 100.0)
                elif line:
                    tail.append(line)
                    del tail[:-20]
            else:
                buf += ch

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    while True:
        try:
            proc.wait(timeout=0.2)
            break
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled() from None
    t.join(timeout=2)
    if proc.returncode != 0 or not dst.exists():
        detail = [l for l in tail if not l.startswith("[")][-3:]  # skip GPU info lines
        msg = "; ".join(detail) or f"it stopped unexpectedly (exit code {proc.returncode})"
        raise EngineError(f"The upscaling engine failed: {msg}")
