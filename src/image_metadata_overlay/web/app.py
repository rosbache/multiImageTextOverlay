"""
FastAPI Web Interface for Image Metadata Overlay

Starts with: uvicorn image_metadata_overlay.web.app:app --host 127.0.0.1 --port 8000
Then open:   http://localhost:8000
"""

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse

from image_metadata_overlay.paths import resource_path
from image_metadata_overlay.web.state import AppState
from image_metadata_overlay.web.routes import export, geo, images, processing, settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Application factory: build the FastAPI app and attach AppState."""
    app = FastAPI(title="Image Metadata Overlay", version="1.0.0")
    app.state.app_state = AppState()

    index_html = resource_path("templates", "index.html")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return FileResponse(str(index_html), media_type="text/html")

    app.include_router(settings.router)
    app.include_router(images.router)
    app.include_router(processing.router)
    app.include_router(geo.router)
    app.include_router(export.router)
    return app


app = create_app()


def run(host: str = "127.0.0.1", port: int = 8000):
    """Start the uvicorn server (console script entry point)."""
    import uvicorn
    uvicorn.run("image_metadata_overlay.web.app:app", host=host, port=port)
