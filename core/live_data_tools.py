from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsSettings,
    QgsVectorLayer,
)

from .config import data_dir, log_info, log_warn

USER_AGENT = "AutoGIS-Studio-QGIS/2.0 (Geospatial AI Copilot)"

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

OSM_THEME_FILTERS: dict[str, list[str]] = {
    "buildings": ['nwr["building"]'],
    "roads": ['way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|service)$"]'],
    "highways": ['way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]'],
    "rivers": ['way["waterway"~"^(river|stream|canal|drain)$"]'],
    "water": ['nwr["natural"="water"]', 'nwr["waterway"="riverbank"]', 'nwr["landuse"="reservoir"]'],
    "railways": ['way["railway"~"^(rail|light_rail|subway|tram)$"]'],
    "landuse": ['nwr["landuse"]'],
    "parks": ['nwr["leisure"~"^(park|garden|nature_reserve)$"]', 'nwr["boundary"="national_park"]'],
    "hospitals": ['nwr["amenity"~"^(hospital|clinic|doctors)$"]'],
    "schools": ['nwr["amenity"~"^(school|university|college|kindergarten)$"]'],
    "amenities": ['nwr["amenity"]'],
    "shops": ['nwr["shop"]'],
    "power": ['nwr["power"~"^(line|substation|plant|generator|tower)$"]'],
    "boundaries": ['relation["boundary"="administrative"]'],
}


def _datasets_dir() -> str:
    folder = os.path.join(data_dir(), "datasets")
    os.makedirs(folder, exist_ok=True)
    return folder


def _safe_slug(text: str) -> str:
    clean = "".join(ch if ch.isalnum() else "_" for ch in str(text or "layer").strip())
    while "__" in clean:
        clean = clean.replace("__", "_")
    return clean.strip("_")[:42] or "layer"


def _http_get_json(url: str, timeout: int = 25) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _canvas_bbox_wgs84(iface) -> list[float] | None:
    if not iface or not iface.mapCanvas():
        return None
    canvas = iface.mapCanvas()
    ext = canvas.extent()
    if ext.isEmpty():
        return None
    src_crs = canvas.mapSettings().destinationCrs()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    if src_crs.isValid() and src_crs != wgs84:
        xform = QgsCoordinateTransform(src_crs, wgs84, QgsProject.instance())
        ext = xform.transformBoundingBox(ext)
    return [
        round(ext.xMinimum(), 6),
        round(ext.yMinimum(), 6),
        round(ext.xMaximum(), 6),
        round(ext.yMaximum(), 6),
    ]


def _geocode_nominatim(query: str, with_polygon: bool = True, limit: int = 5) -> list[dict]:
    params = {
        "q": query,
        "format": "jsonv2",
        "polygon_geojson": "1" if with_polygon else "0",
        "addressdetails": "1",
        "limit": str(limit),
    }
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(params)
    try:
        res = _http_get_json(url, timeout=20)
        if isinstance(res, list) and res:
            return res
    except Exception as exc:
        log_warn(f"Nominatim search warning for '{query}': {exc}")

    # Fallback to Komoot Photon geocoder
    photon_url = "https://photon.komoot.io/api/?" + urllib.parse.urlencode({"q": query, "limit": str(limit)})
    try:
        data = _http_get_json(photon_url, timeout=20)
        feats = data.get("features") or []
        out = []
        for f in feats:
            props = f.get("properties") or {}
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or [0, 0]
            ext = props.get("extent")  # [minlon, maxlat, maxlon, minlat]
            bbox = [ext[1], ext[3], ext[0], ext[2]] if isinstance(ext, list) and len(ext) == 4 else [
                coords[1] - 0.05, coords[1] + 0.05, coords[0] - 0.05, coords[0] + 0.05
            ]
            out.append({
                "display_name": ", ".join(str(props.get(k)) for k in ("name", "city", "state", "country") if props.get(k)),
                "lat": str(coords[1]),
                "lon": str(coords[0]),
                "boundingbox": [str(b) for b in bbox],
                "geojson": geom,
                "type": props.get("osm_value", "place"),
            })
        return out
    except Exception as exc:
        log_warn(f"Photon geocoder warning for '{query}': {exc}")
        return []


