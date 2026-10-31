"""Earth Engine operations callable from AutoGIS tools.

These helpers are intentionally independent of the chat/provider layer. They
initialize the user's configured local Earth Engine credentials and expose
bounded, JSON-serializable catalog/region operations.
"""
from __future__ import annotations

from typing import Any

import json as _gee_json
from .gee_credentials import initialize_earth_engine, get_gee_config, get_oauth_credentials_project
from .config import AutoGISConfig, data_dir as _gee_data_dir


def _ee(override_project: str = ""):
    ok, message = initialize_earth_engine(override_project=override_project)
    if not ok:
        raise RuntimeError(message)
    import ee  # type: ignore
    return ee


def _retry_gee_with_oauth_project(fn):
    """Execute an Earth Engine call; if the configured project lacks permission, retry with the OAuth default project."""
    try:
        return fn()
    except Exception as exc:
        msg = str(exc)
        fb_proj = get_oauth_credentials_project()
        if fb_proj and ("Permission" in msg or "denied" in msg or "not exist" in msg or "403" in msg):
            _ee(override_project=fb_proj)
            AutoGISConfig().gee_project_id = fb_proj
            return fn()
        raise


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


# --- AutoGIS integrated Earth Engine download tools ---
import datetime as _gee_dt
import os as _gee_os
import tempfile as _gee_tempfile
import urllib.request as _gee_urllib
import urllib.parse as _gee_urlparse
import zipfile as _gee_zipfile
from .config import data_dir as _gee_data_dir


def _resolve_boundary_info_threadsafe(place: str, run_on_main=None) -> tuple[list[float] | None, str, dict | None]:
    """Thread-safely inspect QgsProject on the main thread to get bbox and exact polygon GeoJSON for clipping."""
    def _inspect_project():
        try:
            from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsVectorLayer
            proj = QgsProject.instance()
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            place_clean = place.split(",")[0].strip().lower() if place else ""
            best_lyr = None
            for lyr in proj.mapLayers().values():
                if isinstance(lyr, QgsVectorLayer) and lyr.isValid() and lyr.featureCount() > 0 and lyr.geometryType() == 2:
                    lname = lyr.name().lower()
                    if "boundary" in lname:
                        if place_clean and place_clean in lname:
                            best_lyr = lyr
                            break
                        if best_lyr is None:
                            best_lyr = lyr
            if best_lyr is not None:
                ext = best_lyr.extent()
                xform = None
                if best_lyr.crs().isValid() and best_lyr.crs() != wgs84:
                    xform = QgsCoordinateTransform(best_lyr.crs(), wgs84, proj)
                    ext = xform.transformBoundingBox(ext)
                bbox = [
                    round(ext.xMinimum(), 6),
                    round(ext.yMinimum(), 6),
                    round(ext.xMaximum(), 6),
                    round(ext.yMaximum(), 6),
                ]
                poly_json = None
                for feat in best_lyr.getFeatures():
                    geom = feat.geometry()
                    if geom and not geom.isEmpty():
                        if xform is not None:
                            geom.transform(xform)
                        # Simplify slightly if vertex count is huge so GEE getDownloadURL payload stays compact
                        if geom.constGet() and geom.asWkb() and len(geom.asWkb()) > 25000:
                            geom = geom.simplify(0.0005)
                        poly_json = _gee_json.loads(geom.asJson())
                        break
                return bbox, best_lyr.name(), poly_json
        except Exception as err:
            _ = err
        return None, "", None

    if callable(run_on_main):
        return run_on_main(_inspect_project, timeout=15.0)
    return _inspect_project()


def _gee_bbox(args, run_on_main=None):
    raw = args.get("bbox")
    place = str(args.get("place") or "").strip()
    if raw is None:
        if not place:
            raise ValueError("Provide a place name (e.g. Delhi, India) or bbox=[west,south,east,north].")
        proj_bbox, proj_name, _ = _resolve_boundary_info_threadsafe(place, run_on_main=run_on_main)
        if proj_bbox:
            raw, resolved = proj_bbox, proj_name
        else:
            from .live_data_tools import _geocode_nominatim
            hits = _geocode_nominatim(place, with_polygon=False, limit=5)
            if not hits:
                raise RuntimeError("Could not resolve area for " + place)
            best = hits[0]
            bb = best.get("boundingbox")
            if isinstance(bb, list) and len(bb) == 4:
                raw = [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])]
            else:
                lat, lon = float(best.get("lat", 0)), float(best.get("lon", 0))
                raw = [lon - 0.06, lat - 0.06, lon + 0.06, lat + 0.06]
            resolved = str(best.get("display_name") or place)
    else:
        resolved = place or "custom AOI"
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        raise ValueError("bbox must be [west,south,east,north] in EPSG:4326.")
    bbox = [float(v) for v in raw]
    w, s, e, n = bbox
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ValueError("Invalid bbox coordinates.")
    if (e-w)*(n-s) > 4:
        raise ValueError("AOI too large for direct download; use a smaller bbox.")
    return bbox, resolved


