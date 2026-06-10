"""
FastAPI Web Interface for Image Metadata Overlay

Starts with: uvicorn web_app:app --reload
Then open:   http://localhost:8000
"""

import asyncio
import base64
import io
import json
import logging
import os
import tempfile
import uuid
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, validator

import config

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
INDEX_HTML = TEMPLATES_DIR / "index.html"
TEMP_UPLOAD_DIR = Path(tempfile.gettempdir()) / "multiImageOverlay_uploads"
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Image Metadata Overlay", version="1.0.0")

# In-memory stores
jobs: dict[str, dict] = {}          # job_id -> {status, processed, total, results}
address_cache: dict[tuple, Optional[str]] = {}  # (lat, lon) -> address string
location_overrides: dict[str, dict] = {}  # filename -> {lat, lon, edited}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class FolderRequest(BaseModel):
    path: str


class OverlaySettings(BaseModel):
    # Directories
    output_dir: str = ""
    # Overlay text
    project_info: str = ""
    text_position: str = "bottom-left"
    padding: int = 30
    # Font
    font_size: int = 128
    font_path: str = "fonts/arial.ttf"
    # Colors
    text_color_r: int = 255
    text_color_g: int = 255
    text_color_b: int = 255
    outline_color_r: int = 0
    outline_color_g: int = 0
    outline_color_b: int = 0
    outline_width: int = 2
    # Coordinates
    show_utm: bool = True
    target_epsg: int = 25832
    utm_zone: int = 32
    utm_hemisphere: str = "N"
    # Direction
    show_direction: bool = True
    direction_precision: int = 8
    # Address
    show_address: bool = True
    geocoder_timeout: int = 5
    # Output
    output_quality: int = 85
    file_collision_mode: str = "overwrite"
    # Processing
    max_workers: int = 4


class PreviewRequest(BaseModel):
    filename: str
    source_folder: str
    settings: OverlaySettings


class ProcessRequest(BaseModel):
    source_folder: str
    output_dir: str
    settings: OverlaySettings
    filenames: list[str] = []   # empty = process all


class LocationUpdateRequest(BaseModel):
    filename: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    reset: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings_to_config_dict(s: OverlaySettings) -> dict:
    """Convert OverlaySettings to the config_dict format expected by workers."""
    return {
        "TEXT_POSITION": s.text_position,
        "TEXT_COLOR": (s.text_color_r, s.text_color_g, s.text_color_b),
        "OUTLINE_COLOR": (s.outline_color_r, s.outline_color_g, s.outline_color_b),
        "OUTLINE_WIDTH": s.outline_width,
        "FONT_SIZE": s.font_size,
        "FONT_PATH": s.font_path,
        "PADDING": s.padding,
        "OUTPUT_QUALITY": s.output_quality,
        "TARGET_EPSG": s.target_epsg,
        "UTM_ZONE": s.utm_zone,
        "UTM_HEMISPHERE": s.utm_hemisphere,
        "SHOW_UTM_COORDINATES": s.show_utm,
        "SHOW_DIRECTION": s.show_direction,
        "DIRECTION_PRECISION": s.direction_precision,
        "PROJECT_INFO": s.project_info or None,
        "SHOW_ADDRESS": s.show_address,
        "GEOCODER_TIMEOUT": s.geocoder_timeout,
        "FILE_COLLISION_MODE": s.file_collision_mode,
        "MAX_WORKERS": s.max_workers,
    }


def _apply_config_dict(cfg: dict):
    """Apply a config_dict to the config module in the current process."""
    for key, value in cfg.items():
        setattr(config, key, value)


def _get_jpg_files(folder: str) -> list[Path]:
    return [
        f for f in Path(folder).iterdir()
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg")
    ]


async def _geocode_images(jpg_files: list[Path], timeout: int):
    """Pre-geocode GPS coordinates for a list of images (runs in thread pool)."""
    from exif_handler import extract_exif_data, reverse_geocode

    def geocode_one(f: Path) -> tuple:
        try:
            meta = extract_exif_data(str(f), filename=f.stem)
            lat = meta.get("_lat_decimal")
            lon = meta.get("_lon_decimal")
            if lat is not None and lon is not None:
                key = (round(lat, 6), round(lon, 6))
                if key not in address_cache:
                    address_cache[key] = reverse_geocode(lat, lon, timeout=timeout)
        except Exception as e:
            logger.warning(f"Geocode failed for {f.name}: {e}")

    loop = asyncio.get_event_loop()
    for f in jpg_files:
        await loop.run_in_executor(None, geocode_one, f)


