"""Smoke tests for overlay rendering and EXIF preservation."""

import piexif
import pytest
from PIL import Image

from image_metadata_overlay.config import DEFAULT_CONFIG
from image_metadata_overlay.core.overlay import process_image


def _make_gps_jpg(path, lat=(60, 8, 30.0), lon=(10, 15, 27.0), size=(400, 300)):
    """Create a small JPEG with GPS EXIF at *path* (default: Hønefoss area)."""
    def to_rationals(dms):
        deg = int(dms[0]); m = int(dms[1]); s = dms[2]
        return ((deg, 1), (m, 1), (int(s * 100), 100))

    img = Image.new("RGB", size, (70, 120, 80))
    img.save(path, "JPEG")
    exif = {
        "0th": {piexif.ImageIFD.Orientation: 1},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2024:03:15 14:30:45"},
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: to_rationals(lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: to_rationals(lon),
            piexif.GPSIFD.GPSAltitude: (120, 1),
        },
    }
    piexif.insert(piexif.dump(exif), str(path))


def test_process_image_renders_overlay_and_preserves_gps(tmp_path):
    src = tmp_path / "photo.jpg"
    out = tmp_path / "photo_out.jpg"
    _make_gps_jpg(src)

    cfg = DEFAULT_CONFIG.with_overrides(
        font_size=20, show_address=False, project_info="TEST PROJECT",
    )
    assert process_image(str(src), str(out), config=cfg) is True
    assert out.is_file()

    # GPS is preserved verbatim; Orientation stays 1
    exif = piexif.load(str(out))
    assert exif["GPS"], "GPS EXIF should be preserved"
    assert exif["GPS"][piexif.GPSIFD.GPSLatitude][0][0] == 60
    assert exif["0th"].get(piexif.ImageIFD.Orientation) == 1

    # Overlay actually changed pixels (the bottom-left text area differs)
    src_img = Image.open(src).convert("RGB")
    out_img = Image.open(out).convert("RGB")
    w, h = src_img.size
    strip_src = src_img.crop((0, h - 80, w, h)).tobytes()
    strip_out = out_img.crop((0, h - 80, w, h)).tobytes()
    assert strip_src != strip_out, "overlay text should modify bottom strip pixels"


def test_process_image_no_overlay_mode_copies_lossless(tmp_path):
    src = tmp_path / "photo.jpg"
    out = tmp_path / "photo_out.jpg"
    _make_gps_jpg(src)

    cfg = DEFAULT_CONFIG.with_overrides(add_text_overlay=False)
    assert process_image(str(src), str(out), config=cfg) is True
    # Byte-identical copy
    assert src.read_bytes() == out.read_bytes()


def test_process_image_no_overlay_same_path_is_noop(tmp_path):
    src = tmp_path / "photo.jpg"
    _make_gps_jpg(src)
    cfg = DEFAULT_CONFIG.with_overrides(add_text_overlay=False)
    # input == output should not raise (SameFileError guard)
    assert process_image(str(src), str(src), config=cfg) is True
