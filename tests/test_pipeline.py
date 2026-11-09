import io
import threading

import numpy as np
import pytest
from PIL import Image, ImageCms

from photo_upscaler import engine, pipeline
from photo_upscaler.pipeline import Settings
from conftest import FAST_MODEL, needs_engine, photo, sha

ADOBE_LIKE_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()  # any non-sRGB profile
XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">' \
      b'<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:rights>(c) Test Studio</dc:rights>' \
      b'</rdf:Description></rdf:RDF></x:xmpmeta>'


@pytest.mark.parametrize("name,scale", [
    ("realesrgan-x4plus", 4), ("realesr-animevideov3-x2", 2), ("realesr-animevideov3-x3", 3),
    ("4xNomos8kSC", 4), ("4x_NMKD-Siax_200k", 4), ("RealESRGAN_General_x4_v3", 4), ("2x_Something", 2),
])
def test_native_scale_read_from_file_name(name, scale):
    assert engine.native_scale(name) == scale


def test_target_size_modes():
    assert pipeline.target_size(4000, 3000, Settings("m", scale=2))[:2] == (8000, 6000)
    assert pipeline.target_size(4000, 3000, Settings("m", scale=1.5))[:2] == (6000, 4500)
    assert pipeline.target_size(3000, 4000, Settings("m", mode="long_edge", long_edge=6000))[:2] == (4500, 6000)


def test_output_path_never_overwrites(tmp_path):
    src = tmp_path / "a.jpg"
    photo().save(src)
    s = Settings("m", scale=2)
    p1 = pipeline.output_path(src, s, 2)
    assert p1 == tmp_path / "Upscaled" / "a_upscaled_2x.jpg"
    p1.parent.mkdir()
    p1.write_bytes(b"x")
    p2 = pipeline.output_path(src, s, 2)
    assert p2.name == "a_upscaled_2x (2).jpg"
    # an output folder equal to the input folder still never hits the original
    s2 = Settings("m", scale=2, out_dir=str(tmp_path))
    assert pipeline.output_path(src, s2, 2) != src


def test_jpeg_keeps_metadata_and_rotation(tmp_path, fake_engine):
    src = tmp_path / "IMG_0001.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6                       # rotated 90° (portrait shot)
    exif[0x013B] = "Jane Photographer"     # Artist
    exif[0x8298] = "(c) Jane"              # Copyright
    exif[0x0110] = "Canon EOS R5"          # Model
    photo(120, 80).save(src, quality=95, exif=exif, icc_profile=ADOBE_LIKE_ICC, dpi=(240, 240), xmp=XMP)
    before = sha(src)

    r = pipeline.process(src, Settings(FAST_MODEL, scale=2))

    assert sha(src) == before, "original must never change"
    assert r.in_size == (80, 120) and r.out_size == (160, 240)
    out = Image.open(r.out_path)
    assert out.size == (160, 240) and out.format == "JPEG"
    assert out.info["icc_profile"] == ADOBE_LIKE_ICC
    assert out.info["dpi"] == (240, 240)
    assert b"Test Studio" in out.info["xmp"]
    ex = out.getexif()
    assert ex[0x0112] == 1
    assert ex[0x013B] == "Jane Photographer" and ex[0x8298] == "(c) Jane" and ex[0x0110] == "Canon EOS R5"
    assert pipeline.APP_TAG in ex[0x0131]


def test_long_edge_print_size_sets_dpi(tmp_path, fake_engine):
    src = tmp_path / "a.png"
    photo(100, 50).save(src)
    r = pipeline.process(src, Settings(FAST_MODEL, mode="long_edge", long_edge=354, dpi=300, fmt="tiff"))
    out = Image.open(r.out_path)
    assert out.size == (354, 177) and out.format == "TIFF"
    assert tuple(round(d) for d in out.info["dpi"]) == (300, 300)