def _resolve_place_bbox_wgs84(place: str) -> tuple[list[float] | None, str]:
    hits = _geocode_nominatim(place, with_polygon=False, limit=3)
    if not hits:
        return None, ""
    best = hits[0]
    bb = best.get("boundingbox")
    if isinstance(bb, list) and len(bb) == 4:
        # Nominatim boundingbox is [south_lat, north_lat, west_lon, east_lon]
        south, north, west, east = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
        return [west, south, east, north], str(best.get("display_name") or place)
    lat, lon = float(best.get("lat", 0)), float(best.get("lon", 0))
    return [lon - 0.05, lat - 0.05, lon + 0.05, lat + 0.05], str(best.get("display_name") or place)


# ============================================================================
# 1. PLACE BOUNDARY & GEOCODING DOWNLOADER (Nominatim / Photon)
# ============================================================================

def tool_fetch_place_boundary(iface, args: dict) -> dict:
    place = str(args.get("place") or "").strip()
    if not place:
        return {"error": "'place' name or address is required (e.g. 'Jaipur', 'Rajasthan', 'Bikaner district')."}

    geometry_preference = str(args.get("geometry_type") or "boundary").strip().lower()
    add_to_map = bool(args.get("add_to_map", True))
    zoom = bool(args.get("zoom", True))

    hits = _geocode_nominatim(place, with_polygon=(geometry_preference != "point"), limit=5)
    if not hits:
        return {"error": f"Could not find location or boundary for '{place}'."}

    # Prefer a hit that has a Polygon/MultiPolygon if user asked for a boundary
    chosen = hits[0]
    if geometry_preference != "point":
        for h in hits:
            gj = h.get("geojson") or {}
            if gj.get("type") in ("Polygon", "MultiPolygon"):
                chosen = h
                break

    display_name = str(chosen.get("display_name") or place)
    lat = float(chosen.get("lat") or 0.0)
    lon = float(chosen.get("lon") or 0.0)
    bb = chosen.get("boundingbox") or [lat - 0.05, lat + 0.05, lon - 0.05, lon + 0.05]
    bbox_wgs84 = [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])]

    gj_geom = chosen.get("geojson")
    if not isinstance(gj_geom, dict) or geometry_preference == "point":
        gj_geom = {"type": "Point", "coordinates": [lon, lat]}

    layer_name = str(args.get("layer_name") or f"{place.title()} Boundary").strip()
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": place,
                    "display_name": display_name,
                    "osm_type": str(chosen.get("osm_type") or ""),
                    "osm_id": str(chosen.get("osm_id") or ""),
                    "category": str(chosen.get("category") or chosen.get("type") or ""),
                    "lat": lat,
                    "lon": lon,
                },
                "geometry": gj_geom,
            }
        ],
    }

    out_file = os.path.join(_datasets_dir(), f"boundary_{_safe_slug(place)}_{int(time.time())}.geojson")
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(feature_collection, fh, ensure_ascii=False)

    layer_id = None
    if add_to_map:
        vlyr = QgsVectorLayer(out_file, layer_name, "ogr")
        if vlyr.isValid():
            # Style polygon boundaries with a crisp cyan outline and subtle fill
            from .gis_tools import _tool_style_vector_layer
            QgsProject.instance().addMapLayer(vlyr)
            _tool_style_vector_layer(iface, {
                "layer": vlyr.id(),
                "style_type": "single",
                "color": "#00BBF9",
                "outline_color": "#0284C7",
                "opacity": 0.35 if gj_geom.get("type") in ("Polygon", "MultiPolygon") else 0.9,
            })
            layer_id = vlyr.id()
            if zoom and iface and iface.mapCanvas():
                ext = iface.mapCanvas().mapSettings().layerToMapCoordinates(vlyr, vlyr.extent())
                if not ext.isEmpty():
                    ext.scale(1.15)
                    iface.mapCanvas().setExtent(ext)
                    iface.mapCanvas().refresh()

    return {
        "status": "loaded" if layer_id else "geocoded",
        "place": place,
        "display_name": display_name,
        "geometry_type": gj_geom.get("type"),
        "center_lon_lat": [lon, lat],
        "bbox_wgs84": bbox_wgs84,
        "layer_id": layer_id,
        "layer_name": layer_name,
        "file_path": out_file,
    }


