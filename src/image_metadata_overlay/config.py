"""
Configuration for Image Metadata Overlay.

``OverlayConfig`` is an immutable value object holding every per-job overlay
setting. It is passed explicitly through the processing pipeline (CLI args,
web settings, multiprocessing workers) instead of being mutated in place.

Module-level ``INPUT_DIR`` / ``OUTPUT_DIR`` remain as *application-level*
default directories (the launcher may patch them when frozen); they are
deliberately not part of ``OverlayConfig``.
"""

from dataclasses import dataclass, replace
from typing import Any, Optional, Tuple

# Application-level default directories (dev convenience; not per-job settings)
INPUT_DIR = r"C:\Users\eor\OneDrive - Multiconsult\Pictures\kabeltrase"
OUTPUT_DIR = r"C:\Users\eor\OneDrive - Multiconsult\Pictures\kabeltrase\processed building"
# INPUT_DIR = r"C:\Users\eor\OneDrive - Multiconsult\Pictures\arbion hønefoss"
# OUTPUT_DIR = r"C:\Users\eor\OneDrive - Multiconsult\Pictures\arbion hønefoss\processed"

_VALID_POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
_VALID_COLLISION_MODES = ("overwrite", "skip", "rename")

# Mapping between the legacy UPPERCASE dict keys (web settings flow, export
# context JSON, worker payloads) and OverlayConfig field names.
_KEY_MAP = {
    "PROJECT_INFO": "project_info",
    "ADD_TEXT_OVERLAY": "add_text_overlay",
    "TEXT_COLOR": "text_color",
    "OUTLINE_COLOR": "outline_color",
    "OUTLINE_WIDTH": "outline_width",
    "FONT_SIZE": "font_size",
    "FONT_PATH": "font_path",
    "TEXT_POSITION": "text_position",
    "PADDING": "padding",
    "OUTPUT_QUALITY": "output_quality",
    "FILE_COLLISION_MODE": "file_collision_mode",
    "SHOW_UTM_COORDINATES": "show_utm_coordinates",
    "TARGET_EPSG": "target_epsg",
    "UTM_ZONE": "utm_zone",
    "UTM_HEMISPHERE": "utm_hemisphere",
    "SHOW_DIRECTION": "show_direction",
    "DIRECTION_PRECISION": "direction_precision",
    "SHOW_ADDRESS": "show_address",
    "GEOCODER_TIMEOUT": "geocoder_timeout",
    "MAX_WORKERS": "max_workers",
    "SHOW_CHAINAGE": "show_chainage",
    "CHAINAGE_PREFIX": "chainage_prefix",
    "CHAINAGE_PRECISION": "chainage_precision",
    "SHOW_CHAINAGE_OFFSET": "show_chainage_offset",
    "CHAINAGE_START_M": "chainage_start_m",
    "POLYGON_APPEND_PROJECT_INFO": "polygon_append_project_info",
    "POLYGON_APPEND_FILENAME": "polygon_append_filename",
}

_TUPLE_FIELDS = ("text_color", "outline_color")


