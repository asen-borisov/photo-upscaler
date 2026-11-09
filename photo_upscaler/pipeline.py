"""Photo pipeline around the AI engine.

open (any format) -> straighten EXIF rotation -> 8-bit RGB(A) temp PNG -> AI x4 ->
resize to the exact target with Lanczos -> optional blend with a plain resize
("AI strength") -> save with the original colour profile, EXIF, XMP and DPI.

The original file is never touched: output always goes to a new, unique file.
"""
from __future__ import annotations

import io
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps, PngImagePlugin

from . import engine

try:  # iPhone photos
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:  # pragma: no cover
    pass

Image.MAX_IMAGE_PIXELS = None  # big photos are the whole point

SUPPORTED = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif", ".bmp"}
APP_TAG = "Photo Upscaler"
SUFFIX = "_upscaled"
MAX_FACTOR = 4.0
FORMATS = {"jpeg": ".jpg", "tiff": ".tif", "png": ".png", "webp": ".webp"}
MAX_SIDE = {".jpg": 65500, ".webp": 16383}
SAME = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".tif": "tiff", ".tiff": "tiff", ".webp": "webp",
        ".heic": "jpeg", ".heif": "jpeg", ".bmp": "png"}

# EXIF tags
ORIENTATION, SOFTWARE, EXIF_IFD, EXIF_W, EXIF_H = 0x0112, 0x0131, 0x8769, 0xA002, 0xA003
TIFF_LAYOUT_TAGS = (254, 255, 256, 257, 258, 259, 262, 263, 266, 273, 277, 278, 279, 280, 281, 284, 317, 320,
                    322, 323, 324, 325, 330, 338, 339, 340, 341, 347, 532, 700, 34377, 34675, 37724)


class Skipped(Exception):
    pass


@dataclass
class Settings:
    model: str
    mode: str = "scale"             # "scale" or "long_edge"
    scale: float = 2.0
    long_edge: int = 0
    strength: float = 1.0           # 1 = full AI, 0 = plain Lanczos resize
    fmt: str = "same"               # same | jpeg | tiff | png | webp
    jpeg_quality: int = 95
    out_dir: str = ""               # "" -> "<input folder>/Upscaled"
    dpi: int = 0                    # 0 -> keep the original DPI
    skip_if_big: bool = True


@dataclass
class Result:
    out_path: Path
    in_size: tuple[int, int]
    out_size: tuple[int, int]
    seconds: float
    notes: list[str] = field(default_factory=list)


def is_supported(p: Path) -> bool:
    return p.suffix.lower() in SUPPORTED and not p.name.startswith(".")


def target_size(w: int, h: int, s: Settings) -> tuple[int, int, float]:
    """Exact output size and the factor it represents."""
    if s.mode == "long_edge":
        if s.long_edge <= 0:
            raise ValueError("Set a target long edge in pixels.")
        f = s.long_edge / max(w, h)
    else:
        f = float(s.scale)
    if f <= 0:
        raise ValueError("Scale must be positive.")
    return max(1, round(w * f)), max(1, round(h * f)), f


def output_path(src: Path, s: Settings, factor: float) -> Path:
    fmt = SAME.get(src.suffix.lower(), "jpeg") if s.fmt == "same" else s.fmt
    folder = Path(s.out_dir) if s.out_dir else src.parent / "Upscaled"
    tag = f"{factor:g}x" if s.mode == "scale" else f"{s.long_edge}px"
    base = folder / f"{src.stem}{SUFFIX}_{tag}{FORMATS[fmt]}"
    p, n = base, 2
    while p.exists() or p.resolve() == src.resolve():
        p = base.with_name(f"{base.stem} ({n}){base.suffix}")
        n += 1
    return p


def _to_8bit(im: Image.Image) -> Image.Image:
    if im.mode in ("I;16", "I;16B", "I;16L", "I"):
        a = np.asarray(im, dtype=np.uint32)
        return Image.fromarray((a >> 8 if a.max() > 255 else a).astype(np.uint8), "L")
    if im.mode == "F":
        return Image.fromarray(np.clip(np.asarray(im), 0, 255).astype(np.uint8), "L")
    return im


def load(src: Path):
    """Open a photo upright, as 8-bit RGB/RGBA/L, plus its metadata."""
    im = Image.open(src)
    meta = {
        "icc": im.info.get("icc_profile"),
        "xmp": im.info.get("xmp") or im.info.get("XML:com.adobe.xmp"),
        "dpi": im.info.get("dpi"),
        "exif": im.getexif(),
    }
    for tag in TIFF_LAYOUT_TAGS:  # a TIFF's own layout tags must not leak into the new file
        meta["exif"].pop(tag, None)
    notes = []
    if src.suffix.lower() in (".tif", ".tiff") and im.mode in ("RGB", "RGBA") and \
            getattr(im, "tag_v2", {}).get(258, (8,))[0] == 16:
        notes.append("16-bit TIFF processed at 8 bits")
    im = ImageOps.exif_transpose(im) or im
    im = _to_8bit(im)
    if im.mode == "CMYK":
        src_prof = ImageCms.ImageCmsProfile(io.BytesIO(meta["icc"])) if meta["icc"] else None
        srgb = ImageCms.createProfile("sRGB")
        im = ImageCms.profileToProfile(im, src_prof, srgb, outputMode="RGB") if src_prof else im.convert("RGB")
        meta["icc"] = ImageCms.ImageCmsProfile(srgb).tobytes()
        notes.append("CMYK converted to sRGB")
    if im.mode in ("P", "PA"):
        im = im.convert("RGBA" if "transparency" in im.info or im.mode == "PA" else "RGB")
    if im.mode == "LA":
        im = im.convert("RGBA")
    if im.mode not in ("RGB", "RGBA", "L"):
        im = im.convert("RGB")
    return im, meta, notes


