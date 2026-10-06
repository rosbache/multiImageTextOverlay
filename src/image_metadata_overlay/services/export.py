"""HTML report export: render report.html and zip it with processed images."""

import logging
import tempfile
import uuid
from pathlib import Path

from image_metadata_overlay.paths import resource_path

logger = logging.getLogger(__name__)


def build_export_zip(ctx: dict) -> Path:
    """
    Render the HTML report and package it with the processed images into a ZIP.
    Runs in a worker thread (via asyncio.to_thread). Returns the ZIP file path.
    """
    import zipfile
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from image_metadata_overlay.core.exif import extract_exif_data

    output_dir = Path(ctx["output_dir"])
    results = ctx.get("results", [])

    # Per-image entries: join job results with the snapshot maps, read lat/lon
    # from the processed files (EXIF is preserved, incl. any staged overrides).
    entries: list[dict] = []
    failed: list[dict] = []
    for r in results:
        fname = r.get("file") or ""
        if not r.get("success"):
            failed.append(r)
            continue
        out_name = r.get("output_file") or fname
        out_path = output_dir / out_name
        if not out_path.is_file():
            failed.append({"file": fname, "success": False,
                           "message": f"output file not found: {out_name}"})
            continue
        loc = (ctx.get("location_map") or {}).get(fname)
        if loc is not None:
            # Staged location override — source EXIF intentionally left untouched
            lat, lon = loc
        else:
            lat = lon = None
            try:
                meta = extract_exif_data(str(out_path), filename=fname)
                lat = meta.get("_lat_decimal")
                lon = meta.get("_lon_decimal")
            except Exception as e:
                logger.warning(f"Could not read EXIF from {out_name} for export: {e}")
        entries.append({
            "filename": fname,
            "output_file": out_name,
            "lat": lat,
            "lon": lon,
            "address": (ctx.get("address_map") or {}).get(fname),
            "chainage": (ctx.get("chainage_map") or {}).get(fname),
            "polygon_value": (ctx.get("polygon_map") or {}).get(fname),
            "edited": (ctx.get("edited_map") or {}).get(fname, False),
        })

    line_info = ctx.get("line")
    polygon_info = ctx.get("polygon_layer")
    settings = ctx.get("settings") or {}
    has_geo = bool(
        line_info or polygon_info or any(e["lat"] is not None for e in entries)
    )

    report_data = {
        "entries": entries,
        "line": line_info,
        "polygon": polygon_info,
    }

    env = Environment(
        loader=FileSystemLoader(str(resource_path("templates"))),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("export_report.html")
    html = template.render(
        project_info=settings.get("PROJECT_INFO") or "",
        created=ctx.get("created") or "",
        source_folder=ctx.get("source_folder") or "",
        entries=entries,
        failed=failed,
        line=line_info,
        polygon_layer=polygon_info,
        has_geo=has_geo,
        report_data=report_data,
    )

    zip_path = Path(tempfile.gettempdir()) / f"report_export_{uuid.uuid4().hex}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.html", html)
        for e in entries:
            zf.write(output_dir / e["output_file"],
                     arcname=f"images/{e['output_file']}")
    logger.info(
        f"Export built: {len(entries)} image(s), {len(failed)} failed/skipped -> {zip_path}"
    )
    return zip_path
