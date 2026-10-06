"""HTML report export endpoints."""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from image_metadata_overlay.services import precompute
from image_metadata_overlay.services.export import build_export_zip
from image_metadata_overlay.web.models import FolderExportRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def _state(request: Request):
    return request.app.state.app_state


@router.post("/api/export-html")
async def export_html_report(request: Request):
    """Build and download a ZIP containing report.html + processed images."""
    state = _state(request)
    if state.last_export_context is None or state.last_export_context.get("status") != "done":
        raise HTTPException(
            status_code=409,
            detail="No completed processing job. Run processing first, then export.",
        )
    try:
        zip_path = await asyncio.to_thread(build_export_zip, state.last_export_context)
    except Exception as e:
        logger.error(f"HTML export failed: {e}")
        raise HTTPException(status_code=500, detail=f"HTML export failed: {e}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"report_{stamp}.zip",
        background=BackgroundTask(lambda: Path(zip_path).unlink(missing_ok=True)),
    )


@router.post("/api/export-html-from-folder")
async def export_html_from_folder(req: FolderExportRequest, request: Request):
    """Build a report ZIP straight from a folder of (already processed) images.

    Images are bundled as-is and never modified: staged location overrides are
    reflected in the report map via location_map, source EXIF is left untouched.
    """
    state = _state(request)
    source_folder = Path(req.source_folder)
    if not source_folder.exists():
        raise HTTPException(status_code=400, detail="Source folder does not exist")

    jpg_files = precompute.get_jpg_files(str(source_folder))
    if not jpg_files:
        raise HTTPException(status_code=400, detail="No JPG images found in source folder")

    if req.filenames:
        name_set = set(req.filenames)
        jpg_files = [f for f in jpg_files if f.name in name_set]
        if not jpg_files:
            raise HTTPException(status_code=400, detail="None of the specified files were found")

    from image_metadata_overlay.web.processing_helpers import settings_to_config
    cfg = settings_to_config(req.settings)

    ctx = {
        "job_id": None,
        "created": datetime.now().isoformat(timespec="seconds"),
        "source_folder": str(source_folder),
        "output_dir": str(source_folder),  # images are bundled as-is
        "settings": cfg.to_dict(),
        "filenames": [f.name for f in jpg_files],
        "address_map": precompute.build_address_map(
            jpg_files, req.settings.show_address, req.settings.geocoder_timeout, state
        ),
        "chainage_map": precompute.build_chainage_map(jpg_files, cfg, state),
        "polygon_map": precompute.build_polygon_value_map(jpg_files, state),
        "edited_map": {f.name: f.name in state.location_overrides for f in jpg_files},
        "location_map": {
            f.name: (state.location_overrides[f.name]["lat"],
                     state.location_overrides[f.name]["lon"])
            for f in jpg_files if f.name in state.location_overrides
        },
        "line": precompute.snapshot_line(state),
        "polygon_layer": precompute.snapshot_polygon(state),
        "status": "done",
        "results": [
            {"file": f.name, "success": True, "message": "", "output_file": f.name}
            for f in jpg_files
        ],
    }
    try:
        zip_path = await asyncio.to_thread(build_export_zip, ctx)
    except Exception as e:
        logger.error(f"Folder HTML export failed: {e}")
        raise HTTPException(status_code=500, detail=f"HTML export failed: {e}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"report_{stamp}.zip",
        background=BackgroundTask(lambda: Path(zip_path).unlink(missing_ok=True)),
    )
