"""Earth Engine operations callable from AutoGIS tools.

These helpers are intentionally independent of the chat/provider layer. They
initialize the user's configured local Earth Engine credentials and expose
bounded, JSON-serializable catalog/region operations.
"""
from __future__ import annotations

from typing import Any

from .gee_credentials import initialize_earth_engine, get_gee_config


def _ee():
    ok, message = initialize_earth_engine()
    if not ok:
        raise RuntimeError(message)
    import ee  # type: ignore
    return ee


def tool_gee_image_collection(args: dict[str, Any]) -> dict[str, Any]:
    """Return image-collection metadata and count for a date/region filter."""
    ee = _ee()
    collection_id = str(args.get("collection_id") or "COPERNICUS/S2_SR_HARMONIZED").strip()
    start_date = str(args.get("start_date") or "").strip()
    end_date = str(args.get("end_date") or "").strip()
    bbox = args.get("bbox")
    if not start_date or not end_date:
        raise ValueError("start_date and end_date are required (YYYY-MM-DD).")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("bbox must be [west, south, east, north] in EPSG:4326.")
    west, south, east, north = [float(v) for v in bbox]
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox coordinates are invalid.")
    region = ee.Geometry.Rectangle([west, south, east, north])
    collection = (ee.ImageCollection(collection_id)
                  .filterDate(start_date, end_date)
                  .filterBounds(region))
    count = int(collection.size().getInfo())
    first = None
    if count:
        image = ee.Image(collection.first())
        props = image.toDictionary(["system:index", "system:time_start", "CLOUDY_PIXEL_PERCENTAGE"]).getInfo()
        first = {str(k): v for k, v in props.items()}
    return {
        "provider": "Google Earth Engine",
        "project_id": get_gee_config().get("project_id", ""),
        "collection_id": collection_id,
        "start_date": start_date,
        "end_date": end_date,
        "bbox": [west, south, east, north],
        "image_count": count,
        "first_image": first,
    }


def tool_gee_image_preview(args: dict[str, Any]) -> dict[str, Any]:
    """Return an Earth Engine thumbnail URL for a bounded image preview."""
    ee = _ee()
    image_id = str(args.get("image_id") or "").strip()
    bbox = args.get("bbox")
    bands = args.get("bands") or ["B4", "B3", "B2"]
    if not image_id:
        raise ValueError("image_id is required.")
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("bbox must be [west, south, east, north] in EPSG:4326.")
    west, south, east, north = [float(v) for v in bbox]
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("bbox coordinates are invalid.")
    if not isinstance(bands, (list, tuple)) or not bands or len(bands) > 6:
        raise ValueError("bands must contain between 1 and 6 band names.")
    image = ee.Image(image_id).select([str(b) for b in bands])
    region = ee.Geometry.Rectangle([west, south, east, north])
    params = {"region": region, "dimensions": 1024, "format": "png"}
    if len(bands) >= 3:
        params["bands"] = [str(b) for b in bands[:3]]
        params["min"] = 0
        params["max"] = 3000
    return {
        "provider": "Google Earth Engine",
        "image_id": image_id,
        "thumbnail_url": image.getThumbURL(params),
        "bands": list(bands),
        "bbox": [west, south, east, north],
    }