# ============================================================================
# 2. LIVE OPENSTREETMAP (OVERPASS API) FEATURE EXTRACTOR
# ============================================================================

def _osm_elements_to_geojson(elements: list[dict]) -> dict[str, list[dict]]:
    """Convert Overpass JSON elements (with `out body geom;`) into Point, LineString, and Polygon GeoJSON features."""
    points: list[dict] = []
    lines: list[dict] = []
    polygons: list[dict] = []

    area_keys = {"building", "landuse", "natural", "leisure", "amenity", "shop", "tourism", "Boundary", "boundary", "historic", "man_made", "aeroway"}

    for el in elements:
        el_type = el.get("type")
        tags = el.get("tags") or {}
        if not tags and el_type == "node":
            continue

        props: dict[str, Any] = {
            "osm_id": el.get("id"),
            "osm_type": el_type,
            "name": tags.get("name") or tags.get("name:en") or "",
        }
        for k, v in list(tags.items())[:25]:
            if k not in props:
                props[k] = v

        if el_type == "node" and "lat" in el and "lon" in el:
            points.append({
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": [float(el["lon"]), float(el["lat"])]},
            })
        elif el_type == "way" and "geometry" in el:
            coords = [[float(pt["lon"]), float(pt["lat"])] for pt in el["geometry"] if "lon" in pt and "lat" in pt]
            if len(coords) < 2:
                continue
            is_closed = len(coords) >= 4 and coords[0] == coords[-1]
            is_area = is_closed and (any(k in tags for k in area_keys) or tags.get("area") == "yes")
            if is_area:
                polygons.append({
                    "type": "Feature",
                    "properties": props,
                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                })
            else:
                lines.append({
                    "type": "Feature",
                    "properties": props,
                    "geometry": {"type": "LineString", "coordinates": coords},
                })
        elif el_type == "relation" and "members" in el:
            outer_rings = []
            for m in el.get("members") or []:
                if m.get("type") == "way" and m.get("geometry"):
                    ring = [[float(pt["lon"]), float(pt["lat"])] for pt in m["geometry"] if "lon" in pt and "lat" in pt]
                    if len(ring) >= 4 and ring[0] == ring[-1]:
                        outer_rings.append(ring)
                    elif len(ring) >= 2:
                        lines.append({
                            "type": "Feature",
                            "properties": props,
                            "geometry": {"type": "LineString", "coordinates": ring},
                        })
            if outer_rings:
                polygons.append({
                    "type": "Feature",
                    "properties": props,
                    "geometry": {"type": "MultiPolygon", "coordinates": [[r] for r in outer_rings]},
                })

    return {"polygons": polygons, "lines": lines, "points": points}


