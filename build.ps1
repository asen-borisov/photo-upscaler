# Builds a standalone Windows app folder + zip (no Python needed on the computer that runs it).
#   powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "Run install.bat first." }
& $py -m pip install -q -r requirements-dev.txt
& $py scripts\setup_engine.py
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }

& $py -m PyInstaller --noconfirm --clean --windowed --name "Photo Upscaler" --icon assets\icon.ico `
    --add-data "photo_upscaler\web;photo_upscaler\web" `
    --add-data "photo_upscaler\models.json;photo_upscaler" `
    --collect-all webview --collect-submodules uvicorn app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$out = "dist\Photo Upscaler"
Copy-Item -Recurse -Force engine "$out\engine"
Copy-Item -Force "READ ME FIRST.txt", LICENSES.md "$out\"
$version = (& $py -c "import photo_upscaler; print(photo_upscaler.__version__)").Trim()
$zip = "dist\PhotoUpscaler-$version-windows"
if (Test-Path "$zip.zip") { Remove-Item "$zip.zip" }
# Python's zip (not Compress-Archive, which writes backslash paths some unzip tools mangle)
& $py -c "import shutil; shutil.make_archive(r'$zip', 'zip', 'dist', 'Photo Upscaler')"
Write-Host "Built $zip.zip"
