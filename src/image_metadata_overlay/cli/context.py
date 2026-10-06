"""Lookup context for CLI precomputation (satisfies precompute.LookupContext).

The CLI has no HTTP session, so this is a lightweight stand-in for the web
``AppState`` holding only what the precompute services need.
"""

from typing import Optional


class CliContext:
    def __init__(self) -> None:
        self.address_cache: dict = {}
        self.location_overrides: dict = {}
        self.geocode_progress: dict = {"running": False, "done": 0, "total": 0}
        self.active_line: Optional[dict] = None
        self.active_polygon_layer: Optional[dict] = None
