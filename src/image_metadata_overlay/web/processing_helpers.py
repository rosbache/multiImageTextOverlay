"""Settings → OverlayConfig conversion shared by the web routes."""

from image_metadata_overlay.config import OverlayConfig
from image_metadata_overlay.web.models import OverlaySettings


def settings_to_config(s: OverlaySettings) -> OverlayConfig:
    """Convert an OverlaySettings request model to an immutable OverlayConfig."""
    return OverlayConfig(
        text_position=s.text_position,
        text_color=(s.text_color_r, s.text_color_g, s.text_color_b),
        outline_color=(s.outline_color_r, s.outline_color_g, s.outline_color_b),
        outline_width=s.outline_width,
        font_size=s.font_size,
        font_path=s.font_path,
        padding=s.padding,
        output_quality=s.output_quality,
        target_epsg=s.target_epsg,
        utm_zone=s.utm_zone,
        utm_hemisphere=s.utm_hemisphere,
        show_utm_coordinates=s.show_utm,
        show_direction=s.show_direction,
        direction_precision=s.direction_precision,
        project_info=s.project_info or None,
        add_text_overlay=s.add_text_overlay,
        show_address=s.show_address,
        geocoder_timeout=s.geocoder_timeout,
        file_collision_mode=s.file_collision_mode,
        max_workers=s.max_workers,
        show_chainage=s.show_chainage,
        chainage_prefix=s.chainage_prefix,
        chainage_precision=s.chainage_precision,
        show_chainage_offset=s.show_chainage_offset,
        chainage_start_m=s.chainage_start_m,
        polygon_append_project_info=s.polygon_append_project_info,
        polygon_append_filename=s.polygon_append_filename,
    )