def _lookup_address(image_path: Path) -> Optional[str]:
    """Look up cached address for an image, checking overrides first."""
    from exif_handler import extract_exif_data
    
    filename = image_path.name
    
    # Check for staged override first
    if filename in location_overrides:
        override = location_overrides[filename]
        lat, lon = override['lat'], override['lon']
    else:
        try:
            meta = extract_exif_data(str(image_path), filename=filename)
            lat = meta.get("_lat_decimal")
            lon = meta.get("_lon_decimal")
        except Exception:
            return None
    
    if lat is not None and lon is not None:
        key = (round(lat, 6), round(lon, 6))
        return address_cache.get(key)
    
    return None


def _generate_preview_sync(input_path: str, cfg_dict: dict) -> bytes:
    """
    Run process_image in-process (called via asyncio.to_thread).
    Returns PNG bytes of the processed image scaled to max 1200px wide.
    """
    import config as cfg
    from image_processor import process_image
    from PIL import Image
    from exif_handler import write_gps_to_exif
    import shutil

    _apply_config_dict(cfg_dict)
    
    # Check if we need to apply a staged override
    filename = Path(input_path).name
    needs_temp_copy = filename in location_overrides
    
    if needs_temp_copy:
        # Create temp copy to avoid modifying source during preview
        temp_path = Path(tempfile.gettempdir()) / f"preview_input_{uuid.uuid4().hex}.jpg"
        shutil.copy2(input_path, temp_path)
        working_path = str(temp_path)
        
        # Apply override to temp copy
        override = location_overrides[filename]
        write_gps_to_exif(working_path, override['lat'], override['lon'])
    else:
        working_path = input_path
        temp_path = None

    address = _lookup_address(Path(input_path))

    out_path = Path(tempfile.gettempdir()) / f"preview_{uuid.uuid4().hex}.jpg"
    try:
        success = process_image(working_path, str(out_path), address=address)
        if not success:
            raise RuntimeError("process_image returned False")

        img = Image.open(str(out_path))
        max_width = 1200
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    finally:
        if out_path.exists():
            out_path.unlink(missing_ok=True)
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _run_batch_job(job_id: str, jpg_files: list[Path], output_dir: Path,
                   cfg_dict: dict, collision_mode: str, max_workers: int,
                   address_map: dict):
    """
    Execute batch processing in a background thread.
    Calls process_single_image workers via ProcessPoolExecutor.
    """
    from main import process_single_image

    jobs[job_id]["status"] = "running"
    jobs[job_id]["total"] = len(jpg_files)

    process_args = [
        (jpg, output_dir, collision_mode, cfg_dict, address_map.get(jpg.name))
        for jpg in jpg_files
    ]

    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(process_single_image, arg): arg[0].name
                      for arg in process_args}
        for future in future_map:
            name = future_map[future]
            try:
                success, fname, msg = future.result()
            except Exception as e:
                success, fname, msg = False, name, str(e)
            results.append({"file": fname, "success": success, "message": msg})
            jobs[job_id]["processed"] += 1
            jobs[job_id]["current_file"] = fname

    jobs[job_id]["status"] = "done"
    jobs[job_id]["results"] = results


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(str(INDEX_HTML), media_type="text/html")


@app.get("/api/settings")
async def get_settings():
    """Return current config defaults as JSON."""
    return {
        "project_info": config.PROJECT_INFO or "",
        "text_position": config.TEXT_POSITION,
        "padding": config.PADDING,
        "font_size": config.FONT_SIZE,
        "font_path": config.FONT_PATH,
        "text_color_r": config.TEXT_COLOR[0],
        "text_color_g": config.TEXT_COLOR[1],
        "text_color_b": config.TEXT_COLOR[2],
        "outline_color_r": config.OUTLINE_COLOR[0],
        "outline_color_g": config.OUTLINE_COLOR[1],
        "outline_color_b": config.OUTLINE_COLOR[2],
        "outline_width": config.OUTLINE_WIDTH,
        "show_utm": config.SHOW_UTM_COORDINATES,
        "target_epsg": config.TARGET_EPSG,
        "utm_zone": config.UTM_ZONE,
        "utm_hemisphere": config.UTM_HEMISPHERE,
        "show_direction": config.SHOW_DIRECTION,
        "direction_precision": config.DIRECTION_PRECISION,
        "show_address": config.SHOW_ADDRESS,
        "geocoder_timeout": config.GEOCODER_TIMEOUT,
        "output_quality": config.OUTPUT_QUALITY,
        "file_collision_mode": config.FILE_COLLISION_MODE,
        "max_workers": config.MAX_WORKERS,
        "input_dir": config.INPUT_DIR,
        "output_dir": config.OUTPUT_DIR,
    }


