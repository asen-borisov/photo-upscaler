"""Local web API + UI. Only listens on 127.0.0.1 (this computer)."""
from __future__ import annotations

import io
import os
import subprocess
import tempfile
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel

from . import engine, pipeline
from .jobs import Queue

WEB = Path(__file__).with_name("web")
WORKDIR = Path(tempfile.gettempdir()) / "photo-upscaler"
WORKDIR.mkdir(exist_ok=True)

app = FastAPI(title="Photo Upscaler")
queue = Queue(WORKDIR)


class Paths(BaseModel):
    paths: list[str]


class StartBody(BaseModel):
    model: str
    mode: str = "scale"
    scale: float = 2.0
    long_edge: int = 0
    strength: float = 1.0
    fmt: str = "same"
    jpeg_quality: int = 95
    out_dir: str = ""
    dpi: int = 0
    skip_if_big: bool = True


@app.get("/api/models")
def models():
    return [asdict(m) for m in engine.available_models()]


@app.post("/api/add")
def add(body: Paths):
    return {"added": queue.add_paths(body.paths)}


@app.get("/api/queue")
def status():
    return queue.snapshot()


@app.post("/api/start")
def start(body: StartBody):
    try:
        queue.start(pipeline.Settings(**body.model_dump()))
    except (engine.EngineError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/cancel")
def cancel():
    queue.stop()
    return {"ok": True}


@app.post("/api/remove/{job_id}")
def remove(job_id: int):
    queue.remove(job_id)
    return {"ok": True}


@app.post("/api/clear")
def clear():
    queue.clear_finished()
    return {"ok": True}


def _job(job_id: int):
    j = queue.get(job_id)
    if j is None:
        raise HTTPException(404, "No such item")
    return j


@lru_cache(maxsize=2)
def _open(path: str, mtime: float) -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im) or im
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    im.load()
    return im


def _image(job, which: str) -> Image.Image:
    p = job.out_path if which == "after" else job.path
    if not p or not os.path.exists(p):
        raise HTTPException(404, "Not ready")
    return _open(p, os.path.getmtime(p))


def _jpeg(im: Image.Image, q=90) -> Response:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=q)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/thumb/{job_id}")
def thumb(job_id: int):
    j = _job(job_id)
    with Image.open(j.path) as im:
        im.draft("RGB", (160, 160))
        im = ImageOps.exif_transpose(im) or im
        im.thumbnail((96, 96))
        return _jpeg(im, 80)


@app.get("/api/preview/{job_id}")
def preview(job_id: int, which: str = "after", w: int = 1600, h: int = 1200):
    """Whole-photo view; 'before' is stretched to the same frame so the slider lines up."""
    j = _job(job_id)
    after = _image(j, "after")
    s = min(w / after.width, h / after.height, 1.0)
    size = (max(1, round(after.width * s)), max(1, round(after.height * s)))
    src = after if which == "after" else _image(j, "before")
    return _jpeg(src.resize(size, Image.LANCZOS, reducing_gap=3.0))


@app.get("/api/crop/{job_id}")
def crop(job_id: int, which: str, x: int, y: int, w: int, h: int, zoom: float = 1.0):
    """A region at 100% (or `zoom`) of the OUTPUT, for pixel-peeping.
    For 'before' the same region of the original is enlarged with bicubic,
    which is what you would get without AI."""
    j = _job(job_id)
    after = _image(j, "after")
    w, h = max(1, min(w, 4000)), max(1, min(h, 4000))
    x, y = max(0, min(x, after.width - 1)), max(0, min(y, after.height - 1))
    region = (x, y, min(after.width, x + w), min(after.height, y + h))
    if which == "after":
        im = after.crop(region)
    else:
        src = _image(j, "before")
        sx, sy = src.width / after.width, src.height / after.height
        im = src.resize((region[2] - region[0], region[3] - region[1]), Image.BICUBIC,
                        box=(region[0] * sx, region[1] * sy, region[2] * sx, region[3] * sy))
    if zoom != 1.0:
        im = im.resize((round(im.width * zoom), round(im.height * zoom)), Image.NEAREST)
    return _jpeg(im, 95)


@app.post("/api/reveal/{job_id}")
def reveal(job_id: int):
    j = _job(job_id)
    if j.out_path and os.path.exists(j.out_path) and os.name == "nt":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(j.out_path)])
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory=WEB), name="static")