def already_upscaled(src: Path) -> bool:
    if SUFFIX in src.stem:
        return True
    try:
        return APP_TAG in str(Image.open(src).getexif().get(SOFTWARE, ""))
    except Exception:
        return False


def _exif_bytes(exif: Image.Exif, size: tuple[int, int], model: str) -> bytes:
    exif[ORIENTATION] = 1
    sw = str(exif.get(SOFTWARE, "")).strip()
    exif[SOFTWARE] = f"{sw}; {APP_TAG} ({model})" if sw and APP_TAG not in sw else f"{APP_TAG} ({model})"
    ifd = exif.get_ifd(EXIF_IFD)
    if ifd:
        ifd[EXIF_W], ifd[EXIF_H] = size
    return exif.tobytes()


def save(im: Image.Image, dst: Path, meta: dict, s: Settings, model: str) -> None:
    fmt = {".jpg": "JPEG", ".tif": "TIFF", ".png": "PNG", ".webp": "WEBP"}[dst.suffix]
    kw: dict = {}
    if meta["icc"]:
        kw["icc_profile"] = meta["icc"]
    dpi = (s.dpi, s.dpi) if s.dpi else meta["dpi"]
    if dpi:
        kw["dpi"] = tuple(round(float(d)) for d in dpi)
    exif = _exif_bytes(meta["exif"], im.size, model)
    xmp = meta["xmp"]
    if isinstance(xmp, str):
        xmp = xmp.encode("utf-8")
    if fmt == "JPEG":
        if im.mode == "RGBA":
            im = _flatten(im)
        kw.update(quality=s.jpeg_quality, subsampling=0, exif=exif)
        if xmp:
            kw["xmp"] = xmp
    elif fmt == "TIFF":
        # Uncompressed on purpose: libtiff's LZW writer drops the camera EXIF block.
        if xmp:
            meta["exif"][700] = xmp
        kw["exif"] = _exif_bytes(meta["exif"], im.size, model)
    elif fmt == "PNG":
        kw.update(exif=exif, compress_level=6)
        info = PngImagePlugin.PngInfo()
        info.add_text("Software", APP_TAG)
        if xmp:
            info.add_itxt("XML:com.adobe.xmp", xmp.decode("utf-8", "replace"))
        kw["pnginfo"] = info
    elif fmt == "WEBP":
        kw.update(quality=s.jpeg_quality, exif=exif, method=4)
        if xmp:
            kw["xmp"] = xmp
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    try:
        im.save(tmp, fmt, **kw)
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def _flatten(im: Image.Image) -> Image.Image:
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.getchannel("A"))
    return bg


def process(src: Path, s: Settings, on_progress=None, cancel: threading.Event | None = None,
            workdir: Path | None = None) -> Result:
    """Upscale one photo. Raises Skipped, engine.Cancelled or engine.EngineError."""
    t0 = time.time()
    report = on_progress or (lambda f: None)
    model = engine.get_model(s.model)
    if already_upscaled(src):
        raise Skipped("already upscaled by this app")
    im, meta, notes = load(src)
    w, h = im.size
    tw, th, factor = target_size(w, h, s)
    if factor <= 1.0:
        if s.skip_if_big:
            raise Skipped(f"already {w}x{h}, no bigger than the target")
    if factor > MAX_FACTOR + 1e-6:
        raise ValueError(f"{factor:.1f}x is more than the {MAX_FACTOR:g}x maximum for {w}x{h}.")
    dst = output_path(src, s, factor)
    limit = MAX_SIDE.get(dst.suffix)
    if limit and max(tw, th) > limit:
        raise ValueError(f"{tw}x{th} is too big for {dst.suffix[1:].upper()} (max {limit} px per side). "
                         "Choose TIFF or PNG, or a smaller size.")
    report(0.03)

    with tempfile.TemporaryDirectory(dir=workdir, prefix="ups_") as td:
        tin, tout = Path(td) / "in.png", Path(td) / "out.png"
        (im.convert("RGB") if im.mode == "L" else im).save(tin, compress_level=1)
        engine.run(tin, tout, model, on_progress=lambda f: report(0.05 + 0.8 * f), cancel=cancel)
        ai = Image.open(tout)
        ai.load()
    if ai.size != (w * model.scale, h * model.scale):
        raise engine.EngineError(f"Engine returned {ai.size[0]}x{ai.size[1]}, expected "
                                 f"{w * model.scale}x{h * model.scale}. Output discarded to protect the photo.")
    if im.mode == "RGBA" and ai.mode != "RGBA":  # keep transparency if the engine dropped it
        ai.putalpha(im.getchannel("A").resize(ai.size, Image.LANCZOS))
    report(0.88)
    if cancel is not None and cancel.is_set():
        raise engine.Cancelled()

    out = ai if ai.size == (tw, th) else ai.resize((tw, th), Image.LANCZOS)
    del ai
    if s.strength < 0.999:
        base = im.convert(out.mode) if im.mode != out.mode else im
        out = Image.blend(base.resize((tw, th), Image.LANCZOS), out, max(0.0, s.strength))
    if im.mode == "L":
        out = out.convert("L")
    report(0.93)
    save(out, dst, meta, s, model.id)
    report(1.0)
    return Result(dst, (w, h), (tw, th), time.time() - t0, notes)