def tool_fetch_osm_features(iface, args: dict) -> dict:
    theme = str(args.get("category") or args.get("theme") or "buildings").strip().lower()
    place = str(args.get("place") or "").strip()
    bbox = args.get("bbox")
    osm_key = str(args.get("osm_key") or args.get("custom_tag") or "").strip()
    osm_value = str(args.get("osm_value") or "").strip()
    max_features = max(50, min(int(args.get("limit") or args.get("max_features") or 2000), 10000))

    # 1. Resolve bounding box [xmin, ymin, xmax, ymax] in EPSG:4326
    resolved_place = ""
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        bbox_4326 = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
    elif place:
        bbox_4326, resolved_place = _resolve_place_bbox_wgs84(place)
        if not bbox_4326:
            return {"error": f"Could not resolve bounding box for place '{place}'."}
    else:
        bbox_4326 = _canvas_bbox_wgs84(iface)
        if not bbox_4326:
            return {"error": "Please provide a 'place' name (e.g. 'Jaipur') or zoom the map to a city."}
        if abs(bbox_4326[2] - bbox_4326[0]) > 2.0 or abs(bbox_4326[3] - bbox_4326[1]) > 2.0:
            return {"error": "Current map view is too wide. Please specify a city/area name in 'place' (e.g. 'Jaipur', 'New Delhi') or zoom in closer."}

    west, south, east, north = bbox_4326
    span_lon = abs(east - west)
    span_lat = abs(north - south)
    if span_lon > 0.45 or span_lat > 0.45:
        cx, cy = (west + east) / 2.0, (south + north) / 2.0
        half_lon = min(span_lon / 2.0, 0.18)
        half_lat = min(span_lat / 2.0, 0.18)
        west, south, east, north = cx - half_lon, cy - half_lat, cx + half_lon, cy + half_lat

    overpass_bbox = f"{south},{west},{north},{east}"

    # 2. Build Overpass QL query
    if osm_key:
        if osm_value and osm_value != "*":
            clauses = [f'nwr["{osm_key}"="{osm_value}"]({overpass_bbox});']
        else:
            clauses = [f'nwr["{osm_key}"]({overpass_bbox});']
        label_stem = f"{osm_key}_{osm_value or 'all'}"
    else:
        filters = OSM_THEME_FILTERS.get(theme)
        if not filters:
            clauses = [f'nwr["{theme}"]({overpass_bbox});']
        else:
            clauses = [f"{flt}({overpass_bbox});" for flt in filters]
        label_stem = theme

    ql = f"[out:json][timeout:14];(\n  " + "\n  ".join(clauses) + f"\n);out body geom {max_features};"

    # 3. Query Overpass mirrors with automatic failover
    raw_data = None
    last_err = ""
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(
                endpoint,
                data=urllib.parse.urlencode({"data": ql}).encode("utf-8"),
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw_data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(raw_data, dict) and "elements" in raw_data:
                break
        except Exception as exc:
            last_err = str(exc)
            continue

    if not isinstance(raw_data, dict) or "elements" not in raw_data:
        return {"error": f"Overpass API query failed: {last_err or 'No response'}"}

    grouped = _osm_elements_to_geojson(raw_data.get("elements") or [])
    total_found = sum(len(v) for v in grouped.values())
    if total_found == 0:
        return {
            "status": "empty",
            "theme": label_stem,
            "bbox_wgs84": [west, south, east, north],
            "message": f"No OpenStreetMap features found for '{label_stem}' in the target area.",
        }

    theme_colors = {
        "buildings": "#F59E0B",
        "roads": "#EF4444",
        "highways": "#DC2626",
        "rivers": "#0EA5E9",
        "water": "#0284C7",
        "railways": "#6366F1",
        "parks": "#10B981",
        "landuse": "#84CC16",
        "hospitals": "#EC4899",
        "schools": "#8B5CF6",
    }
    base_color = theme_colors.get(theme, "#00BBF9")

    loaded_layers = []
    place_tag = f" ({place.title()})" if place else ""
    base_layer_name = str(args.get("layer_name") or f"OSM {label_stem.title()}{place_tag}").strip()

    from .gis_tools import _tool_style_vector_layer

    for geom_family, feats in grouped.items():
        if not feats:
            continue
        suffix = f" ({geom_family.title()})" if sum(1 for v in grouped.values() if v) > 1 else ""
        lname = f"{base_layer_name}{suffix}"
        out_path = os.path.join(_datasets_dir(), f"osm_{_safe_slug(lname)}_{int(time.time())}.geojson")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "features": feats}, fh, ensure_ascii=False)

        vlyr = QgsVectorLayer(out_path, lname, "ogr")
        if vlyr.isValid():
            QgsProject.instance().addMapLayer(vlyr)
            _tool_style_vector_layer(iface, {
                "layer": vlyr.id(),
                "style_type": "single",
                "color": base_color,
                "opacity": 0.78,
            })
            loaded_layers.append({
                "id": vlyr.id(),
                "name": vlyr.name(),
                "geometry": geom_family,
                "feature_count": len(feats),
                "file_path": out_path,
            })

    if loaded_layers and iface and iface.mapCanvas():
        first_lyr = QgsProject.instance().mapLayer(loaded_layers[0]["id"])
        if first_lyr:
            ext = iface.mapCanvas().mapSettings().layerToMapCoordinates(first_lyr, first_lyr.extent())
            if not ext.isEmpty():
                ext.scale(1.1)
                iface.mapCanvas().setExtent(ext)
        iface.mapCanvas().refresh()

    return {
        "status": "loaded",
        "theme": label_stem,
        "place": resolved_place or place or "map_canvas",
        "bbox_wgs84": [round(west, 5), round(south, 5), round(east, 5), round(north, 5)],
        "total_features": total_found,
        "layers": loaded_layers,
    }


