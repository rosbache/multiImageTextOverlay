$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found at .venv. Create it and install dependencies before building."
}

& $python -m pip install -r requirements.txt
& $python -m pip install "PyInstaller>=6.20,<7"

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
& $python -m PyInstaller --noconfirm --clean launcher.spec

Write-Host "Build complete: $PSScriptRoot\dist\ImageMetadataOverlay\ImageMetadataOverlay.exe"$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Create .venv and install dependencies first."
}

& $python -m pip install -r requirements.txt
& $python -m pip install "PyInstaller>=6.20,<7"

Remove-Item -Recurse -Force .\build, .\dist -ErrorAction SilentlyContinue
& $python -m PyInstaller --noconfirm --clean .\launcher.spec

Write-Host "Build complete: $PWD\dist\ImageMetadataOverlay\ImageMetadataOverlay.exe"