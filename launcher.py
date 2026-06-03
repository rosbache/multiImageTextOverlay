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


def _resource_path(relative: str) -> str:
    """Return absolute path to a resource, works for dev and PyInstaller bundles."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _patch_paths():
    """
    Point config defaults at the bundle's bundled directories so that
    the app works out-of-the-box without any manual configuration.
    """
    import config
    # Only override if the paths don't already point somewhere real
    if not os.path.isdir(config.INPUT_DIR):
        config.INPUT_DIR = _resource_path("input")
    if not os.path.isdir(config.OUTPUT_DIR):
        config.OUTPUT_DIR = _resource_path("output")
    if not os.path.isfile(config.FONT_PATH):
        config.FONT_PATH = _resource_path(os.path.join("fonts", "arial.ttf"))


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

    # Add the bundle root to sys.path so all local modules are importable
    bundle_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    if bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)

    _patch_paths()

    # Open browser in background thread
    threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn
    uvicorn.run(
        "web_app:app",
        host=HOST,
        port=PORT,
        log_config=None,   # disable uvicorn's colored formatter (crashes without a console)
        log_level="warning",
    )