# ============================================================================
# 3. LIVE ROAD NETWORK ROUTING (OSRM Public API)
# ============================================================================

def tool_compute_road_route(iface, args: dict) -> dict:
    origin = args.get("origin")
    destination = args.get("destination")
    profile = str(args.get("profile") or "driving").strip().lower()
    if profile not in ("driving", "walking", "cycling"):
        profile = "driving"

    def _resolve_pt(val: Any) -> tuple[list[float] | None, str]:
        if isinstance(val, (list, tuple)) and len(val) == 2:
            return [float(val[0]), float(val[1])], f"{val[0]},{val[1]}"
        if isinstance(val, str) and val.strip():
            hits = _geocode_nominatim(val.strip(), with_polygon=False, limit=1)
            if hits:
                return [float(hits[0]["lon"]), float(hits[0]["lat"])], str(hits[0].get("display_name") or val)
        return None, ""

    orig_pt, orig_label = _resolve_pt(origin)
    dest_pt, dest_label = _resolve_pt(destination)
    if not orig_pt or not dest_pt:
        return {"error": "Could not resolve 'origin' and 'destination' coordinates or place names."}

    osrm_profile = {"driving": "driving", "walking": "foot", "cycling": "bike"}[profile]
    coords_str = f"{orig_pt[0]},{orig_pt[1]};{dest_pt[0]},{dest_pt[1]}"
    url = f"https://router.project-osrm.org/route/v1/{osrm_profile}/{coords_str}?overview=full&geometries=geojson&steps=false"

    try:
        data = _http_get_json(url, timeout=25)
    except Exception as exc:
        return {"error": f"OSRM routing service error: {exc}"}

    routes = data.get("routes") or []
    if not routes:
        return {"error": "No road route found between origin and destination."}

    best = routes[0]
    dist_km = round(float(best.get("distance") or 0.0) / 1000.0, 2)
    dur_min = round(float(best.get("duration") or 0.0) / 60.0, 1)
    geom = best.get("geometry")

    layer_name = str(args.get("layer_name") or f"Route: {origin} to {destination} ({dist_km} km)").strip()
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "origin": orig_label,
                    "destination": dest_label,
                    "profile": profile,
                    "distance_km": dist_km,
                    "duration_min": dur_min,
                },
                "geometry": geom,
            }
        ],
    }

    out_path = os.path.join(_datasets_dir(), f"route_{_safe_slug(layer_name)}_{int(time.time())}.geojson")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False)

    vlyr = QgsVectorLayer(out_path, layer_name, "ogr")
    layer_id = None
    if vlyr.isValid():
        from .gis_tools import _tool_style_vector_layer
        QgsProject.instance().addMapLayer(vlyr)
        _tool_style_vector_layer(iface, {
            "layer": vlyr.id(),
            "style_type": "single",
            "color": "#2563EB",
            "size": 1.8,
            "opacity": 0.95,
        })
        layer_id = vlyr.id()
        if iface and iface.mapCanvas():
            ext = iface.mapCanvas().mapSettings().layerToMapCoordinates(vlyr, vlyr.extent())
            if not ext.isEmpty():
                ext.scale(1.15)
                iface.mapCanvas().setExtent(ext)
                iface.mapCanvas().refresh()

    return {
        "status": "routed",
        "origin": orig_label,
        "destination": dest_label,
        "profile": profile,
        "distance_km": dist_km,
        "duration_minutes": dur_min,
        "layer_id": layer_id,
        "layer_name": layer_name,
        "file_path": out_path,
    }


