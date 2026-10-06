"""
Launcher for Image Metadata Overlay web app.

When built with PyInstaller this becomes the entry-point executable.
It starts the uvicorn/FastAPI server and opens a browser tab automatically.
"""

import sys
import os
import threading
import webbrowser
import time


_dll_directory_handles = []


def _resource_path(relative: str) -> str:
    """Return absolute path to a resource, works for dev and PyInstaller bundles."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _configure_native_dlls():
    """Make bundled native geospatial libraries available to pyogrio on Windows."""
    if not getattr(sys, "frozen", False) or not hasattr(os, "add_dll_directory"):
        return

    pyogrio_libs = _resource_path("pyogrio.libs")
    if not os.path.isdir(pyogrio_libs):
        return

    _dll_directory_handles.append(os.add_dll_directory(pyogrio_libs))
    os.environ["PATH"] = pyogrio_libs + os.pathsep + os.environ.get("PATH", "")


def _patch_paths():
    """
    Point config defaults at real directories so that
    the app works out-of-the-box without any manual configuration.
    """
    from image_metadata_overlay import config
    # Only override if the paths don't already point somewhere real.
    # (The font needs no patching: overlay rendering resolves relative font
    # paths against the bundled assets directory via paths.resolve_font.)
    if not os.path.isdir(config.INPUT_DIR):
        config.INPUT_DIR = _resource_path("input")
    if not os.path.isdir(config.OUTPUT_DIR):
        config.OUTPUT_DIR = _resource_path("output")


HOST = "127.0.0.1"
PORT = 8000


def _open_browser():
    """Wait briefly for the server to start, then open the default browser."""
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}")


if __name__ == "__main__":
    # MUST be called before anything else when using ProcessPoolExecutor in a
    # frozen PyInstaller exe.  Without this, each worker process re-executes
    # the launcher instead of running the submitted task.
    import multiprocessing
    multiprocessing.freeze_support()

    # Add the bundle root to sys.path when frozen so all bundled modules
    # are importable (a no-op in dev, where the package is installed).
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir and bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)

    _configure_native_dlls()
    _patch_paths()

    # Open browser in background thread
    threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn
    uvicorn.run(
        "image_metadata_overlay.web.app:app",
        host=HOST,
        port=PORT,
        log_config=None,   # disable uvicorn's colored formatter (crashes without a console)
        log_level="warning",
    )
