"""Shared batch-processing orchestration.

Both the CLI and the web app run the same worker: a single task tuple
carrying everything the worker process needs (including the immutable
:class:`~image_metadata_overlay.config.OverlayConfig`, which pickles cleanly
across the ``ProcessPoolExecutor`` boundary — no config-module mutation).
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

from image_metadata_overlay.config import OverlayConfig
from image_metadata_overlay.core.overlay import process_image


def sanitise_filename_fragment(value: str) -> str:
    """Return a filesystem-safe representation of *value* suitable for filename use."""
    if not value:
        return ""
    invalid = '<>:"/\\|?*\r\n\t'
    cleaned = "".join("_" if ch in invalid else ch for ch in value).strip()
    cleaned = "_".join(cleaned.split())  # collapse whitespace
    return cleaned[:80]


def get_unique_output_path(output_path: Path) -> Path:
    """Generate a unique output path by adding a counter if file exists."""
    if not output_path.exists():
        return output_path

    stem = output_path.stem
    suffix = output_path.suffix
    parent = output_path.parent
    counter = 1
    while True:
        new_path = parent / f"{stem}_{counter}{suffix}"
        if not new_path.exists():
            return new_path
        counter += 1


def process_single_image(args_tuple) -> Tuple[bool, str, str, Optional[str]]:
    """
    Multiprocessing worker: process a single image.

    Args:
        args_tuple: Tuple of
            ``(input_path, output_dir, collision_mode, overlay_cfg, address, chainage)``
            with optional trailing entries:
            ``(..., location_edited: bool)`` and
            ``(..., location_edited: bool, polygon_value: Optional[str])``

    Returns:
        ``(success, input_filename, message, output_filename)`` — the output
        name is returned because collision mode ``rename`` and
        ``polygon_append_filename`` can change it.
    """
    tuple_args = list(args_tuple)
    if len(tuple_args) < 6:
        raise ValueError(f"process_single_image expects at least 6 args, got {len(tuple_args)}")

    input_path, output_dir, collision_mode, overlay_cfg, address, chainage = tuple_args[:6]
    assert isinstance(overlay_cfg, OverlayConfig)

    # Optional trailing args
    location_edited = False
    polygon_value = None
    if len(tuple_args) >= 7:
        seventh = tuple_args[6]
        if isinstance(seventh, bool):
            location_edited = seventh
        else:
            polygon_value = seventh
    if len(tuple_args) >= 8:
        polygon_value = tuple_args[7]

    # Create output path with same filename, optionally appending the polygon
    # field value (sanitised) to the stem.
    output_name = input_path.name
    if polygon_value and overlay_cfg.polygon_append_filename:
        stem = input_path.stem
        suffix = input_path.suffix
        safe = sanitise_filename_fragment(str(polygon_value))
        if safe:
            output_name = f"{stem}_{safe}{suffix}"
    output_path = output_dir / output_name

    # Handle file collision
    if output_path.exists():
        if collision_mode == 'skip':
            return True, input_path.name, "skipped (already exists)", output_path.name
        elif collision_mode == 'rename':
            output_path = get_unique_output_path(output_path)
            logging.debug(f"Renamed output to: {output_path.name}")

    success = process_image(
        str(input_path), str(output_path),
        address=address, chainage=chainage,
        location_edited=location_edited,
        polygon_value=polygon_value,
        config=overlay_cfg,
    )

    if success:
        return True, input_path.name, "processed successfully", output_path.name
    return False, input_path.name, "processing failed", output_path.name
