# Credits and licenses

The app's own code is in this repository (no third-party code is copied into it).
It bundles or downloads the following separately licensed parts.

## Upscaling engine

| Part | Author | License |
|---|---|---|
| `upscayl-bin.exe`, a build of [upscayl-ncnn](https://github.com/upscayl/upscayl-ncnn) (fork of [Real-ESRGAN-ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan)) | Upscayl team, xinntao | AGPL-3.0 (full text in `engine/LICENSE-upscayl-bin.txt`) |

The engine is a separate, unmodified program that the app starts as its own process. Its source code is
available at https://github.com/upscayl/upscayl-ncnn (release `20251207-174704`).

## AI models

Only models whose licenses allow **commercial use** are bundled.

| In the app | Model | Author | License |
|---|---|---|---|
| Natural photo | 4xLSDIRplusC | Philip Hofmann (Phhofm / Helaman) | CC-BY-4.0 |
| Soft or compressed | 4xNomos8kSC | Philip Hofmann (Phhofm / Helaman) | CC-BY-4.0 |
| Quick preview | 4xLSDIRCompactC3 | Philip Hofmann (Phhofm / Helaman) | CC-BY-4.0 |

Models are from https://openmodeldb.info, in the ncnn format published at
https://github.com/upscayl/custom-models. CC-BY-4.0 requires credit to the author, which this file gives.

Tested and **not** bundled: 4x-UltraSharp and 4x-Remacri (CC-BY-NC-SA-4.0, no commercial use).

## Python libraries

Pillow (MIT-CMU), pillow-heif (BSD-3), NumPy (BSD-3), FastAPI (MIT), Uvicorn (BSD-3),
pywebview (BSD-3), pythonnet (MIT).
