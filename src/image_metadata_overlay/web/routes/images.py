"""Image browsing endpoints: folder scan, upload, locations, thumbnails, EXIF."""

import asyncio
import base64
import io
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from image_metadata_overlay.config import DEFAULT_CONFIG, OverlayConfig
from image_metadata_overlay.services import precompute
from image_metadata_overlay.web.models import (
    FolderRequest, LocationUpdateRequest, PreviewRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

TEMP_UPLOAD_DIR = Path(tempfile.gettempdir()) / "multiImageOverlay_uploads"
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _state(request: Request):
    return request.app.state.app_state


def _generate_preview_sync(input_path: str, cfg: OverlayConfig, ctx,
                           chainage: Optional[str] = None,
                           polygon_value: Optional[str] = None) -> bytes:
    """
    Run process_image in-process (called via asyncio.to_thread).
    Returns JPEG bytes of the processed image scaled to max 1200px wide.
    """
    from image_metadata_overlay.core.overlay import process_image
    from PIL import Image
    from image_metadata_overlay.core.exif import write_gps_to_exif

    # Check if we need to apply a staged override
    filename = Path(input_path).name
    needs_temp_copy = filename in ctx.location_overrides

    if needs_temp_copy:
        # Create temp copy to avoid modifying source during preview
        temp_path = Path(tempfile.gettempdir()) / f"preview_input_{uuid.uuid4().hex}.jpg"
        shutil.copy2(input_path, temp_path)
        working_path = str(temp_path)
        override = ctx.location_overrides[filename]
        write_gps_to_exif(working_path, override['lat'], override['lon'])
    else:
        working_path = input_path
        temp_path = None

    address = precompute.lookup_address(Path(input_path), ctx)

    out_path = Path(tempfile.gettempdir()) / f"preview_{uuid.uuid4().hex}.jpg"
    try:
        success = process_image(
            working_path, str(out_path),
            address=address, chainage=chainage,
            location_edited=needs_temp_copy,
            polygon_value=polygon_value, config=cfg,
        )
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


@router.post("/api/load-folder")
async def load_folder(req: FolderRequest, background_tasks: BackgroundTasks,
                      request: Request):
    """Scan a folder for JPG images and start async geocoding."""
    state = _state(request)
    folder = Path(req.path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {req.path}")

    jpg_files = precompute.get_jpg_files(str(folder))
    if not jpg_files:
        return {"source_folder": str(folder), "images": [],
                "summary": precompute.build_image_summary([])}

    state.geocode_progress["running"] = True
    state.geocode_progress["done"] = 0
    state.geocode_progress["total"] = len(jpg_files)
    background_tasks.add_task(
        precompute.geocode_images, jpg_files, DEFAULT_CONFIG.geocoder_timeout, state
    )

    return {
        "source_folder": str(folder),
        "images": [f.name for f in sorted(jpg_files)],
        "summary": precompute.build_image_summary(jpg_files),
    }


@router.post("/api/upload")
async def upload_images(background_tasks: BackgroundTasks, request: Request,
                        files: list[UploadFile] = File(...)):
    """Accept uploaded JPG files and save to a unique per-session temp directory."""
    state = _state(request)
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

    state.geocode_progress["running"] = True
    state.geocode_progress["done"] = 0
    state.geocode_progress["total"] = len(jpg_files)
    background_tasks.add_task(
        precompute.geocode_images, jpg_files, DEFAULT_CONFIG.geocoder_timeout, state
    )

    return {
        "source_folder": str(session_dir),
        "images": sorted(saved),
        "summary": precompute.build_image_summary(jpg_files),
    }


@router.get("/api/image-locations")
async def get_image_locations(source_folder: str, request: Request):
    """Return locations for all images in the source folder."""
    state = _state(request)
    from image_metadata_overlay.core.exif import extract_exif_data

    folder = Path(source_folder)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {source_folder}")

    jpg_files = precompute.get_jpg_files(str(folder))
    locations = []

    for jpg_file in jpg_files:
        filename = jpg_file.name
        lat = None
        lon = None
        has_gps = False
        edited = False
        address = None
        status = "missing"
        status_detail = "No GPS coordinates found in the image metadata."

        try:
            meta = extract_exif_data(str(jpg_file), filename=filename)
        except Exception as exc:
            status = "error"
            status_detail = f"Could not read EXIF metadata: {exc}"
        else:
            if filename in state.location_overrides:
                override = state.location_overrides[filename]
                lat = override['lat']
                lon = override['lon']
                has_gps = True
                edited = override.get('edited', True)
                status = "edited" if edited else "manual"
                status_detail = "Manual location override applied."
            else:
                lat = meta.get('_lat_decimal')
                lon = meta.get('_lon_decimal')
                has_gps = lat is not None and lon is not None
                edited = False

            if has_gps:
                key = (round(lat, 6), round(lon, 6))
                address = state.address_cache.get(key)
                status = "geolocated"
                status_detail = "GPS coordinates available."
                if address is None:
                    status = "address-pending"
                    status_detail = "Coordinates available, address lookup pending or unavailable."
            else:
                status = "missing"
                status_detail = "No GPS coordinates found in the image metadata."

        locations.append({
            "filename": filename,
            "lat": lat,
            "lon": lon,
            "has_gps": has_gps,
            "edited": edited,
            "address": address,
            "status": status,
            "status_detail": status_detail,
        })

    return {"locations": locations}


@router.get("/api/thumbnail")
async def get_thumbnail(source_folder: str, filename: str, max_size: int = 320):
    """Return a small JPEG thumbnail of a source image (used for map popup previews)."""
    from PIL import Image, ImageOps

    folder = Path(source_folder)
    if not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {source_folder}")
    target = (folder / filename).resolve()
    try:
        target.relative_to(folder.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not target.is_file() or target.suffix.lower() not in (".jpg", ".jpeg"):
        raise HTTPException(status_code=404, detail=f"Image not found: {filename}")

    def _make_thumb() -> bytes:
        with Image.open(target) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((max_size, max_size))
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=80)
            return buf.getvalue()

    data = await asyncio.to_thread(_make_thumb)
    return StreamingResponse(io.BytesIO(data), media_type="image/jpeg")


@router.post("/api/update-location")
async def update_location(req: LocationUpdateRequest, request: Request):
    """Stage or reset a location override for an image."""
    state = _state(request)
    if req.reset:
        if req.filename in state.location_overrides:
            del state.location_overrides[req.filename]
        return {"status": "reset", "filename": req.filename}

    if req.lat is None or req.lon is None:
        raise HTTPException(status_code=400, detail="Both lat and lon required when not resetting")

    from image_metadata_overlay.core.exif import validate_coordinates
    if not validate_coordinates(req.lat, req.lon):
        raise HTTPException(status_code=400, detail=f"Invalid coordinates: lat={req.lat}, lon={req.lon}")

    state.location_overrides[req.filename] = {
        "lat": req.lat,
        "lon": req.lon,
        "edited": True
    }

    # Update address cache in background
    from image_metadata_overlay.core.exif import reverse_geocode
    key = (round(req.lat, 6), round(req.lon, 6))
    if key not in state.address_cache:
        try:
            state.address_cache[key] = reverse_geocode(
                req.lat, req.lon, timeout=DEFAULT_CONFIG.geocoder_timeout)
        except Exception as e:
            logger.warning(f"Geocoding failed for ({req.lat}, {req.lon}): {e}")

    return {
        "status": "updated",
        "filename": req.filename,
        "lat": req.lat,
        "lon": req.lon
    }


@router.post("/api/preview")
async def generate_preview(req: PreviewRequest, request: Request):
    """
    Generate a processed preview for a single image.
    Returns: {"image": "<base64 JPEG>"}
    """
    state = _state(request)
    input_path = Path(req.source_folder) / req.filename
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Image not found: {req.filename}")

    from image_metadata_overlay.web.processing_helpers import settings_to_config
    cfg = settings_to_config(req.settings)

    # Compute chainage for this image if a reference line is active
    chainage_str: Optional[str] = None
    if state.active_line is not None and req.settings.show_chainage:
        try:
            from image_metadata_overlay.core.exif import extract_exif_data
            from image_metadata_overlay.geo import chainage as cc
            meta = extract_exif_data(str(input_path), filename=req.filename)
            lat = meta.get("_lat_decimal")
            lon = meta.get("_lon_decimal")
            if req.filename in state.location_overrides:
                ov = state.location_overrides[req.filename]
                lat, lon = ov["lat"], ov["lon"]
            if lat is not None and lon is not None:
                result = cc.calculate_chainage(
                    state.active_line["line"], lat, lon,
                    precision=req.settings.chainage_precision,
                    prefix=req.settings.chainage_prefix,
                    show_offset=req.settings.show_chainage_offset,
                    start_m=req.settings.chainage_start_m,
                )
                chainage_str = result.formatted
        except Exception as e:
            logger.warning(f"Chainage calc failed for preview {req.filename}: {e}")

    # Compute polygon field value for this image if a polygon layer is active
    polygon_value_str: Optional[str] = None
    if state.active_polygon_layer is not None:
        try:
            from image_metadata_overlay.core.exif import extract_exif_data
            from image_metadata_overlay.geo.polygons import lookup_polygon_value
            if req.filename in state.location_overrides:
                ov = state.location_overrides[req.filename]
                lat, lon = ov["lat"], ov["lon"]
            else:
                meta = extract_exif_data(str(input_path), filename=req.filename)
                lat = meta.get("_lat_decimal")
                lon = meta.get("_lon_decimal")
            polygon_value_str = lookup_polygon_value(state.active_polygon_layer, lat, lon)
        except Exception as e:
            logger.warning(f"Polygon lookup failed for preview {req.filename}: {e}")

    try:
        img_bytes = await asyncio.to_thread(
            _generate_preview_sync, str(input_path), cfg, state, chainage_str, polygon_value_str
        )
    except Exception as e:
        logger.error(f"Preview failed: {e}")
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {e}")

    b64 = base64.b64encode(img_bytes).decode()
    return {"image": b64}


@router.get("/api/exif")
async def get_exif_data(filename: str, source_folder: str):
    """Return all EXIF tags and image dimensions for the given image."""
    import piexif
    from PIL import Image as PilImage

    input_path = Path(source_folder) / filename
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Image not found: {filename}")

    result: dict[str, Any] = {}

    try:
        with PilImage.open(str(input_path)) as im:
            result["width"], result["height"] = im.size
    except Exception as e:
        logger.warning(f"Could not open image for dimensions: {e}")

    result["file_size_bytes"] = input_path.stat().st_size

    tag_sections: dict[str, dict[str, str]] = {}
    try:
        exif_dict = piexif.load(str(input_path))
        ifd_names = {
            "0th": piexif.ImageIFD,
            "Exif": piexif.ExifIFD,
            "GPS": piexif.GPSIFD,
            "1st": piexif.ImageIFD,
        }
        for ifd_key, ifd_tags in ifd_names.items():
            section = exif_dict.get(ifd_key, {})
            if not section:
                continue
            tag_map = {v: k for k, v in vars(ifd_tags).items() if isinstance(v, int)}
            entries: dict[str, str] = {}
            for tag_id, value in section.items():
                tag_name = tag_map.get(tag_id, f"Tag_{tag_id}")
                if isinstance(value, bytes):
                    try:
                        decoded = value.decode("utf-8").rstrip("\x00")
                    except UnicodeDecodeError:
                        decoded = value.decode("latin-1", errors="replace").rstrip("\x00")
                    entries[tag_name] = decoded
                elif isinstance(value, tuple) and all(isinstance(v, tuple) for v in value):
                    parts = [f"{n}/{d}" for n, d in value]
                    entries[tag_name] = ", ".join(parts)
                elif isinstance(value, tuple) and len(value) == 2:
                    n, d = value
                    entries[tag_name] = f"{n/d:.6g}" if d != 0 else str(n)
                else:
                    entries[tag_name] = str(value)
            if entries:
                tag_sections[ifd_key] = entries
    except Exception as e:
        logger.warning(f"Could not read EXIF tags for {filename}: {e}")

    result["exif"] = tag_sections
    return result
