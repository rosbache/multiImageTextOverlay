"""Per-image metadata precomputation shared by CLI and web.

These helpers resolve, for a batch of images, the values that must be computed
*before* handing work to the worker pool: addresses (geocoded, cached),
chainage from a reference line, and polygon field values from a layer.

The ``lookup`` object supplies the shared caches/state (address cache, staged
location overrides, active line/layer). In the web app this is the ``AppState``;
the CLI constructs an equivalent lightweight context.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional, Protocol

from image_metadata_overlay.config import OverlayConfig
from image_metadata_overlay.geo.polygons import lookup_polygon_value

logger = logging.getLogger(__name__)


class LookupContext(Protocol):
    """State provider for precomputation (satisfied by web ``AppState``)."""
    address_cache: dict
    location_overrides: dict
    geocode_progress: dict
    active_line: Optional[dict]
    active_polygon_layer: Optional[dict]


def get_jpg_files(folder: str) -> list[Path]:
    return [
        f for f in Path(folder).iterdir()
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg")
    ]


def build_image_summary(jpg_files: list[Path]) -> dict:
    """Return simple metadata for a scanned image set."""
    total_size_bytes = sum(f.stat().st_size for f in jpg_files if f.is_file())
    return {
        "count": len(jpg_files),
        "total_size_bytes": total_size_bytes,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
    }


def _coords_for(f: Path, ctx: LookupContext) -> tuple:
    """(lat, lon) for *f*, preferring a staged location override."""
    fn = f.name
    if fn in ctx.location_overrides:
        ov = ctx.location_overrides[fn]
        return ov["lat"], ov["lon"]
    from image_metadata_overlay.core.exif import extract_exif_data
    try:
        meta = extract_exif_data(str(f), filename=fn)
        return meta.get("_lat_decimal"), meta.get("_lon_decimal")
    except Exception:
        return None, None


def lookup_address(image_path: Path, ctx: LookupContext) -> Optional[str]:
    """Look up the cached address for an image, checking overrides first."""
    lat, lon = _coords_for(image_path, ctx)
    if lat is not None and lon is not None:
        key = (round(lat, 6), round(lon, 6))
        return ctx.address_cache.get(key)
    return None


async def geocode_images(jpg_files: list[Path], timeout: int, ctx: LookupContext):
    """Pre-geocode GPS coordinates for a list of images (runs in thread pool)."""
    from image_metadata_overlay.core.exif import extract_exif_data, reverse_geocode

    ctx.geocode_progress["running"] = True
    ctx.geocode_progress["done"] = 0
    ctx.geocode_progress["total"] = len(jpg_files)

    def geocode_one(f: Path) -> None:
        try:
            meta = extract_exif_data(str(f), filename=f.stem)
            lat = meta.get("_lat_decimal")
            lon = meta.get("_lon_decimal")
            if lat is not None and lon is not None:
                key = (round(lat, 6), round(lon, 6))
                if key not in ctx.address_cache:
                    ctx.address_cache[key] = reverse_geocode(lat, lon, timeout=timeout)
        except Exception as e:
            logger.warning(f"Geocode failed for {f.name}: {e}")
        finally:
            ctx.geocode_progress["done"] += 1

    loop = asyncio.get_event_loop()
    for f in jpg_files:
        await loop.run_in_executor(None, geocode_one, f)

    ctx.geocode_progress["running"] = False


def build_address_map(jpg_files: list[Path], show_address: bool,
                      geocoder_timeout: int, ctx: LookupContext) -> dict:
    """Resolve an address per image: cache first, on-demand geocode for misses."""
    address_map: dict[str, Optional[str]] = {}
    if show_address:
        from image_metadata_overlay.core.exif import extract_exif_data, reverse_geocode
        for f in jpg_files:
            addr = lookup_address(f, ctx)
            if addr is None:
                # Cache miss — geocode now using the correct coordinates for this image
                try:
                    meta = extract_exif_data(str(f), filename=f.stem)
                    lat = meta.get("_lat_decimal")
                    lon = meta.get("_lon_decimal")
                    if lat is not None and lon is not None:
                        key = (round(lat, 6), round(lon, 6))
                        if key not in ctx.address_cache:
                            ctx.address_cache[key] = reverse_geocode(
                                lat, lon, timeout=geocoder_timeout
                            )
                        addr = ctx.address_cache.get(key)
                except Exception as e:
                    logger.warning(f"On-demand geocode failed for {f.name}: {e}")
            address_map[f.name] = addr
    else:
        for f in jpg_files:
            address_map[f.name] = None
    return address_map


def build_chainage_map(jpg_files: list[Path], cfg: OverlayConfig,
                       ctx: LookupContext) -> dict:
    """Chainage per image when a reference line is loaded and chainage is enabled."""
    chainage_map: dict[str, Optional[str]] = {f.name: None for f in jpg_files}
    if ctx.active_line is None or not cfg.show_chainage:
        return chainage_map
    try:
        from image_metadata_overlay.core.exif import extract_exif_data
        from image_metadata_overlay.geo import chainage as cc
        locs = []
        for f in jpg_files:
            lat, lon = _coords_for(f, ctx)
            locs.append({"filename": f.name, "lat": lat, "lon": lon})
        results = cc.batch_calculate_chainages(
            ctx.active_line["line"], locs,
            precision=cfg.chainage_precision,
            prefix=cfg.chainage_prefix,
            show_offset=cfg.show_chainage_offset,
            start_m=cfg.chainage_start_m,
        )
        chainage_map = {name: d["formatted"] for name, d in results.items()}
    except Exception as e:
        logger.warning(f"Chainage batch calculation failed: {e}")
    return chainage_map


def build_polygon_value_map(jpg_files: list[Path], ctx: LookupContext) -> dict:
    """For each image compute the polygon field value that contains it (or None)."""
    result: dict[str, Optional[str]] = {}
    if ctx.active_polygon_layer is None:
        return {f.name: None for f in jpg_files}
    for f in jpg_files:
        lat, lon = _coords_for(f, ctx)
        result[f.name] = lookup_polygon_value(ctx.active_polygon_layer, lat, lon)
    return result


def snapshot_line(ctx: LookupContext) -> Optional[dict]:
    """Snapshot the active reference line for the export context (or None)."""
    if ctx.active_line is None:
        return None
    return {
        "geojson_line": ctx.active_line["geojson_line"],
        "markers_geojson": ctx.active_line["markers_geojson"],
        "total_length_m": round(ctx.active_line["line"].total_length, 1),
        "epsg": ctx.active_line["line"].epsg,
    }


def snapshot_polygon(ctx: LookupContext) -> Optional[dict]:
    """Snapshot the active polygon layer for the export context (or None)."""
    if ctx.active_polygon_layer is None:
        return None
    return {
        "geojson": ctx.active_polygon_layer["geojson"],
        "layer": ctx.active_polygon_layer["layer"],
        "field": ctx.active_polygon_layer["field"],
    }
