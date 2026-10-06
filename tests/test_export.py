"""Smoke test for the HTML report export (services/export.py)."""

import zipfile

import piexif
from PIL import Image

from image_metadata_overlay.services.export import build_export_zip


def _make_jpg(path, size=(200, 150)):
    img = Image.new("RGB", size, (40, 90, 140))
    img.save(path, "JPEG")


def test_build_export_zip(tmp_path):
    out_dir = tmp_path / "processed"
    out_dir.mkdir()
    _make_jpg(out_dir / "a.jpg")
    _make_jpg(out_dir / "b.jpg")

    ctx = {
        "job_id": None,
        "created": "2026-10-06 12:00:00",
        "source_folder": str(out_dir),
        "output_dir": str(out_dir),
        "settings": {"PROJECT_INFO": "Test Project"},
        "filenames": ["a.jpg", "b.jpg"],
        "address_map": {"a.jpg": "Main Street 1", "b.jpg": None},
        "chainage_map": {"a.jpg": "kp 1+000", "b.jpg": None},
        "polygon_map": {},
        "edited_map": {},
        "line": None,
        "polygon_layer": None,
        "status": "done",
        "results": [
            {"file": "a.jpg", "success": True, "message": "", "output_file": "a.jpg"},
            {"file": "b.jpg", "success": True, "message": "", "output_file": "b.jpg"},
            {"file": "c.jpg", "success": False, "message": "no GPS", "output_file": None},
        ],
    }

    zip_path = build_export_zip(ctx)
    try:
        assert zip_path.is_file()
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert "report.html" in names
            assert "images/a.jpg" in names
            assert "images/b.jpg" in names
            html = zf.read("report.html").decode("utf-8")
        assert "Test Project" in html
        assert "Main Street 1" in html
        assert "kp 1+000" in html
        assert "c.jpg" in html  # listed under failed/skipped
    finally:
        zip_path.unlink(missing_ok=True)


def test_build_export_zip_missing_output_marks_failed(tmp_path):
    out_dir = tmp_path / "processed"
    out_dir.mkdir()
    _make_jpg(out_dir / "a.jpg")

    ctx = {
        "created": "2026-10-06 12:00:00",
        "source_folder": str(out_dir),
        "output_dir": str(out_dir),
        "settings": {},
        "filenames": ["a.jpg"],
        "address_map": {}, "chainage_map": {}, "polygon_map": {}, "edited_map": {},
        "line": None, "polygon_layer": None, "status": "done",
        "results": [
            {"file": "a.jpg", "success": True, "message": "", "output_file": "a.jpg"},
            {"file": "missing.jpg", "success": True, "message": "", "output_file": "missing.jpg"},
        ],
    }
    zip_path = build_export_zip(ctx)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            assert "images/a.jpg" in zf.namelist()
            html = zf.read("report.html").decode("utf-8")
        # missing.jpg reported as failed (output file not found), not bundled
        assert "images/missing.jpg" not in html
        assert "missing.jpg" in html  # appears in the failed list
    finally:
        zip_path.unlink(missing_ok=True)