# ============================================================================
# 4. MICROSOFT PLANETARY COMPUTER STAC (30m DEM, Sentinel-2, Esri LULC)
# ============================================================================

STAC_DATASETS: dict[str, tuple[str, str, str]] = {
    "dem": ("cop-dem-glo-30", "data", "Copernicus 30m DEM Elevation"),
    "elevation": ("cop-dem-glo-30", "data", "Copernicus 30m DEM Elevation"),
    "sentinel2": ("sentinel-2-l2a", "visual", "Sentinel-2 True Color (10m)"),
    "lulc": ("io-lulc-annual-v02", "data", "Esri 10m Land Cover (LULC)"),
}


def tool_fetch_stac_earth_data(iface, args: dict) -> dict:
    dataset_key = str(args.get("dataset") or "dem").strip().lower()
    place = str(args.get("place") or "").strip()
    bbox = args.get("bbox")
    max_cloud = float(args.get("max_cloud_cover") if args.get("max_cloud_cover") is not None else 15.0)

    if dataset_key in STAC_DATASETS:
        collection, asset_key, label_prefix = STAC_DATASETS[dataset_key]
    else:
        collection = dataset_key
        asset_key = str(args.get("asset_key") or "data")
        label_prefix = f"STAC {collection}"

    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        bbox_4326 = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
    elif place:
        bbox_4326, _ = _resolve_place_bbox_wgs84(place)
        if not bbox_4326:
            return {"error": f"Could not resolve location '{place}'."}
    else:
        bbox_4326 = _canvas_bbox_wgs84(iface)
        if not bbox_4326:
            return {"error": "Provide a 'place' name or 'bbox' [xmin, ymin, xmax, ymax]."}

    search_payload: dict[str, Any] = {
        "collections": [collection],
        "bbox": bbox_4326,
        "limit": 5,
    }
    if collection == "sentinel-2-l2a":
        search_payload["query"] = {"eo:cloud_cover": {"lt": max_cloud}}

    req = urllib.request.Request(
        "https://planetarycomputer.microsoft.com/api/stac/v1/search",
        data=json.dumps(search_payload).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            stac_res = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        return {"error": f"Planetary Computer STAC search error: {exc}"}

    features = stac_res.get("features") or []
    if not features:
        return {"error": f"No STAC items found for collection '{collection}' in bbox {bbox_4326}."}

    item = features[0]
    item_id = item.get("id", "item")
    assets = item.get("properties") or {}
    item_assets = item.get("assets") or {}
    asset_obj = item_assets.get(asset_key) or next(
        (v for v in item_assets.values() if "tiff" in str(v.get("type", "")).lower()),
        None,
    )
    if not asset_obj or not asset_obj.get("href"):
        return {"error": f"No GeoTIFF asset found in STAC item '{item_id}'."}

    raw_href = str(asset_obj["href"])
    # Sign URL via Planetary Computer SAS token endpoint
    sign_url = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?" + urllib.parse.urlencode({"href": raw_href})
    try:
        signed_data = _http_get_json(sign_url, timeout=15)
        signed_href = str(signed_data.get("href") or raw_href)
    except Exception:
        signed_href = raw_href

    vsi_uri = f"/vsicurl/{signed_href}"
    place_suffix = f" ({place.title()})" if place else ""
    layer_name = str(args.get("layer_name") or f"{label_prefix}{place_suffix} [{item_id[:18]}]").strip()

    rlayer = QgsRasterLayer(vsi_uri, layer_name, "gdal")
    if not rlayer.isValid():
        return {"error": f"GDAL could not stream COG raster from '{signed_href[:120]}'."}

    QgsProject.instance().addMapLayer(rlayer)
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {
        "status": "streamed_cog_loaded",
        "collection": collection,
        "item_id": item_id,
        "datetime": assets.get("datetime"),
        "cloud_cover": assets.get("eo:cloud_cover"),
        "layer_id": rlayer.id(),
        "layer_name": rlayer.name(),
        "crs": rlayer.crs().authid(),
        "width": rlayer.width(),
        "height": rlayer.height(),
        "bands": rlayer.bandCount(),
    }


# ============================================================================
# 5. SAVED QGIS CONNECTIONS (XYZ, WMS/Bhuvan, WFS, PostGIS)
# ============================================================================

def tool_list_saved_qgis_connections(iface, args: dict) -> dict:
    qs = QgsSettings()
    xyz_list = []
    qs.beginGroup("qgis/connections-xyz")
    for name in qs.childGroups():
        url = qs.value(f"{name}/url", "")
        if url:
            xyz_list.append({"name": name, "url": url, "zmin": qs.value(f"{name}/zmin", 0), "zmax": qs.value(f"{name}/zmax", 19)})
    qs.endGroup()

    wms_list = []
    qs.beginGroup("connections/ows/items/wms/connections/items")
    for name in qs.childGroups():
        url = qs.value(f"{name}/url", "")
        if url:
            wms_list.append({"name": name, "url": url})
    qs.endGroup()

    wfs_list = []
    qs.beginGroup("connections/ows/items/wfs/connections/items")
    for name in qs.childGroups():
        url = qs.value(f"{name}/url", "")
        if url:
            wfs_list.append({"name": name, "url": url})
    qs.endGroup()

    pg_list = []
    qs.beginGroup("PostgreSQL/connections")
    for name in qs.childGroups():
        host = qs.value(f"{name}/host", "")
        db = qs.value(f"{name}/database", "")
        if host or db:
            pg_list.append({"name": name, "host": host, "database": db, "port": qs.value(f"{name}/port", 5432)})
    qs.endGroup()

    return {
        "xyz_tiles": xyz_list,
        "wms_services": wms_list,
        "wfs_services": wfs_list,
        "postgis_databases": pg_list,
    }


def tool_load_saved_qgis_connection(iface, args: dict) -> dict:
    conn_name = str(args.get("connection_name") or "").strip()
    conn_type = str(args.get("connection_type") or "xyz").strip().lower()
    if not conn_name:
        return {"error": "'connection_name' is required. Call 'list_saved_qgis_connections' first to see available names."}

    qs = QgsSettings()
    if conn_type == "xyz":
        qs.beginGroup("qgis/connections-xyz")
        matched = next((g for g in qs.childGroups() if g.lower() == conn_name.lower() or conn_name.lower() in g.lower()), None)
        if not matched:
            qs.endGroup()
            return {"error": f"Saved XYZ connection '{conn_name}' not found."}
        url = qs.value(f"{matched}/url", "")
        zmin = qs.value(f"{matched}/zmin", 0)
        zmax = qs.value(f"{matched}/zmax", 19)
        qs.endGroup()
        encoded_url = urllib.parse.quote(str(url), safe=":/?=&{}")
        uri = f"type=xyz&url={encoded_url}&zmin={zmin}&zmax={zmax}"
        rlayer = QgsRasterLayer(uri, matched, "wms")
        if not rlayer.isValid():
            return {"error": f"Could not load XYZ connection '{matched}'."}
        QgsProject.instance().addMapLayer(rlayer)
        return {"status": "loaded", "type": "xyz", "name": matched, "layer_id": rlayer.id()}

    return {"error": f"Unsupported connection_type '{conn_type}'. Currently supports 'xyz'."}