@dataclass(frozen=True)
class OverlayConfig:
    """Immutable overlay/processing settings for one job or session."""

    # Overlay text
    project_info: Optional[str] = "22kV Kabeltrase Ringerike"
    add_text_overlay: bool = True
    # Text appearance (RGB tuples)
    text_color: Tuple[int, int, int] = (255, 255, 255)
    outline_color: Tuple[int, int, int] = (0, 0, 0)
    outline_width: int = 2
    # Font
    font_size: int = 128
    font_path: str = "fonts/arial.ttf"
    # Text positioning
    text_position: str = "bottom-left"
    padding: int = 30
    # Output
    output_quality: int = 95
    file_collision_mode: str = "overwrite"
    # Coordinate system
    show_utm_coordinates: bool = True
    target_epsg: int = 25832
    utm_zone: int = 32
    utm_hemisphere: str = "N"
    # Direction
    show_direction: bool = True
    direction_precision: int = 8
    # Address
    show_address: bool = True
    geocoder_timeout: int = 10
    # Processing
    max_workers: int = 4
    # Chainage / reference line
    show_chainage: bool = False
    chainage_prefix: str = "kp"
    chainage_precision: float = 1
    show_chainage_offset: bool = False
    chainage_start_m: float = 0.0
    # Polygon layer
    polygon_append_project_info: bool = False
    polygon_append_filename: bool = False

    def to_dict(self) -> dict:
        """Serialise to the legacy UPPERCASE-key dict format."""
        return {upper: getattr(self, name) for upper, name in _KEY_MAP.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "OverlayConfig":
        """Build from a legacy UPPERCASE-key dict; unknown keys are ignored."""
        kwargs = {}
        for upper, name in _KEY_MAP.items():
            if upper in d:
                value = d[upper]
                if name in _TUPLE_FIELDS and value is not None:
                    value = tuple(value)
                kwargs[name] = value
        return cls(**kwargs)

    def with_overrides(self, **kwargs: Any) -> "OverlayConfig":
        """Return a copy with the given fields replaced."""
        return replace(self, **kwargs)

    def validate(self) -> bool:
        """Validate configuration values. Raises ValueError if invalid."""
        def validate_rgb(color, name):
            if not isinstance(color, tuple) or len(color) != 3:
                raise ValueError(f"{name} must be a tuple of 3 values (R, G, B)")
            if not all(isinstance(c, int) and 0 <= c <= 255 for c in color):
                raise ValueError(f"{name} values must be integers between 0 and 255")

        validate_rgb(self.text_color, "TEXT_COLOR")
        validate_rgb(self.outline_color, "OUTLINE_COLOR")

        if not isinstance(self.font_size, int) or self.font_size < 1 or self.font_size > 500:
            raise ValueError("FONT_SIZE must be an integer between 1 and 500")
        if not isinstance(self.outline_width, int) or self.outline_width < 0 or self.outline_width > 20:
            raise ValueError("OUTLINE_WIDTH must be an integer between 0 and 20")
        if self.text_position not in _VALID_POSITIONS:
            raise ValueError(f"TEXT_POSITION must be one of: {', '.join(_VALID_POSITIONS)}")
        if not isinstance(self.padding, int) or self.padding < 0:
            raise ValueError("PADDING must be a non-negative integer")
        if not isinstance(self.output_quality, int) or self.output_quality < 1 or self.output_quality > 100:
            raise ValueError("OUTPUT_QUALITY must be an integer between 1 and 100")
        if not isinstance(self.max_workers, int) or self.max_workers < 1 or self.max_workers > 32:
            raise ValueError("MAX_WORKERS must be an integer between 1 and 32")
        if self.file_collision_mode not in _VALID_COLLISION_MODES:
            raise ValueError(f"FILE_COLLISION_MODE must be one of: {', '.join(_VALID_COLLISION_MODES)}")
        if not isinstance(self.show_utm_coordinates, bool):
            raise ValueError("SHOW_UTM_COORDINATES must be a boolean")
        if not isinstance(self.target_epsg, int) or self.target_epsg < 1000 or self.target_epsg > 99999:
            raise ValueError("TARGET_EPSG must be an integer between 1000 and 99999")
        if not isinstance(self.utm_zone, int) or self.utm_zone < 1 or self.utm_zone > 60:
            raise ValueError("UTM_ZONE must be an integer between 1 and 60")
        if self.utm_hemisphere not in ['N', 'S']:
            raise ValueError("UTM_HEMISPHERE must be 'N' or 'S'")
        if not isinstance(self.show_direction, bool):
            raise ValueError("SHOW_DIRECTION must be a boolean")
        if self.direction_precision not in [8, 16]:
            raise ValueError("DIRECTION_PRECISION must be 8 or 16")
        if self.project_info is not None and not isinstance(self.project_info, str):
            raise ValueError("PROJECT_INFO must be a string or None")
        if not isinstance(self.chainage_precision, (int, float)) or self.chainage_precision < 1:
            raise ValueError("CHAINAGE_PRECISION must be a number ≥ 1")
        return True


DEFAULT_CONFIG = OverlayConfig()

