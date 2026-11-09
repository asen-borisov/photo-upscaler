"""Download the upscaling engine and AI models into ./engine (one-time setup, not at app runtime).

Every file is pinned to an exact release/commit and checked against its SHA-256,
so a setup can't silently pull a different or tampered file.

    python scripts/setup_engine.py
"""
from __future__ import annotations

import hashlib
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "engine"
MODELS = ENGINE / "models"

RELEASE = "https://github.com/upscayl/upscayl-ncnn/releases/download/20251207-174704/upscayl-bin-20251207-174704-"
ENGINES = {  # platform -> (zip url, {file inside the zip -> (saved as, sha256)})
    "win32": (RELEASE + "windows.zip", {
        "upscayl-bin.exe": ("upscayl-bin.exe", "294d31be8f29d047c0d91a8dcd5e739616ece56bce3188ac688f9a52d70abe60"),
        "LICENSE": ("LICENSE-upscayl-bin.txt", "392150e5ad83609ea48366e700c378fb8e97bf2eec5039bc35685039080f7a85"),
    }),
    "linux": (RELEASE + "linux.zip", {
        "upscayl-bin": ("upscayl-bin", "8b0980197d5bdb6fc4fbc0cc50dae721f3df18d91d0d912ec0a3aeea6495367e"),
        "LICENSE": ("LICENSE-upscayl-bin.txt", "db1a87ba81e885b6bb82971964ab4e202463cde2ac4003571bc5a857d577e4a3"),
    }),
}
CUSTOM = "https://raw.githubusercontent.com/upscayl/custom-models/4b6d2cfa59c7442af115dfc6e50fd8d7d40b96ef/models/"
_SHA = {  # file -> sha256 (models chosen by the comparison in docs/model-test.md)
    "4xLSDIRplusC.param": "4576ed5c2fc5fa250d3c3d585ef02248f26abdfc1867088078f501fe71e5d61e",
    "4xLSDIRplusC.bin": "6df18c714bb7d4ac63ca8a1fb1f1b2712fe3ef5a4b36f09bfa9b827da167ae81",
    "4xNomos8kSC.param": "4576ed5c2fc5fa250d3c3d585ef02248f26abdfc1867088078f501fe71e5d61e",
    "4xNomos8kSC.bin": "da16e3880d87b177b7c6b659bbd880f8a101b868eb9ebc08d69eaa6d3edc4517",
    "4xLSDIRCompactC3.param": "6e3795fb5b6c68b2c39822e78bf83b575c918f96e9db6c36934a79e7d491d5e1",
    "4xLSDIRCompactC3.bin": "692aa5e70c86522ce2d72b94f372751339a2fee65f515d06da5d496d8cf93667",
}
MODEL_FILES = {name: (CUSTOM + name, h) for name, h in _SHA.items()}  # name -> (url, sha256)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "photo-upscaler-setup"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def place(path: Path, data: bytes, expected: str) -> None:
    got = sha256(data)
    if got != expected:
        sys.exit(f"Checksum mismatch for {path.name}: expected {expected}, got {got}. Aborting.")
    path.write_bytes(data)


def main() -> None:
    if sys.platform not in ENGINES:
        sys.exit(f"Unsupported system '{sys.platform}'. Windows and Linux are supported.")
    engine_zip, engine_files = ENGINES[sys.platform]
    MODELS.mkdir(parents=True, exist_ok=True)
    if all((ENGINE / d).exists() and sha256((ENGINE / d).read_bytes()) == h for d, h in engine_files.values()):
        print("engine: ok")
    else:
        print("engine: downloading upscayl-bin ...")
        with zipfile.ZipFile(io.BytesIO(fetch(engine_zip))) as z:
            for name, (dest, expected) in engine_files.items():
                member = next(m for m in z.namelist() if m.endswith("/" + name) or m == name)
                place(ENGINE / dest, z.read(member), expected)
    exe = ENGINE / "upscayl-bin"
    if exe.exists():
        exe.chmod(0o755)  # Linux: zip files don't keep the "can run" flag
    for name, (url, expected) in MODEL_FILES.items():
        dst = MODELS / name
        if dst.exists() and sha256(dst.read_bytes()) == expected:
            print(f"{name}: ok")
            continue
        print(f"{name}: downloading ...")
        place(dst, fetch(url), expected)
    print(f"Done. Engine and models are in {ENGINE}")


if __name__ == "__main__":
    main()