def _gee_safe_slug(text):
    value = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(text))
    return value.strip("_")[:70] or "gee_raster"


def _gee_download_and_load(image, args, iface=None, run_on_main=None, name="Earth_Engine_Raster", default_palette=""):
    ee = _ee()
    place = str(args.get("place") or "").strip()
    bbox, area = _gee_bbox(args, run_on_main=run_on_main)
    _, boundary_name, boundary_geojson = _resolve_boundary_info_threadsafe(place, run_on_main=run_on_main)

    span = max(abs(bbox[2] - bbox[0]), abs(bbox[3] - bbox[1]))
    scale = int(args.get("scale") or 30)
    # Prevent giant multi-hundred-MB downloads that freeze GDAL on regional mountain bboxes
    if span > 0.30 and scale < 20:
        scale = 20
    if span > 0.60 and scale < 30:
        scale = 30
    if not 1 <= scale <= 1000:
        raise ValueError("scale must be between 1 and 1000 meters.")
    crs = str(args.get("crs") or "EPSG:4326")
    region = ee.Geometry.Rectangle(bbox)

    # Clip to exact boundary polygon on Google Earth Engine servers and set outside pixels to -9999 NoData
    clipped_to_poly = False
    if isinstance(boundary_geojson, dict) and boundary_geojson.get("type") in ("Polygon", "MultiPolygon"):
        try:
            ee_poly = ee.Geometry(boundary_geojson)
            image = image.toFloat().clip(ee_poly).unmask(-9999)
            clipped_to_poly = True
        except Exception as err:
            _ = err
            image = image.toFloat().clip(region).unmask(-9999)
    else:
        image = image.toFloat().clip(region).unmask(-9999)

    url = _retry_gee_with_oauth_project(
        lambda: image.getDownloadURL({"name": name, "region": region, "scale": scale, "crs": crs, "format": "GEO_TIFF"})
    )
    folder = _gee_os.path.join(_gee_data_dir(), "datasets")
    _gee_os.makedirs(folder, exist_ok=True)
    fd, temp_path = _gee_tempfile.mkstemp(prefix="gee_", suffix=".tmp", dir=folder)
    _gee_os.close(fd)
    output = _gee_os.path.join(folder, _gee_safe_slug(name) + "_" + str(int(_gee_dt.datetime.now().timestamp())) + ".tif")
    try:
        parsed_url = _gee_urlparse.urlparse(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ValueError(f"Invalid Earth Engine download URL scheme: {parsed_url.scheme}")
        req = _gee_urllib.Request(url, headers={"User-Agent":"AutoGIS-Studio/1.0"})
        size = 0
        with _gee_urllib.urlopen(req, timeout=120) as response, open(temp_path, "wb") as out:  # nosec B310
            while True:
                chunk = response.read(1024*1024)
                if not chunk: break
                size += len(chunk)
                if size > 128*1024*1024:
                    raise ValueError("Direct download exceeded 128 MiB. Reduce the AOI or use a task-based export.")
                out.write(chunk)
        if not size: raise RuntimeError("Earth Engine returned an empty file.")
        if _gee_zipfile.is_zipfile(temp_path):
            with _gee_zipfile.ZipFile(temp_path) as zf:
                members = [n for n in zf.namelist() if n.lower().endswith((".tif",".tiff")) and ".." not in n.split("/") and not n.startswith("/")]
                if not members: raise RuntimeError("Earth Engine ZIP contains no GeoTIFF.")
                with zf.open(members[0]) as src, open(output,"wb") as dst:
                    while True:
                        chunk = src.read(1024*1024)
                        if not chunk: break
                        dst.write(chunk)
        else:
            _gee_os.replace(temp_path, output)
        if not _gee_os.path.isfile(output) or _gee_os.path.getsize(output) < 100:
            raise RuntimeError("Downloaded GeoTIFF is missing or invalid.")
        layer_name = str(args.get("layer_name") or name)
        def _load():
            from qgis.core import QgsProject, QgsRasterLayer
            from .advanced_gis_tools import auto_order_project_layers, tool_style_raster_layer
            project = QgsProject.instance()
            # Replace any prior layer with the same name so layers don't pile up
            for old_lyr in list(project.mapLayers().values()):
                if old_lyr.name().strip().lower() == layer_name.strip().lower():
                    project.removeMapLayer(old_lyr.id())
            layer = QgsRasterLayer(output, layer_name, "gdal")
            if not layer.isValid():
                raise RuntimeError("Downloaded file is not a valid QGIS raster: " + output)
            prov = layer.dataProvider()
            if prov is not None:
                for b in range(1, layer.bandCount() + 1):
                    prov.setNoDataValue(b, -9999.0)
                    prov.setUseSourceNoDataValue(b, True)
            project.addMapLayer(layer)
            if default_palette:
                tool_style_raster_layer(iface, {"layer": layer.id(), "palette": default_palette})
            auto_order_project_layers(iface, focus_place=place)
            if iface and iface.mapCanvas():
                iface.mapCanvas().setExtent(layer.extent())
                iface.mapCanvas().refresh()
            return {"layer_id":layer.id(),"layer_name":layer.name(),"width":layer.width(),
                    "height":layer.height(),"bands":layer.bandCount(),"crs":layer.crs().authid(),
                    "clipped_to_boundary": clipped_to_poly, "boundary_layer": boundary_name or None}
        loaded = run_on_main(_load, timeout=60) if run_on_main else _load()
        return {"status":"success","provider":"Google Earth Engine","project_id":get_gee_config().get("project_id",""),
                "area":area,"bbox":bbox,"scale_m":scale,"output_crs":crs,"file_path":output,
                "file_size_bytes":_gee_os.path.getsize(output),**loaded}
    finally:
        try:
            if _gee_os.path.exists(temp_path): _gee_os.remove(temp_path)
        except OSError: pass


def tool_gee_download_dem(args, iface=None, run_on_main=None):
    ee = _ee()
    dataset = str(args.get("dataset_id") or "NASA/NASADEM_HGT/001")
    band = str(args.get("band") or "elevation")
    place = str(args.get("place") or "")
    payload = dict(args)
    payload["crs"] = str(args.get("crs") or ("EPSG:32643" if "delhi" in place.lower() else "EPSG:4326"))
    payload["layer_name"] = args.get("layer_name") or (place + " DEM").strip() or "Earth Engine DEM"
    image = ee.Image(dataset).select([band])
    out = _gee_download_and_load(image, payload, iface, run_on_main, _gee_safe_slug(payload["layer_name"]), default_palette="terrain")
    out.update({"dataset_id":dataset,"band":band,"product":"DEM"})
    return out


def tool_gee_export_image(args, iface=None, run_on_main=None):
    ee = _ee()
    image_id = str(args.get("image_id") or "").strip()
    if not image_id: raise ValueError("image_id is required.")
    image = ee.Image(image_id)
    bands = args.get("bands")
    if bands:
        if not isinstance(bands,(list,tuple)) or not 1 <= len(bands) <= 12:
            raise ValueError("bands must contain 1-12 band names.")
        image = image.select([str(b) for b in bands])
    name = str(args.get("layer_name") or image_id.replace("/","_"))
    out = _gee_download_and_load(image,args,iface,run_on_main,_gee_safe_slug(name))
    out.update({"image_id":image_id,"bands":list(bands) if bands else "all"})
    return out


def tool_gee_compute_index(args, iface=None, run_on_main=None):
    ee = _ee()
    index = str(args.get("index") or "NDVI").upper()
    pairs = {"NDVI":("B8","B4"),"NDWI":("B3","B8"),"NDBI":("B11","B8")}
    if index not in pairs: raise ValueError("index must be NDVI, NDWI, or NDBI.")
    bbox, _ = _gee_bbox(args, run_on_main=run_on_main)
    today = _gee_dt.date.today()
    start = str(args.get("start_date") or (today-_gee_dt.timedelta(days=365)).isoformat())
    end = str(args.get("end_date") or today.isoformat())
    if start >= end: raise ValueError("start_date must be earlier than end_date.")
    region = ee.Geometry.Rectangle(bbox)
    max_cloud = float(args.get("max_cloud_cover", 30))
    collection = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterDate(start,end)
                  .filterBounds(region).filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", max_cloud)))
    count = int(_retry_gee_with_oauth_project(lambda: collection.size().getInfo()))
    if count == 0 and max_cloud < 50:
        collection = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterDate(start,end)
                      .filterBounds(region).filter(ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", 50.0)))
        count = int(_retry_gee_with_oauth_project(lambda: collection.size().getInfo()))
    if count == 0: raise RuntimeError("No Sentinel-2 images found for this area/date range; expand the date range or cloud threshold.")
    a,b = pairs[index]
    image = collection.median().normalizedDifference([a,b]).rename(index)
    payload = dict(args); payload["bbox"] = bbox; payload["scale"] = int(args.get("scale") or 10)
    payload["layer_name"] = args.get("layer_name") or (index + " " + str(args.get("place") or "AOI"))
    palette_map = {"NDVI": "rdylgn", "NDWI": "blues", "NDBI": "reds"}
    out = _gee_download_and_load(
        image, payload, iface, run_on_main, _gee_safe_slug(payload["layer_name"]),
        default_palette=palette_map.get(index, "rdylgn")
    )
    out.update({"product":index,"dataset_id":"COPERNICUS/S2_SR_HARMONIZED","image_count":count,
                "start_date":start,"end_date":end,"band_math":f"normalizedDifference({a}, {b})"})
    return out
