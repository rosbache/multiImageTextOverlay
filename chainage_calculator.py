"""Chainage (stationing) calculation along a reference line for image overlays.

Supports loading a SOSI KURVE as a reference polyline, computing arc-length
chainage for GPS-tagged images, determining L/R offset from the centreline,
and generating GeoJSON for Leaflet map display.

The geometry is handled entirely in the projected UTM coordinate system
(determined from the SOSI KOORDSYS header), so all distances are metric.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# KOORDSYS → EPSG lookup  (no external file dependency)
# ---------------------------------------------------------------------------

_KOORDSYS_EPSG: Dict[int, int] = {
    # NGO1948 Gauss-Krüger (historical)
    1: 27391, 2: 27392, 3: 27393, 4: 27394,
    5: 27395, 6: 27396, 7: 27397, 8: 27398,
    # ETRS89 / UTM (modern Norwegian standard)
    21: 25831, 22: 25832, 23: 25833, 24: 25834, 25: 25835, 26: 25836,
    # WGS84 / UTM
    31: 32631, 32: 32632, 33: 32633, 34: 32634, 35: 32635, 36: 32636,
    # Geographic
    41: 4258, 42: 4326, 84: 4326,
}

_transformer_cache: Dict[str, Any] = {}


def koordsys_to_epsg(koordsys: int) -> int:
    """Return the EPSG code for a SOSI KOORDSYS value, or 25832 as fallback."""
    return _KOORDSYS_EPSG.get(koordsys, 25832)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class LineGeometry:
    """A reference polyline loaded from a SOSI file, ready for chainage work."""

    coords_utm: List[Tuple[float, float]]   # (easting, northing) pairs in UTM
    cumulative_dist: List[float]            # arc-length at each vertex; starts at 0
    total_length: float                     # total arc length in metres
    epsg: int                               # EPSG code for coords_utm
    object_id: int
    object_type: str
    reversed: bool = False


@dataclass
class ChainageResult:
    """Chainage result for a single image location."""

    valid: bool                # False if the image is before/after the line extent
    chainage_m: float = 0.0   # arc-length from line start (metres)
    offset_m: float = 0.0     # perpendicular distance from centreline (metres)
    offset_side: str = ""     # 'L' (left) or 'R' (right) of increasing chainage
    formatted: str = "N/A"    # ready-to-display string, e.g. "kp 1+234 (R 2.3m)"


# ---------------------------------------------------------------------------
# Pyproj transformer helpers (cached)
# ---------------------------------------------------------------------------

def _transformer_to_wgs84(epsg: int):
    key = f"{epsg}→4326"
    if key not in _transformer_cache:
        from pyproj import Transformer
        _transformer_cache[key] = Transformer.from_crs(
            f"EPSG:{epsg}", "EPSG:4326", always_xy=True
        )
    return _transformer_cache[key]


def _transformer_from_wgs84(epsg: int):
    key = f"4326→{epsg}"
    if key not in _transformer_cache:
        from pyproj import Transformer
        _transformer_cache[key] = Transformer.from_crs(
            "EPSG:4326", f"EPSG:{epsg}", always_xy=True
        )
    return _transformer_cache[key]


# ---------------------------------------------------------------------------
# SOSI loading
# ---------------------------------------------------------------------------

def list_sosi_kurves(sosi_file: str) -> List[dict]:
    """Parse *sosi_file* and return metadata for every KURVE-type object.

    Returns a list of dicts::

        {id, object_type, objtype, coord_count, length_m}
    """
    from sosi_parser import parse_sosi_file

    result = parse_sosi_file(sosi_file)
    enhet = result.header.enhet
    origo_n = result.header.origo_n
    origo_e = result.header.origo_e

    kurves = []
    for obj_id, obj in result.objects.items():
        if obj.object_type not in ("KURVE", "BUEP"):
            continue
        coords = obj.scaled_coordinates(enhet, origo_n, origo_e)
        length_m = 0.0
        for i in range(1, len(coords)):
            n0, e0, _ = coords[i - 1]
            n1, e1, _ = coords[i]
            length_m += math.hypot(e1 - e0, n1 - n0)
        kurves.append({
            "id": obj_id,
            "object_type": obj.object_type,
            "objtype": obj.objtype or "",
            "coord_count": len(coords),
            "length_m": round(length_m, 1),
        })

    # Sort by object ID for consistent ordering
    kurves.sort(key=lambda k: k["id"])
    return kurves


def load_sosi_line(
    sosi_file: str,
    object_id: int,
    reverse: bool = False,
) -> LineGeometry:
    """Load one KURVE from *sosi_file* into a :class:`LineGeometry`.

    Parameters
    ----------
    sosi_file:
        Path to the ``.sos`` / ``.sosi`` file.
    object_id:
        SOSI object ID of the desired KURVE.
    reverse:
        When *True* the coordinate sequence is reversed so chainage increases
        in the opposite direction.
    """
    from sosi_parser import parse_sosi_file

    result = parse_sosi_file(sosi_file)
    header = result.header
    enhet = header.enhet
    origo_n = header.origo_n
    origo_e = header.origo_e

    obj = result.objects.get(object_id)
    if obj is None:
        raise ValueError(f"Object ID {object_id} not found in {sosi_file!r}")

    # scaled_coordinates returns (northing, easting, height)
    raw = obj.scaled_coordinates(enhet, origo_n, origo_e)
    if len(raw) < 2:
        raise ValueError(
            f"Object {object_id} has only {len(raw)} coordinate point(s); need ≥ 2"
        )

    # Store as (easting, northing) — standard x/y convention for distance maths
    coords: List[Tuple[float, float]] = [(e, n) for n, e, _h in raw]

    if reverse:
        coords = list(reversed(coords))

    epsg = koordsys_to_epsg(header.koordsys or 22)

    # Cumulative arc length at each vertex
    cum = [0.0]
    for i in range(1, len(coords)):
        dx = coords[i][0] - coords[i - 1][0]
        dy = coords[i][1] - coords[i - 1][1]
        cum.append(cum[-1] + math.hypot(dx, dy))

    return LineGeometry(
        coords_utm=coords,
        cumulative_dist=cum,
        total_length=cum[-1],
        epsg=epsg,
        object_id=object_id,
        object_type=obj.object_type,
        reversed=reverse,
    )


# ---------------------------------------------------------------------------
# GeoJSON generation
# ---------------------------------------------------------------------------

def get_line_geojson(line: LineGeometry) -> dict:
    """Convert *line* to a WGS84 GeoJSON Feature (LineString)."""
    t = _transformer_to_wgs84(line.epsg)
    coords_wgs84 = []
    for e, n in line.coords_utm:
        lon, lat = t.transform(e, n)
        coords_wgs84.append([lon, lat])

    return {
        "type": "Feature",
        "properties": {
            "object_id": line.object_id,
            "total_length_m": round(line.total_length, 1),
            "epsg": line.epsg,
        },
        "geometry": {
            "type": "LineString",
            "coordinates": coords_wgs84,
        },
    }


def get_chainage_markers_geojson(
    line: LineGeometry,
    interval_m: float = 25.0,
) -> dict:
    """Return a GeoJSON FeatureCollection of chainage tick points.

    A point is placed every *interval_m* metres starting at 0.  Each
    feature carries ``chainage_m`` and ``label`` properties.
    """
    t = _transformer_to_wgs84(line.epsg)
    features = []
    d = 0.0
    while d <= line.total_length + 1e-6:
        e, n = _interpolate_utm(line, d)
        lon, lat = t.transform(e, n)
        label = _format_chainage(d, "kp")
        features.append({
            "type": "Feature",
            "properties": {
                "chainage_m": round(d, 1),
                "label": label,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
        })
        d += interval_m

    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# Chainage calculation
# ---------------------------------------------------------------------------

def calculate_chainage(
    line: LineGeometry,
    lat: float,
    lon: float,
    precision: float = 1.0,
    prefix: str = "kp",
    show_offset: bool = False,
) -> ChainageResult:
    """Compute the chainage and optional L/R offset for a single GPS point.

    The nearest perpendicular projection onto the polyline is found by
    iterating over every segment and keeping the minimum-distance candidate.

    **N/A rule**: a result is marked invalid (formatted as ``"N/A"``) only
    when the image lies *before* the line start or *after* the line end —
    i.e. when the unclamped projection parameter on the first or last segment
    falls outside [0, 1] respectively.  Images that are laterally far from
    the line but within the longitudinal extent still receive a valid chainage.

    Parameters
    ----------
    line:
        The reference :class:`LineGeometry`.
    lat / lon:
        WGS84 decimal degrees of the image.
    precision:
        Round the chainage to the nearest *precision* metres (default 1 m).
    prefix:
        Text prefix for the formatted string (default ``"kp"``).
    show_offset:
        When *True*, append ``(L/R X.Xm)`` to the formatted string.
    """
    try:
        t = _transformer_from_wgs84(line.epsg)
        qe, qn = t.transform(lon, lat)   # always_xy: lon→x=E, lat→y=N
    except Exception as exc:
        logger.warning("Coordinate transform failed for (%.6f, %.6f): %s", lat, lon, exc)
        return ChainageResult(valid=False, formatted="N/A")

    coords = line.coords_utm
    cum = line.cumulative_dist
    n_seg = len(coords) - 1

    if n_seg < 1:
        return ChainageResult(valid=False, formatted="N/A")

    best_dist = math.inf
    best_chainage_m = 0.0
    best_offset_side = "R"
    best_seg_idx = 0
    best_t_unclamped = 0.0

    for i in range(n_seg):
        e1, n1 = coords[i]
        e2, n2 = coords[i + 1]
        de = e2 - e1
        dn = n2 - n1
        seg_len_sq = de * de + dn * dn
        if seg_len_sq < 1e-12:
            continue

        we = qe - e1
        wn = qn - n1
        t_raw = (we * de + wn * dn) / seg_len_sq
        t_clamped = max(0.0, min(1.0, t_raw))

        proj_e = e1 + t_clamped * de
        proj_n = n1 + t_clamped * dn
        dist = math.hypot(qe - proj_e, qn - proj_n)

        if dist < best_dist:
            best_dist = dist
            seg_len = math.sqrt(seg_len_sq)
            best_chainage_m = cum[i] + t_clamped * seg_len
            # Cross product: de*wn - dn*we > 0 → Q is to the left of P1→P2
            best_offset_side = "L" if (de * wn - dn * we) > 0 else "R"
            best_seg_idx = i
            best_t_unclamped = t_raw

    # N/A: image projects before line start or after line end
    if best_seg_idx == 0 and best_t_unclamped < 0:
        return ChainageResult(valid=False, formatted="N/A")
    if best_seg_idx == n_seg - 1 and best_t_unclamped > 1:
        return ChainageResult(valid=False, formatted="N/A")

    # Snap to precision
    if precision > 0:
        best_chainage_m = round(best_chainage_m / precision) * precision

    formatted = _format_chainage(best_chainage_m, prefix)
    if show_offset:
        formatted += f" ({best_offset_side} {best_dist:.1f}m)"

    return ChainageResult(
        valid=True,
        chainage_m=best_chainage_m,
        offset_m=round(best_dist, 2),
        offset_side=best_offset_side,
        formatted=formatted,
    )


def batch_calculate_chainages(
    line: LineGeometry,
    image_locations: List[dict],
    precision: float = 1.0,
    prefix: str = "kp",
    show_offset: bool = False,
) -> Dict[str, dict]:
    """Compute chainages for a list of image location dicts.

    Parameters
    ----------
    image_locations:
        List of ``{filename, lat, lon}`` dicts.  Items where ``lat`` or
        ``lon`` is *None* are returned as N/A.

    Returns
    -------
    Dict mapping each *filename* to::

        {valid, chainage_m, offset_m, offset_side, formatted}
    """
    results: Dict[str, dict] = {}
    for loc in image_locations:
        name = loc.get("filename", "")
        lat = loc.get("lat")
        lon = loc.get("lon")
        if lat is None or lon is None:
            results[name] = {
                "valid": False, "formatted": "N/A",
                "chainage_m": 0.0, "offset_m": 0.0, "offset_side": "",
            }
        else:
            r = calculate_chainage(line, lat, lon, precision, prefix, show_offset)
            results[name] = {
                "valid": r.valid,
                "chainage_m": r.chainage_m,
                "offset_m": r.offset_m,
                "offset_side": r.offset_side,
                "formatted": r.formatted,
            }
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _interpolate_utm(
    line: LineGeometry,
    d: float,
) -> Tuple[float, float]:
    """Linearly interpolate UTM (easting, northing) at arc-length *d*."""
    d = max(0.0, min(d, line.total_length))
    cum = line.cumulative_dist
    coords = line.coords_utm

    for i in range(len(cum) - 1):
        if cum[i] <= d <= cum[i + 1]:
            seg_len = cum[i + 1] - cum[i]
            if seg_len < 1e-12:
                return coords[i]
            t = (d - cum[i]) / seg_len
            e = coords[i][0] + t * (coords[i + 1][0] - coords[i][0])
            n = coords[i][1] + t * (coords[i + 1][1] - coords[i][1])
            return (e, n)

    return coords[-1]


def _format_chainage(chainage_m: float, prefix: str) -> str:
    """Format *chainage_m* as ``"<prefix> km+MMM"`` (whole metres)."""
    chainage_m = max(0.0, chainage_m)
    km = int(chainage_m // 1000)
    m = int(round(chainage_m % 1000))
    return f"{prefix} {km}+{m:03d}"