@app.get("/api/fonts")
async def list_fonts():
    """List available .ttf font files in the fonts/ directory."""
    fonts_dir = BASE_DIR / "fonts"
    if not fonts_dir.exists():
        return {"fonts": []}
    fonts = [str(f.relative_to(BASE_DIR)).replace("\\", "/")
             for f in fonts_dir.rglob("*.ttf")]
    return {"fonts": fonts}


@app.post("/api/load-folder")
async def load_folder(req: FolderRequest, background_tasks: BackgroundTasks):
    """Scan a folder for JPG images and start async geocoding."""
    folder = Path(req.path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {req.path}")

    jpg_files = _get_jpg_files(str(folder))
    if not jpg_files:
        return {"source_folder": str(folder), "images": []}

    # Kick off geocoding in background
    background_tasks.add_task(
        _geocode_images, jpg_files, config.GEOCODER_TIMEOUT
    )

    return {
        "source_folder": str(folder),
        "images": [f.name for f in sorted(jpg_files)],
    }


@app.post("/api/upload")
async def upload_images(background_tasks: BackgroundTasks, files: list[UploadFile] = File(...)):
    """Accept uploaded JPG files and save to a unique per-session temp directory."""
    # Each upload batch gets its own subdirectory so stale files from previous
    # uploads never mix with the current session.
    session_dir = TEMP_UPLOAD_DIR / uuid.uuid4().hex
    session_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for upload in files:
        if not upload.filename:
            continue
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in (".jpg", ".jpeg"):
            continue
        dest = session_dir / upload.filename
        content = await upload.read()
        dest.write_bytes(content)
        saved.append(upload.filename)

    if not saved:
        session_dir.rmdir()
        raise HTTPException(status_code=400, detail="No valid JPG files in upload")

    jpg_files = [session_dir / name for name in saved]

    # Kick off geocoding in background (same as load_folder)
    background_tasks.add_task(_geocode_images, jpg_files, config.GEOCODER_TIMEOUT)

    return {
        "source_folder": str(session_dir),
        "images": sorted(saved),
    }


@app.get("/api/image-locations")
async def get_image_locations(source_folder: str):
    """Return locations for all images in the source folder."""
    from exif_handler import extract_exif_data
    
    folder = Path(source_folder)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {source_folder}")
    
    jpg_files = _get_jpg_files(str(folder))
    locations = []
    
    for jpg_file in jpg_files:
        filename = jpg_file.name
        meta = extract_exif_data(str(jpg_file), filename=filename)
        
        # Check for override first
        if filename in location_overrides:
            override = location_overrides[filename]
            lat = override['lat']
            lon = override['lon']
            has_gps = True
            edited = override.get('edited', True)
        else:
            lat = meta.get('_lat_decimal')
            lon = meta.get('_lon_decimal')
            has_gps = lat is not None and lon is not None
            edited = False
        
        # Get cached address if available
        address = None
        if has_gps:
            key = (round(lat, 6), round(lon, 6))
            address = address_cache.get(key)
        
        locations.append({
            "filename": filename,
            "lat": lat,
            "lon": lon,
            "has_gps": has_gps,
            "edited": edited,
            "address": address
        })
    
    return {"locations": locations}


@app.post("/api/update-location")
async def update_location(req: LocationUpdateRequest):
    """Stage or reset a location override for an image."""
    if req.reset:
        # Reset to original
        if req.filename in location_overrides:
            del location_overrides[req.filename]
        return {"status": "reset", "filename": req.filename}
    
    if req.lat is None or req.lon is None:
        raise HTTPException(status_code=400, detail="Both lat and lon required when not resetting")
    
    # Validate coordinates
    from exif_handler import validate_coordinates
    if not validate_coordinates(req.lat, req.lon):
        raise HTTPException(status_code=400, detail=f"Invalid coordinates: lat={req.lat}, lon={req.lon}")
    
    # Stage the override
    location_overrides[req.filename] = {
        "lat": req.lat,
        "lon": req.lon,
        "edited": True
    }
    
    # Update address cache in background
    from exif_handler import reverse_geocode
    key = (round(req.lat, 6), round(req.lon, 6))
    if key not in address_cache:
        try:
            address_cache[key] = reverse_geocode(req.lat, req.lon, timeout=config.GEOCODER_TIMEOUT)
        except Exception as e:
            logger.warning(f"Geocoding failed for ({req.lat}, {req.lon}): {e}")
    
    return {
        "status": "updated",
        "filename": req.filename,
        "lat": req.lat,
        "lon": req.lon
    }


@app.post("/api/preview")
async def generate_preview(req: PreviewRequest):
    """
    Generate a processed preview for a single image.
    Returns: {"image": "<base64 JPEG>"}
    """
    input_path = Path(req.source_folder) / req.filename
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Image not found: {req.filename}")

    cfg_dict = _settings_to_config_dict(req.settings)

    try:
        img_bytes = await asyncio.to_thread(
            _generate_preview_sync, str(input_path), cfg_dict
        )
    except Exception as e:
        logger.error(f"Preview failed: {e}")
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {e}")

    b64 = base64.b64encode(img_bytes).decode()
    return {"image": b64}


@app.post("/api/process")
async def start_processing(req: ProcessRequest, background_tasks: BackgroundTasks):
    """Start batch image processing. Returns job_id for SSE progress tracking."""
    source_folder = Path(req.source_folder)
    if not source_folder.exists():
        raise HTTPException(status_code=400, detail="Source folder does not exist")

    jpg_files = _get_jpg_files(str(source_folder))
    if not jpg_files:
        raise HTTPException(status_code=400, detail="No JPG images found in source folder")

    # Filter to requested filenames if provided
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

    cfg_dict = _settings_to_config_dict(req.settings)
    
    # Write staged location overrides to source EXIF before processing
    if location_overrides:
        from exif_handler import write_gps_to_exif, reverse_geocode
        
        override_results = []
        for jpg_file in jpg_files:
            if jpg_file.name in location_overrides:
                override = location_overrides[jpg_file.name]
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
                    if key not in address_cache:
                        try:
                            address_cache[key] = reverse_geocode(
                                override['lat'], override['lon'],
                                timeout=req.settings.geocoder_timeout
                            )
                        except Exception as e:
                            logger.warning(f"Geocoding failed for override {jpg_file.name}: {e}")
        
        if override_results:
            logger.info(f"Applied {len(override_results)} location overrides to source EXIF")
            # Clear overrides after writing to source
            for result in override_results:
                if result['success'] and result['file'] in location_overrides:
                    del location_overrides[result['file']]

    # Build address map: use cache where available, geocode synchronously for misses
    address_map: dict[str, Optional[str]] = {}
    if req.settings.show_address:
        from exif_handler import extract_exif_data, reverse_geocode
        for f in jpg_files:
            addr = _lookup_address(f)
            if addr is None:
                # Cache miss — geocode now so we use the correct coordinates for this image
                try:
                    meta = extract_exif_data(str(f), filename=f.stem)
                    lat = meta.get("_lat_decimal")
                    lon = meta.get("_lon_decimal")
                    if lat is not None and lon is not None:
                        key = (round(lat, 6), round(lon, 6))
                        if key not in address_cache:
                            address_cache[key] = reverse_geocode(
                                lat, lon, timeout=req.settings.geocoder_timeout
                            )
                        addr = address_cache.get(key)
                except Exception as e:
                    logger.warning(f"On-demand geocode failed for {f.name}: {e}")
            address_map[f.name] = addr
    else:
        for f in jpg_files:
            address_map[f.name] = None

    job_id = uuid.uuid4().hex
    jobs[job_id] = {
        "status": "queued",
        "processed": 0,
        "total": len(jpg_files),
        "current_file": "",
        "results": [],
    }

    background_tasks.add_task(
        _run_batch_job,
        job_id, jpg_files, output_dir,
        cfg_dict, req.settings.file_collision_mode,
        req.settings.max_workers, address_map,
    )

    return {"job_id": job_id, "total": len(jpg_files)}


@app.get("/api/progress/{job_id}")
async def job_progress(job_id: str):
    """SSE endpoint streaming job progress events."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_stream():
        while True:
            job = jobs.get(job_id, {})
            data = json.dumps({
                "status": job.get("status"),
                "processed": job.get("processed", 0),
                "total": job.get("total", 0),
                "current_file": job.get("current_file", ""),
            })
            yield f"data: {data}\n\n"

            if job.get("status") == "done":
                # Send final results
                results_data = json.dumps({"status": "done", "results": job.get("results", [])})
                yield f"data: {results_data}\n\n"
                break

            await asyncio.sleep(0.4)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.delete("/api/session")
async def cleanup_session():
    """Remove all uploaded temp files and session subdirectories."""
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
