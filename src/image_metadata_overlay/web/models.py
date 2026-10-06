"""Pydantic request models for the web API."""

from typing import Optional

from pydantic import BaseModel


class FolderRequest(BaseModel):
    path: str


class OverlaySettings(BaseModel):
    # Directories
    output_dir: str = ""
    # Overlay text
    project_info: str = ""
    add_text_overlay: bool = True
    text_position: str = "bottom-left"
    padding: int = 30
    # Font
    font_size: int = 72
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
    # Chainage
    show_chainage: bool = False
    chainage_prefix: str = "kp"
    chainage_precision: int = 1
    show_chainage_offset: bool = False
    chainage_start_m: float = 0.0
    # Polygon overlay layer
    polygon_append_project_info: bool = False
    polygon_append_filename: bool = False


class PreviewRequest(BaseModel):
    filename: str
    source_folder: str
    settings: OverlaySettings


class ProcessRequest(BaseModel):
    source_folder: str
    output_dir: str
    settings: OverlaySettings
    filenames: list[str] = []   # empty = process all


class FolderExportRequest(BaseModel):
    source_folder: str
    settings: OverlaySettings
    filenames: list[str] = []   # empty = export all images in the folder


class LocationUpdateRequest(BaseModel):
    filename: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    reset: bool = False


class LoadLinePathRequest(BaseModel):
    path: str


class SelectKurveRequest(BaseModel):
    object_id: int
    reverse: bool = False
    interval_m: float = 25.0
    start_m: float = 0.0


class CalculateChainagesRequest(BaseModel):
    source_folder: str
    precision: float = 1.0
    prefix: str = "kp"
    show_offset: bool = False
    start_m: float = 0.0


class LoadGpkgPathRequest(BaseModel):
    path: str


class SelectPolygonLayerRequest(BaseModel):
    layer: str
    field: Optional[str] = None
