"""Geospatial endpoints: SOSI reference lines / chainage, GeoPackage polygon layers."""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from image_metadata_overlay.geo import polygons
from image_metadata_overlay.services import precompute
from image_metadata_overlay.web.models import (
    CalculateChainagesRequest, LoadGpkgPathRequest, LoadLinePathRequest,
    SelectKurveRequest, SelectPolygonLayerRequest,
)
from image_metadata_overlay.web.routes.images import TEMP_UPLOAD_DIR

logger = logging.getLogger(__name__)

router = APIRouter()


def _state(request: Request):
    return request.app.state.app_state


# ---------------------------------------------------------------------------
# Reference line / chainage endpoints
# ---------------------------------------------------------------------------

@router.post("/api/load-sosi-line-path")
async def load_sosi_line_path(req: LoadLinePathRequest, request: Request):
    """Parse a SOSI file at *req.path* and return the list of available KURVEs."""
    state = _state(request)
    path = Path(req.path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")
    if path.suffix.lower() not in (".sos", ".sosi"):
        raise HTTPException(status_code=400, detail="File must be a .sos or .sosi file")
    try:
        from image_metadata_overlay.geo import chainage as cc
        kurves = cc.list_sosi_kurves(str(path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse SOSI file: {e}")
    state.sosi_temp_path = str(path)
    return {"kurves": kurves, "source_path": str(path)}


@router.post("/api/upload-sosi-line")
async def upload_sosi_line(request: Request, file: UploadFile = File(...)):
    """Accept an uploaded SOSI file and return the list of available KURVEs."""
    state = _state(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".sos", ".sosi"):
        raise HTTPException(status_code=400, detail="Uploaded file must be .sos or .sosi")
    session_dir = TEMP_UPLOAD_DIR / uuid.uuid4().hex
    session_dir.mkdir(parents=True, exist_ok=True)
    dest = session_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)
    try:
        from image_metadata_overlay.geo import chainage as cc
        kurves = cc.list_sosi_kurves(str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to parse SOSI file: {e}")
    state.sosi_temp_path = str(dest)
    return {"kurves": kurves, "source_path": str(dest)}


@router.post("/api/select-kurve")
async def select_kurve(req: SelectKurveRequest, request: Request):
    """Load a specific KURVE from the current SOSI file and store it as the active line."""
    state = _state(request)
    if state.sosi_temp_path is None:
        raise HTTPException(status_code=400, detail="No SOSI file loaded. Load a file first.")
    try:
        from image_metadata_overlay.geo import chainage as cc
        line = cc.load_sosi_line(state.sosi_temp_path, req.object_id, reverse=req.reverse)
        geojson_line = cc.get_line_geojson(line)
        markers_geojson = cc.get_chainage_markers_geojson(
            line, interval_m=req.interval_m,
            start_m=req.start_m, prefix="kp",
        )
        state.active_line = {
            "line": line,
            "geojson_line": geojson_line,
            "markers_geojson": markers_geojson,
            "interval_m": req.interval_m,
            "start_m": req.start_m,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load KURVE {req.object_id}: {e}")
    return {
        "geojson_line": geojson_line,
        "markers_geojson": markers_geojson,
        "total_length_m": round(line.total_length, 1),
        "total_length_exact_m": line.total_length,
        "epsg": line.epsg,
        "object_id": line.object_id,
        "object_type": line.object_type,
    }


@router.get("/api/line-geometry")
async def get_line_geometry(request: Request, interval_m: float = 25.0, start_m: float = 0.0):
    """Return the stored active line GeoJSON and chainage markers."""
    state = _state(request)
    if state.active_line is None:
        raise HTTPException(status_code=404, detail="No reference line loaded")
    stored_interval = state.active_line.get("interval_m", 25.0)
    stored_start_m = state.active_line.get("start_m", 0.0)
    if abs(interval_m - stored_interval) > 0.01 or abs(start_m - stored_start_m) > 0.01:
        from image_metadata_overlay.geo import chainage as cc
        markers = cc.get_chainage_markers_geojson(
            state.active_line["line"], interval_m=interval_m,
            start_m=start_m, prefix="kp",
        )
    else:
        markers = state.active_line["markers_geojson"]
    return {
        "geojson_line": state.active_line["geojson_line"],
        "markers_geojson": markers,
        "total_length_m": round(state.active_line["line"].total_length, 1),
        "total_length_exact_m": state.active_line["line"].total_length,
        "epsg": state.active_line["line"].epsg,
    }


@router.delete("/api/clear-line")
async def clear_line(request: Request):
    """Remove the active reference line from memory."""
    state = _state(request)
    state.active_line = None
    return {"status": "cleared"}


@router.post("/api/calculate-chainages")
async def calculate_chainages_endpoint(req: CalculateChainagesRequest, request: Request):
    """Compute chainage for all GPS-tagged images in *source_folder*."""
    state = _state(request)
    if state.active_line is None:
        raise HTTPException(status_code=400, detail="No reference line loaded")
    folder = Path(req.source_folder)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {req.source_folder}")
    try:
        from image_metadata_overlay.core.exif import extract_exif_data
        from image_metadata_overlay.geo import chainage as cc
        jpg_files = precompute.get_jpg_files(str(folder))
        locs = []
        for f in jpg_files:
            fn = f.name
            if fn in state.location_overrides:
                ov = state.location_overrides[fn]
                locs.append({"filename": fn, "lat": ov["lat"], "lon": ov["lon"]})
            else:
                try:
                    meta = extract_exif_data(str(f), filename=fn)
                    locs.append({"filename": fn,
                                 "lat": meta.get("_lat_decimal"),
                                 "lon": meta.get("_lon_decimal")})
                except Exception:
                    locs.append({"filename": fn, "lat": None, "lon": None})
        results = cc.batch_calculate_chainages(
            state.active_line["line"], locs,
            precision=req.precision,
            start_m=req.start_m,
            prefix=req.prefix,
            show_offset=req.show_offset,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chainage calculation failed: {e}")
    return {"chainages": results}


# ---------------------------------------------------------------------------
# GeoPackage polygon overlay endpoints
# ---------------------------------------------------------------------------

def _layer_summary(path: str, layer_name: str) -> dict:
    """Build a lightweight summary dict for a single layer of *path*."""
    try:
        fields = polygons.read_layer_fields(path, layer_name)
    except Exception as e:
        fields = []
        logger.warning(f"Could not read fields for layer {layer_name}: {e}")
    return {"name": layer_name, "fields": fields}


@router.post("/api/load-gpkg-path")
async def load_gpkg_path(req: LoadGpkgPathRequest, request: Request):
    """Read layers of a GeoPackage from a filesystem path."""
    state = _state(request)
    path = Path(req.path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")
    if path.suffix.lower() not in (".gpkg", ".geojson", ".json", ".shp"):
        logger.warning(f"Unusual polygon layer extension: {path.suffix}")
    try:
        layers = polygons.read_vector_layers(str(path))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read layers: {e}")

    layer_infos = []
    for lyr in layers:
        info = _layer_summary(str(path), lyr["name"])
        info["geometry_type"] = lyr["geometry_type"]
        layer_infos.append(info)

    state.gpkg_temp_path = str(path)
    return {"layers": layer_infos, "source_path": str(path)}


@router.post("/api/upload-gpkg")
async def upload_gpkg(request: Request, file: UploadFile = File(...)):
    """Accept an uploaded GeoPackage file and return its layer summary."""
    state = _state(request)
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".gpkg", ".geojson", ".json"):
        raise HTTPException(status_code=400, detail="Uploaded file must be .gpkg or .geojson")
    session_dir = TEMP_UPLOAD_DIR / uuid.uuid4().hex
    session_dir.mkdir(parents=True, exist_ok=True)
    dest = session_dir / file.filename
    content = await file.read()
    dest.write_bytes(content)
    try:
        layers = polygons.read_vector_layers(str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Failed to read layers: {e}")

    layer_infos = []
    for lyr in layers:
        info = _layer_summary(str(dest), lyr["name"])
        info["geometry_type"] = lyr["geometry_type"]
        layer_infos.append(info)

    state.gpkg_temp_path = str(dest)
    return {"layers": layer_infos, "source_path": str(dest)}


@router.get("/api/gpkg-layer-fields")
async def gpkg_layer_fields(layer: str, request: Request):
    """Return the attribute field names for *layer* of the currently loaded GeoPackage."""
    state = _state(request)
    if state.gpkg_temp_path is None:
        raise HTTPException(status_code=400, detail="No GeoPackage loaded. Load a file first.")
    try:
        fields = polygons.read_layer_fields(state.gpkg_temp_path, layer)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read fields for {layer}: {e}")
    return {"layer": layer, "fields": fields}


@router.post("/api/select-polygon-layer")
async def select_polygon_layer(req: SelectPolygonLayerRequest, request: Request):
    """Load a specific polygon layer + field and store it as the active layer."""
    state = _state(request)
    if state.gpkg_temp_path is None:
        raise HTTPException(status_code=400, detail="No GeoPackage loaded. Load a file first.")
    try:
        layer_state = polygons.load_polygon_layer(state.gpkg_temp_path, req.layer, req.field)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to load layer '{req.layer}': {e}")
    state.active_polygon_layer = layer_state
    return {
        "layer": layer_state["layer"],
        "field": layer_state["field"],
        "feature_count": len(layer_state["features"]),
        "geojson": layer_state["geojson"],
    }


@router.get("/api/polygon-layer")
async def get_polygon_layer(request: Request):
    """Return the currently active polygon layer's GeoJSON (if any)."""
    state = _state(request)
    if state.active_polygon_layer is None:
        return {"loaded": False, "geojson": None}
    return {
        "loaded": True,
        "layer": state.active_polygon_layer["layer"],
        "field": state.active_polygon_layer["field"],
        "feature_count": len(state.active_polygon_layer["features"]),
        "geojson": state.active_polygon_layer["geojson"],
    }


@router.delete("/api/clear-polygon-layer")
async def clear_polygon_layer(request: Request):
    """Remove the active polygon layer from memory."""
    state = _state(request)
    state.active_polygon_layer = None
    return {"status": "cleared"}


@router.get("/api/polygon-values")
async def polygon_values(source_folder: str, request: Request):
    """Return per-image polygon field values for images in *source_folder*."""
    state = _state(request)
    if state.active_polygon_layer is None:
        raise HTTPException(status_code=400, detail="No polygon layer loaded")
    folder = Path(source_folder)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {source_folder}")
    jpg_files = precompute.get_jpg_files(str(folder))
    values = precompute.build_polygon_value_map(jpg_files, state)
    return {"values": values, "field": state.active_polygon_layer["field"]}
