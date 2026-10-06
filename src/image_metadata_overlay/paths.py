"""Resource path resolution for bundled assets.

Assets (templates, fonts, SOSI data) are real files on disk in every supported
deployment mode, so plain __file__-relative resolution is used:

- Dev / pip install: assets live next to this module inside the package.
- PyInstaller (frozen): assets are collected into
  ``_MEIPASS/image_metadata_overlay/assets`` by launcher.spec.
"""

import sys
from pathlib import Path

_PACKAGE_NAME = "image_metadata_overlay"
_ASSETS_DIR_NAME = "assets"


def assets_dir() -> Path:
    """Absolute path to the bundled assets directory."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / _PACKAGE_NAME / _ASSETS_DIR_NAME
    return Path(__file__).resolve().parent / _ASSETS_DIR_NAME


def resource_path(*parts: str) -> Path:
    """Resolve a path inside the assets directory (may not exist)."""
    return assets_dir().joinpath(*parts)


def resolve_font(font_path: str) -> str:
    """Resolve a font path to a real file.

    Relative paths (e.g. the web UI's ``fonts/arial.ttf`` contract) are looked
    up inside the assets directory. Absolute paths are returned unchanged.
    If nothing matches, the input is returned as-is so the caller's fallback
    logic (system fonts) can take over.
    """
    p = Path(font_path)
    if p.is_absolute():
        return str(p)
    candidate = assets_dir() / font_path
    if candidate.is_file():
        return str(candidate)
    return font_path