def test_skips(tmp_path, fake_engine):
    big = tmp_path / "big.jpg"
    photo(400, 300).save(big)
    with pytest.raises(pipeline.Skipped):
        pipeline.process(big, Settings(FAST_MODEL, mode="long_edge", long_edge=300))
    done = tmp_path / "x_upscaled_2x.jpg"
    photo().save(done)
    with pytest.raises(pipeline.Skipped):
        pipeline.process(done, Settings(FAST_MODEL))
    with pytest.raises(ValueError):
        pipeline.process(big, Settings(FAST_MODEL, mode="long_edge", long_edge=2000))  # 5x > 4x max
    assert fake_engine == []


def test_format_size_limit_checked_before_engine_runs(tmp_path, fake_engine):
    src = tmp_path / "web.webp"
    photo(5000, 40).save(src)
    with pytest.raises(ValueError, match="too big for WEBP"):
        pipeline.process(src, Settings(FAST_MODEL, scale=4))
    assert fake_engine == []


def test_bad_engine_output_is_rejected(tmp_path, monkeypatch, fake_engine):
    def short_run(src, dst, model, **kw):  # simulates the "missing slices" engine bug
        im = Image.open(src)
        im.resize((im.width * 3, im.height * 4)).save(dst)

    monkeypatch.setattr(engine, "run", short_run)
    src = tmp_path / "a.jpg"
    photo().save(src)
    with pytest.raises(engine.EngineError):
        pipeline.process(src, Settings(FAST_MODEL))
    assert not (tmp_path / "Upscaled").exists() or not any((tmp_path / "Upscaled").iterdir())


def test_alpha_gray_16bit_cmyk(tmp_path, fake_engine):
    rgba = photo(60, 40).convert("RGBA")
    a = np.full((40, 60), 255, np.uint8); a[:, :20] = 0
    rgba.putalpha(Image.fromarray(a))
    rgba.save(tmp_path / "logo.png")
    out = Image.open(pipeline.process(tmp_path / "logo.png", Settings(FAST_MODEL, scale=2)).out_path)
    assert out.mode == "RGBA" and out.getpixel((5, 5))[3] == 0 and out.getpixel((100, 40))[3] == 255

    photo(60, 40, "L").save(tmp_path / "bw.jpg")
    out = Image.open(pipeline.process(tmp_path / "bw.jpg", Settings(FAST_MODEL, scale=2)).out_path)
    assert out.mode == "L" and out.size == (120, 80)

    g16 = Image.fromarray((np.arange(60 * 40).reshape(40, 60) * 27).astype(np.uint16))
    g16.save(tmp_path / "scan16.tif")
    out = Image.open(pipeline.process(tmp_path / "scan16.tif", Settings(FAST_MODEL, scale=2)).out_path)
    assert out.size == (120, 80)

    photo(60, 40).convert("CMYK").save(tmp_path / "print.jpg")
    r = pipeline.process(tmp_path / "print.jpg", Settings(FAST_MODEL, scale=2))
    assert Image.open(r.out_path).mode == "RGB" and "CMYK" in r.notes[0]


def test_strength_blends_toward_plain_resize(tmp_path, monkeypatch, fake_engine):
    def white_run(src, dst, model, **kw):
        im = Image.open(src)
        Image.new("RGB", (im.width * 4, im.height * 4), "white").save(dst)

    monkeypatch.setattr(engine, "run", white_run)
    Image.new("RGB", (50, 50), "black").save(tmp_path / "k.png")
    out = Image.open(pipeline.process(tmp_path / "k.png", Settings(FAST_MODEL, scale=2, strength=0.5)).out_path)
    assert 120 <= out.getpixel((50, 50))[0] <= 135


@needs_engine
def test_real_engine_end_to_end(tmp_path):
    src = tmp_path / "real.jpg"
    photo(96, 64).save(src, quality=90)
    seen = []
    r = pipeline.process(src, Settings(FAST_MODEL, scale=3), on_progress=seen.append)
    assert Image.open(r.out_path).size == (288, 192)
    assert seen[-1] == 1.0


@needs_engine
def test_real_engine_cancel(tmp_path):
    src = tmp_path / "big.png"
    photo(1400, 1000).save(src)
    cancel = threading.Event()
    threading.Timer(1.5, cancel.set).start()
    with pytest.raises(engine.Cancelled):
        pipeline.process(src, Settings(FAST_MODEL, scale=4), cancel=cancel)
