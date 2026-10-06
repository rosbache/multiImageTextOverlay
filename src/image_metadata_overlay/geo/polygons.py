"""GeoPackage / polygon layer I/O.

Load vector layers (GeoPackage, GeoJSON, shapefile), reproject polygon
features to EPSG:4326, and perform point-in-polygon lookups used to enrich
image metadata with a polygon field value.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def read_vector_layers(path: str) -> list[dict]:
    """List layers of a GeoPackage (or other vector file).

    Returns a list of dicts ``{"name", "geometry_type"}``.
    """
    import pyogrio
    layers = pyogrio.list_layers(path)
    out = []
    for row in layers:
        # pyogrio returns a numpy array [layer_name, geometry_type]
        name = str(row[0])
        geom_type = str(row[1]) if len(row) > 1 else ""
        out.append({"name": name, "geometry_type": geom_type})
    return out


def read_layer_fields(path: str, layer: str) -> list[str]:
    """Return the non-geometry attribute field names of *layer*."""
    import geopandas as gpd
    gdf = gpd.read_file(path, layer=layer, rows=1)
    return [c for c in gdf.columns if c != gdf.geometry.name]


def load_polygon_layer(path: str, layer: str, field: Optional[str]) -> dict:
    """
    Load a polygon layer and prepare state for the map + point-in-polygon lookups.
    Only polygon/multipolygon features are kept. Coordinates are re-projected to
    EPSG:4326 for Leaflet.
    """
    import geopandas as gpd

    gdf = gpd.read_file(path, layer=layer)
    if gdf.empty:
        raise ValueError(f"Layer '{layer}' has no features.")

    # Keep only polygonal features
    gdf = gdf[gdf.geometry.notna()]
    poly_mask = gdf.geometry.geom_type.isin(("Polygon", "MultiPolygon"))
    gdf = gdf[poly_mask]
    if gdf.empty:
        raise ValueError(f"Layer '{layer}' contains no polygon features.")

    if gdf.crs is None:
        # Assume already lat/lon if no CRS was declared
        logger.warning(f"Layer '{layer}' has no CRS, assuming EPSG:4326")
        gdf = gdf.set_crs(4326)
    gdf = gdf.to_crs(4326)

    # Pick a field. If not provided, use the first non-geometry column.
    if field is None or field == "":
        non_geom_cols = [c for c in gdf.columns if c != gdf.geometry.name]
        field = non_geom_cols[0] if non_geom_cols else ""
    if field and field not in gdf.columns:
        raise ValueError(f"Field '{field}' not found in layer '{layer}'.")

    features_list = []
    geojson_features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        value = "" if not field else ("" if row.get(field) is None else str(row.get(field)))
        features_list.append({"value": value, "geometry": geom})
        geojson_features.append({
            "type": "Feature",
            "properties": {"name": value, "field": field},
            "geometry": geom.__geo_interface__,
        })

    geojson = {"type": "FeatureCollection", "features": geojson_features}
    return {
        "source_path": path,
        "layer": layer,
        "field": field,
        "features": features_list,
        "geojson": geojson,
    }


def lookup_polygon_value(polygon_layer: Optional[dict],
                         lat: Optional[float], lon: Optional[float]) -> Optional[str]:
    """Return the polygon field value containing (lat, lon), or None.

    *polygon_layer* is a state dict as returned by :func:`load_polygon_layer`.
    """
    if lat is None or lon is None or polygon_layer is None:
        return None
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)  # shapely x=lon, y=lat (EPSG:4326)
        for feat in polygon_layer.get("features", []):
            geom = feat.get("geometry")
            if geom is None:
                continue
            try:
                if geom.covers(pt) or geom.contains(pt):
                    return feat.get("value")
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"Polygon lookup failed for ({lat}, {lon}): {e}")
    return None
