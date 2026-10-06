"""Batch-processing endpoints: /api/process, SSE progress, geocode progress, session cleanup."""

import asyncio
import json
import logging
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import StreamingResponse

from image_metadata_overlay.config import OverlayConfig
from image_metadata_overlay.services import precompute
from image_metadata_overlay.services.batch import process_single_image
from image_metadata_overlay.web.models import ProcessRequest

logger = logging.getLogger(__name__)

router = APIRouter()


def _state(request: Request):
    return request.app.state.app_state


def _run_batch_job(job_id: str, jpg_files: list[Path], output_dir: Path,
                   cfg: OverlayConfig, collision_mode: str, max_workers: int,
                   address_map: dict, chainage_map: dict, state,
                   edited_map: dict = None, polygon_map: dict = None):
    """
    Execute batch processing in a background thread.
    Calls process_single_image workers via ProcessPoolExecutor.
    """
    state.jobs[job_id]["status"] = "running"
    state.jobs[job_id]["total"] = len(jpg_files)

    _edited_map = edited_map or {}
    _polygon_map = polygon_map or {}
    process_args = [
        (
            jpg, output_dir, collision_mode, cfg,
            address_map.get(jpg.name), chainage_map.get(jpg.name),
            _edited_map.get(jpg.name, False),
            _polygon_map.get(jpg.name),
        )
        for jpg in jpg_files
    ]

    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(process_single_image, arg): arg[0].name
                      for arg in process_args}
        for future in future_map:
            name = future_map[future]
            try:
                success, fname, msg, out_name = future.result()
            except Exception as e:
                success, fname, msg, out_name = False, name, str(e), None
            results.append({"file": fname, "success": success, "message": msg,
                            "output_file": out_name})
            state.jobs[job_id]["processed"] += 1
            state.jobs[job_id]["current_file"] = fname

    state.jobs[job_id]["status"] = "done"
    state.jobs[job_id]["results"] = results

    # Publish results into the export context so /api/export-html can build a report
    if state.last_export_context is not None and state.last_export_context.get("job_id") == job_id:
        state.last_export_context["results"] = results
        state.last_export_context["status"] = "done"


@router.post("/api/process")
async def start_processing(req: ProcessRequest, background_tasks: BackgroundTasks,
                           request: Request):
    """Start batch image processing. Returns job_id for SSE progress tracking."""
    state = _state(request)
    import uuid

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

    output_dir = Path(req.output_dir) if req.output_dir else source_folder / "processed"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Cannot create output dir: {e}")

    from image_metadata_overlay.web.processing_helpers import settings_to_config
    cfg = settings_to_config(req.settings)

    # Snapshot which files had location edits before overrides are cleared
    edited_map: dict[str, bool] = {f.name: f.name in state.location_overrides for f in jpg_files}

    # Write staged location overrides to source EXIF before processing
    if state.location_overrides:
        from image_metadata_overlay.core.exif import write_gps_to_exif, reverse_geocode

        override_results = []
        for jpg_file in jpg_files:
            if jpg_file.name in state.location_overrides:
                override = state.location_overrides[jpg_file.name]
                success = write_gps_to_exif(str(jpg_file), override['lat'], override['lon'])
                override_results.append({
                    "file": jpg_file.name,
                    "success": success,
                    "lat": override['lat'],
                    "lon": override['lon']
                })

                # Refresh address cache with new coordinates
                if success and req.settings.show_address:
                    key = (round(override['lat'], 6), round(override['lon'], 6))
                    if key not in state.address_cache:
                        try:
                            state.address_cache[key] = reverse_geocode(
                                override['lat'], override['lon'],
                                timeout=req.settings.geocoder_timeout
                            )
                        except Exception as e:
                            logger.warning(f"Geocoding failed for override {jpg_file.name}: {e}")

        if override_results:
            logger.info(f"Applied {len(override_results)} location overrides to source EXIF")
            for result in override_results:
                if result['success'] and result['file'] in state.location_overrides:
                    del state.location_overrides[result['file']]

    # Build address map: use cache where available, geocode synchronously for misses
    address_map = precompute.build_address_map(
        jpg_files, req.settings.show_address, req.settings.geocoder_timeout, state
    )

    job_id = uuid.uuid4().hex
    state.jobs[job_id] = {
        "status": "queued",
        "processed": 0,
        "total": len(jpg_files),
        "current_file": "",
        "results": [],
    }

    chainage_map = precompute.build_chainage_map(jpg_files, cfg, state)
    polygon_map = precompute.build_polygon_value_map(jpg_files, state)

    # Snapshot all state needed for the HTML report export. The export is decoupled
    # from live state, so clearing the line/layer afterwards does not affect it.
    state.last_export_context = {
        "job_id": job_id,
        "created": datetime.now().isoformat(timespec="seconds"),
        "source_folder": str(source_folder),
        "output_dir": str(output_dir),
        "settings": cfg.to_dict(),
        "filenames": [f.name for f in jpg_files],
        "address_map": dict(address_map),
        "chainage_map": dict(chainage_map),
        "polygon_map": dict(polygon_map),
        "edited_map": dict(edited_map),
        "line": precompute.snapshot_line(state),
        "polygon_layer": precompute.snapshot_polygon(state),
        "status": "running",
        "results": [],
    }

    background_tasks.add_task(
        _run_batch_job,
        job_id, jpg_files, output_dir,
        cfg, req.settings.file_collision_mode,
        req.settings.max_workers, address_map, chainage_map, state, edited_map,
        polygon_map,
    )

    return {"job_id": job_id, "total": len(jpg_files)}


@router.get("/api/progress/{job_id}")
async def job_progress(job_id: str, request: Request):
    """SSE endpoint streaming job progress events."""
    state = _state(request)
    if job_id not in state.jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        while True:
            job = state.jobs.get(job_id, {})
            data = json.dumps({
                "status": job.get("status"),
                "processed": job.get("processed", 0),
                "total": job.get("total", 0),
                "current_file": job.get("current_file", ""),
            })
            yield f"data: {data}\n\n"

            if job.get("status") == "done":
                results_data = json.dumps({"status": "done", "results": job.get("results", [])})
                yield f"data: {results_data}\n\n"
                break

            await asyncio.sleep(0.4)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/api/geocode-progress")
async def get_geocode_progress(request: Request):
    """Return current background geocoding progress."""
    state = _state(request)
    return {
        "running": state.geocode_progress["running"],
        "done": state.geocode_progress["done"],
        "total": state.geocode_progress["total"],
    }


@router.delete("/api/session")
async def cleanup_session():
    """Remove all uploaded temp files and session subdirectories."""
    from image_metadata_overlay.web.routes.images import TEMP_UPLOAD_DIR

    removed = 0
    for item in TEMP_UPLOAD_DIR.iterdir():
        if item.is_file():
            item.unlink(missing_ok=True)
            removed += 1
        elif item.is_dir():
            for f in item.rglob("*"):
                if f.is_file():
                    f.unlink(missing_ok=True)
                    removed += 1
            item.rmdir()
    return {"removed": removed}
