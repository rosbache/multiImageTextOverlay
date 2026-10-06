"""Settings and font-listing endpoints."""

from fastapi import APIRouter, Request

from image_metadata_overlay import config as app_config
from image_metadata_overlay.config import DEFAULT_CONFIG
from image_metadata_overlay.paths import assets_dir

router = APIRouter()


@router.get("/api/settings")
async def get_settings():
    """Return current config defaults as JSON."""
    d = DEFAULT_CONFIG
    return {
        "project_info": d.project_info or "",
        "add_text_overlay": d.add_text_overlay,
        "text_position": d.text_position,
        "padding": d.padding,
        "font_size": d.font_size,
        "font_path": d.font_path,
        "text_color_r": d.text_color[0],
        "text_color_g": d.text_color[1],
        "text_color_b": d.text_color[2],
        "outline_color_r": d.outline_color[0],
        "outline_color_g": d.outline_color[1],
        "outline_color_b": d.outline_color[2],
        "outline_width": d.outline_width,
        "show_utm": d.show_utm_coordinates,
        "target_epsg": d.target_epsg,
        "utm_zone": d.utm_zone,
        "utm_hemisphere": d.utm_hemisphere,
        "show_direction": d.show_direction,
        "direction_precision": d.direction_precision,
        "show_address": d.show_address,
        "geocoder_timeout": d.geocoder_timeout,
        "output_quality": d.output_quality,
        "file_collision_mode": d.file_collision_mode,
        "max_workers": d.max_workers,
        "input_dir": app_config.INPUT_DIR,
        "output_dir": app_config.OUTPUT_DIR,
        "show_chainage": d.show_chainage,
        "chainage_prefix": d.chainage_prefix,
        "chainage_precision": d.chainage_precision,
        "show_chainage_offset": d.show_chainage_offset,
        "chainage_start_m": d.chainage_start_m,
        "polygon_append_project_info": d.polygon_append_project_info,
        "polygon_append_filename": d.polygon_append_filename,
    }


@router.get("/api/fonts")
async def list_fonts():
    """List available .ttf font files in the bundled fonts asset directory."""
    base = assets_dir()
    fonts_dir = base / "fonts"
    if not fonts_dir.exists():
        return {"fonts": []}
    fonts = [str(f.relative_to(base)).replace("\\", "/")
             for f in fonts_dir.rglob("*.ttf")]
    return {"fonts": fonts}
