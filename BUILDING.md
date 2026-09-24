# Building and Deploying

This project is packaged as a Windows desktop application with PyInstaller.
The executable starts the local FastAPI server and opens the web interface in
the user's default browser.

## Prerequisites

- Windows
- Python installed
- A project virtual environment at `.venv`
- A TrueType font at `fonts\\arial.ttf`

Create the environment once, from the repository root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Build

Run the build script from PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

The script installs the required dependencies, clears previous `build` and
`dist` folders, and builds using `launcher.spec`.

The release is written to:

```text
dist\ImageMetadataOverlay\
```

Start the application locally with:

```powershell
.\dist\ImageMetadataOverlay\ImageMetadataOverlay.exe
```

## Deploy

The current `launcher.spec` is configured for a PyInstaller `onedir` build.
Copy or zip the entire `dist\ImageMetadataOverlay` directory for deployment.
Do not distribute only `ImageMetadataOverlay.exe`, because it depends on the
DLLs, Python runtime, templates, fonts, PROJ files, and SOSI lookup data beside
it.

The recipient can extract the folder anywhere writable and run
`ImageMetadataOverlay.exe`. No Python installation or virtual environment is
required on the recipient's machine.

## Verification

After each build:

1. Start `ImageMetadataOverlay.exe` from the release folder.
2. Confirm that the browser opens at `http://127.0.0.1:8000`.
3. Load a JPG and generate a preview.
4. If chainage is used, load a SOSI file and confirm that it can list and select a line.
5. If polygon overlays are used, load a GeoPackage and confirm that a layer can be selected.

## Optional Single File Build

Set `ONEFILE = True` in `launcher.spec` and rerun `build.ps1` to produce a
single executable in `dist`. This is easier to share but starts more slowly,
because PyInstaller extracts bundled files to a temporary folder at launch.

Restore `ONEFILE = False` for the standard, faster `onedir` deployment.