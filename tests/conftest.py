import hashlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from photo_upscaler import engine

FAST_MODEL = "4xLSDIRCompactC3"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def photo(w=120, h=80, mode="RGB", seed=0) -> Image.Image:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.stack([xx * 255 / w, yy * 255 / h, (xx + yy) * 127 / (w + h)], -1)
    arr = np.clip(base + rng.normal(0, 12, base.shape), 0, 255).astype(np.uint8)
    im = Image.fromarray(arr, "RGB")
    return im.convert(mode) if mode != "RGB" else im


@pytest.fixture
def fake_engine(monkeypatch):
    """Replace the GPU engine with a plain Lanczos 4x so pipeline tests run in milliseconds."""
    calls = []

    def run(src, dst, model, on_progress=None, cancel=None, **kw):
        calls.append(model.id)
        im = Image.open(src)
        im.resize((im.width * model.scale, im.height * model.scale), Image.LANCZOS).save(dst)
        if on_progress:
            on_progress(1.0)

    fake = engine.Model(FAST_MODEL, "Fast", "test", 4, "fast", "CC-BY-4.0")
    monkeypatch.setattr(engine, "run", run)
    monkeypatch.setattr(engine, "get_model", lambda mid: fake)
    return calls


needs_engine = pytest.mark.skipif(
    not engine.EXE.exists() or not (engine.MODELS_DIR / f"{FAST_MODEL}.param").exists(),
    reason="engine not installed (run scripts/setup_engine.py)")
