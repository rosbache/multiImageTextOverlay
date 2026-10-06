"""Web application state.

A single :class:`AppState` instance is stored on the FastAPI ``app.state`` and
shared by all routes. The tool targets a single local user, so state is global
to the app rather than keyed per session.
"""

from typing import Optional

from image_metadata_overlay.config import OverlayConfig


class AppState:
    """Holds all mutable web-session state previously kept as module globals."""

    def __init__(self) -> None:
        # Job tracking: job_id -> {status, processed, total, results, ...}
        self.jobs: dict[str, dict] = {}
        # Geocoding cache: (rounded lat, rounded lon) -> address string
        self.address_cache: dict[tuple, Optional[str]] = {}
        # Staged location edits: filename -> {"lat", "lon", "edited"}
        self.location_overrides: dict[str, dict] = {}
        # Live background-geocoding progress
        self.geocode_progress: dict = {"running": False, "done": 0, "total": 0}
        # Snapshot of the last completed job for the HTML report export
        self.last_export_context: Optional[dict] = None
        # Active SOSI reference line: {"line", "geojson_line", "markers_geojson", ...}
        self.active_line: Optional[dict] = None
        # Path of the currently loaded SOSI file
        self.sosi_temp_path: Optional[str] = None
        # Active polygon layer state (see geo.polygons.load_polygon_layer)
        self.active_polygon_layer: Optional[dict] = None
        # Path of the currently loaded GeoPackage
        self.gpkg_temp_path: Optional[str] = None
