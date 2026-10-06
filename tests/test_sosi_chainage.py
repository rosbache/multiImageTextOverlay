"""Tests for SOSI parsing and chainage calculation.

Uses the real SOSI file at the repo root (a stikningslinje reference line).

Note on LineGeometry conventions (verified against geo/chainage.py):
- ``coords_utm`` is a list of ``(easting, northing)`` tuples.
- ``_transformer_to_wgs84(epsg).transform(lon, lat)`` uses always_xy (x=lon, y=lat).
- A point at the first vertex has t=0 on segment 0 → valid, chainage 0.
- Chainage increases along the line; reversing swaps start/end chainages.
"""

import math
from pathlib import Path

import pytest

from image_metadata_overlay.geo import chainage as cc
from image_metadata_overlay.geo.chainage import _transformer_to_wgs84
from image_metadata_overlay.geo.sosi import parse_sosi_file

REPO_ROOT = Path(__file__).resolve().parent.parent
SOSI_FILE = REPO_ROOT / "stikningslinje_ rev12.sos"


@pytest.fixture(scope="module")
def line():
    if not SOSI_FILE.exists():
        pytest.skip("SOSI test file not present")
    kurves = cc.list_sosi_kurves(str(SOSI_FILE))
    assert kurves
    return cc.load_sosi_line(str(SOSI_FILE), kurves[0]["id"])


def _point_at_fraction(line, frac):
    """WGS84 (lat, lon) of a point at *frac* of the line's total length."""
    target = line.total_length * frac
    acc = 0.0
    coords = line.coords_utm
    for i in range(1, len(coords)):
        (e0, n0), (e1, n1) = coords[i - 1], coords[i]
        seg = math.hypot(e1 - e0, n1 - n0)
        if acc + seg >= target and seg > 0:
            t = (target - acc) / seg
            e = e0 + (e1 - e0) * t
            n = n0 + (n1 - n0) * t
            lon, lat = _transformer_to_wgs84(line.epsg).transform(e, n)
            return lat, lon
        acc += seg
    # Past the end: return the last vertex
    e, n = coords[-1]
    lon, lat = _transformer_to_wgs84(line.epsg).transform(e, n)
    return lat, lon


def test_parse_sosi_file():
    if not SOSI_FILE.exists():
        pytest.skip("SOSI test file not present")
    parsed = parse_sosi_file(str(SOSI_FILE))
    assert parsed.objects, "expected at least one parsed object"
    assert parsed.header.koordsys is not None


def test_list_sosi_kurves():
    if not SOSI_FILE.exists():
        pytest.skip("SOSI test file not present")
    kurves = cc.list_sosi_kurves(str(SOSI_FILE))
    assert len(kurves) >= 1
    for k in kurves:
        assert k["object_type"] in ("KURVE", "BUEP", "LINJE")
        assert k["coord_count"] >= 2
        assert math.isfinite(k["length_m"]) and k["length_m"] > 0


def test_chainage_at_start_vertex(line):
    lat, lon = _point_at_fraction(line, 0.0)
    r = cc.calculate_chainage(line, lat, lon, precision=1, prefix="kp")
    assert r.valid
    assert r.chainage_m == pytest.approx(0, abs=2)
    assert r.formatted.startswith("kp")


def test_chainage_increases_along_line(line):
    ch_start = cc.calculate_chainage(line, *_point_at_fraction(line, 0.1)).chainage_m
    ch_end = cc.calculate_chainage(line, *_point_at_fraction(line, 0.9)).chainage_m
    assert ch_end > ch_start
    # Within longitudinal extent, chainage should be near the fractional distance
    assert ch_start == pytest.approx(line.total_length * 0.1, rel=0.02, abs=5)
    assert ch_end == pytest.approx(line.total_length * 0.9, rel=0.02, abs=5)


def test_reverse_line_swaps_direction(line):
    if not SOSI_FILE.exists():
        pytest.skip("SOSI test file not present")
    kurves = cc.list_sosi_kurves(str(SOSI_FILE))
    rev = cc.load_sosi_line(str(SOSI_FILE), kurves[0]["id"], reverse=True)
    assert rev.total_length == pytest.approx(line.total_length)
    lat, lon = _point_at_fraction(line, 0.0)  # same physical start vertex
    ch_fwd = cc.calculate_chainage(line, lat, lon).chainage_m
    ch_rev = cc.calculate_chainage(rev, lat, lon).chainage_m
    assert ch_fwd == pytest.approx(0, abs=2)
    assert ch_rev == pytest.approx(rev.total_length, abs=2)


def test_point_past_end_is_na(line):
    # A point well beyond the end of the line should be N/A
    e_end, n_end = line.coords_utm[-1]
    e_prev, n_prev = line.coords_utm[-2]
    # extrapolate 200 m past the end
    de, dn = e_end - e_prev, n_end - n_prev
    seg = math.hypot(de, dn)
    e_past = e_end + de / seg * 200
    n_past = n_end + dn / seg * 200
    lon, lat = _transformer_to_wgs84(line.epsg).transform(e_past, n_past)
    r = cc.calculate_chainage(line, lat, lon)
    assert not r.valid
    assert r.formatted == "N/A"
