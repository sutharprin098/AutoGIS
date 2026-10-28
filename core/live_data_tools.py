from __future__ import annotations

import concurrent.futures
import json
import math
import os
import re
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

USER_AGENT = "AutoGIS-Studio/1.0 (+https://autogis.princesite.in/ - contact: sutharprince098@gmail.com)"

# Global public Overpass API mirrors
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

GEOCODE_ENDPOINTS = [
    "https://nominatim.openstreetmap.org/search",
    "https://photon.komoot.io/api/",
]

OSM_THEME_FILTERS: dict[str, list[str]] = {
    "buildings": ['way["building"]', 'relation["building"]'],
    "roads": ['way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified)$"]'],
    "major_roads": ['way["highway"~"^(motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link)$"]'],
    "highways": ['way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]'],
    "rivers": ['way["waterway"~"^(river|stream|canal|drain)$"]'],
    "water": [
        'way["natural"="water"]',
        'relation["natural"="water"]',
        'way["waterway"="riverbank"]',
        'way["water"]',
        'relation["water"]',
        'way["landuse"="reservoir"]',
        'relation["landuse"="reservoir"]',
    ],
    "railways": ['way["railway"~"^(rail|light_rail|subway|tram)$"]'],
    "landuse": ['way["landuse"]', 'relation["landuse"]'],
    "parks": [
        'way["leisure"~"^(park|garden|nature_reserve)$"]',
        'relation["leisure"~"^(park|garden|nature_reserve)$"]',
        'relation["boundary"="national_park"]',
    ],
    "hospitals": ['nwr["amenity"~"^(hospital|clinic|doctors)$"]'],
    "schools": ['nwr["amenity"~"^(school|university|college|kindergarten)$"]'],
    "amenities": ['nwr["amenity"]'],
    "shops": ['nwr["shop"]'],
    "power": ['way["power"~"^(line|substation|plant)$"]', 'node["power"~"^(tower|substation|generator)$"]'],
    "boundary": ['relation["boundary"="administrative"]'],
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


def _http_get_json(url: str, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _canvas_bbox_wgs84(iface) -> list[float] | None:
    # First check if there is already a boundary or vector layer in the project with a valid extent
    try:
        proj = QgsProject.instance()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        for lyr in proj.mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and lyr.isValid() and lyr.featureCount() > 0:
                if "boundary" in lyr.name().lower():
                    ext = lyr.extent()
                    if not ext.isEmpty():
                        if lyr.crs().isValid() and lyr.crs() != wgs84:
                            xform = QgsCoordinateTransform(lyr.crs(), wgs84, proj)
                            ext = xform.transformBoundingBox(ext)
                        return [
                            round(ext.xMinimum(), 6),
                            round(ext.yMinimum(), 6),
                            round(ext.xMaximum(), 6),
                            round(ext.yMaximum(), 6),
                        ]
    except Exception:
        pass

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
    for base in GEOCODE_ENDPOINTS:
        url = f"{base}?" + urllib.parse.urlencode(params)
        try:
            res = _http_get_json(url, timeout=12)
            if isinstance(res, list) and res:
                return res
        except Exception as exc:
            log_warn(f"Geocoder warning ({base}) for '{query}': {exc}")

    # Fallback to Komoot Photon geocoder
    photon_url = "https://photon.komoot.io/api/?" + urllib.parse.urlencode({"q": query, "limit": str(limit)})
    try:
        data = _http_get_json(photon_url, timeout=15)
        feats = data.get("features") or []
        out = []
        for f in feats:
            props = f.get("properties") or {}
            geom = f.get("geometry") or {}
            coords = geom.get("coordinates") or [0, 0]
            ext = props.get("extent")  # [minlon, maxlat, maxlon, minlat]
            bbox = [ext[1], ext[3], ext[0], ext[2]] if isinstance(ext, list) and len(ext) == 4 else [
                coords[1] - 0.06, coords[1] + 0.06, coords[0] - 0.06, coords[0] + 0.06
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
    # Check if a boundary layer for this place is already loaded in QgsProject
    try:
        proj = QgsProject.instance()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        place_clean = place.split(",")[0].strip().lower()
        for lyr in proj.mapLayers().values():
            if isinstance(lyr, QgsVectorLayer) and lyr.isValid() and lyr.featureCount() > 0:
                lname = lyr.name().lower()
                if place_clean and place_clean in lname and "boundary" in lname:
                    ext = lyr.extent()
                    if not ext.isEmpty():
                        if lyr.crs().isValid() and lyr.crs() != wgs84:
                            xform = QgsCoordinateTransform(lyr.crs(), wgs84, proj)
                            ext = xform.transformBoundingBox(ext)
                        return [
                            round(ext.xMinimum(), 6),
                            round(ext.yMinimum(), 6),
                            round(ext.xMaximum(), 6),
                            round(ext.yMaximum(), 6),
                        ], lyr.name()
    except Exception:
        pass

    hits = _geocode_nominatim(place, with_polygon=False, limit=5)
    if not hits:
        return None, ""
    # Prefer city/town/administrative boundary over a giant state/district if multiple hits exist
    best = hits[0]
    for h in hits:
        htype = str(h.get("type") or h.get("addresstype") or "").lower()
        if htype in ("city", "town", "municipality", "village", "suburb", "administrative"):
            bb = h.get("boundingbox")
            if isinstance(bb, list) and len(bb) == 4:
                span = max(abs(float(bb[1]) - float(bb[0])), abs(float(bb[3]) - float(bb[2])))
                if 0.01 <= span <= 0.45:
                    best = h
                    break

    bb = best.get("boundingbox")
    if isinstance(bb, list) and len(bb) == 4:
        south, north, west, east = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
        return [west, south, east, north], str(best.get("display_name") or place)
    lat, lon = float(best.get("lat", 0)), float(best.get("lon", 0))
    return [lon - 0.06, lat - 0.06, lon + 0.06, lat + 0.06], str(best.get("display_name") or place)


# ============================================================================
# 1. PLACE BOUNDARY & GEOCODING DOWNLOADER (Nominatim & Photon)
# ============================================================================

def tool_fetch_place_boundary(iface, args: dict, run_on_main=None) -> dict:
    place = str(args.get("place") or "").strip()
    if not place:
        return {"error": "'place' name or address is required (e.g. 'Udaipur', 'Jaipur', 'Rajasthan')."}

    geometry_preference = str(args.get("geometry_type") or "boundary").strip().lower()
    add_to_map = bool(args.get("add_to_map", True))
    zoom = bool(args.get("zoom", True))

    hits = _geocode_nominatim(place, with_polygon=(geometry_preference != "point"), limit=5)
    if not hits:
        return {"error": f"Could not find location or boundary for '{place}'."}

    chosen = hits[0]
    if geometry_preference != "point":
        # Prefer city/municipality polygon over huge district if available
        poly_hits = [h for h in hits if isinstance(h.get("geojson"), dict) and h["geojson"].get("type") in ("Polygon", "MultiPolygon")]
        if poly_hits:
            chosen = poly_hits[0]
            for h in poly_hits:
                bb = h.get("boundingbox")
                if isinstance(bb, list) and len(bb) == 4:
                    span = max(abs(float(bb[1]) - float(bb[0])), abs(float(bb[3]) - float(bb[2])))
                    if 0.02 <= span <= 0.45:
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

    def _load_on_main() -> str | None:
        if not add_to_map:
            return None
        vlyr = QgsVectorLayer(out_file, layer_name, "ogr")
        if not vlyr.isValid():
            return None
        from .gis_tools import _PROCESSING_LAYER_REFS, _tool_style_vector_layer
        _PROCESSING_LAYER_REFS.append(vlyr)
        QgsProject.instance().addMapLayer(vlyr)
        _tool_style_vector_layer(iface, {
            "layer": vlyr.id(),
            "style_type": "single",
            "color": "#00BBF9",
            "outline_color": "#0284C7",
            "opacity": 0.30 if gj_geom.get("type") in ("Polygon", "MultiPolygon") else 0.9,
        })
        if zoom and iface and iface.mapCanvas():
            ext = iface.mapCanvas().mapSettings().layerToMapCoordinates(vlyr, vlyr.extent())
            if not ext.isEmpty():
                ext.scale(1.15)
                iface.mapCanvas().setExtent(ext)
                iface.mapCanvas().refresh()
        return vlyr.id()

    layer_id = run_on_main(_load_on_main) if callable(run_on_main) else _load_on_main()

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

def _stitch_osm_rings(way_segments: list[list[list[float]]]) -> list[list[list[float]]]:
    """Stitch connected OSM relation way segments into closed polygon rings."""
    rings: list[list[list[float]]] = []
    open_runs: list[list[list[float]]] = []

    for seg in way_segments:
        if len(seg) >= 4 and seg[0] == seg[-1]:
            rings.append(seg)
        elif len(seg) >= 2:
            open_runs.append([list(pt) for pt in seg])

    while open_runs:
        current = open_runs.pop(0)
        changed = True
        while changed and (len(current) < 4 or current[0] != current[-1]):
            changed = False
            tail = current[-1]
            head = current[0]
            for idx, cand in enumerate(open_runs):
                if cand[0] == tail:
                    current.extend(cand[1:])
                    open_runs.pop(idx)
                    changed = True
                    break
                if cand[-1] == tail:
                    current.extend( reversed(cand[:-1]))
                    open_runs.pop(idx)
                    changed = True
                    break
                if cand[-1] == head:
                    current = cand[:-1] + current
                    open_runs.pop(idx)
                    changed = True
                    break
                if cand[0] == head:
                    current = list(reversed(cand[1:])) + current
                    open_runs.pop(idx)
                    changed = True
                    break
        if len(current) >= 4:
            if current[0] != current[-1]:
                current.append(list(current[0]))
            rings.append(current)

    return rings


def _osm_elements_to_geojson(elements: list[dict], theme: str = "") -> dict[str, list[dict]]:
    """Convert Overpass JSON elements (`out geom;`) into Polygon, LineString, and Point GeoJSON features."""
    points: list[dict] = []
    lines: list[dict] = []
    polygons: list[dict] = []

    area_keys = {
        "building", "landuse", "natural", "leisure", "amenity", "shop",
        "tourism", "boundary", "historic", "man_made", "aeroway", "water",
    }
    linear_keys = {"highway", "railway", "barrier"}
    force_polygon_themes = {"water", "buildings", "landuse", "parks", "boundary", "boundaries"}
    force_line_themes = {"roads", "major_roads", "highways", "rivers", "railways"}

    # Track ways that belong to relations so we don't duplicate outer rings as standalone lines
    in_relations: set[Any] = set()
    for el in elements:
        if el.get("type") == "relation":
            for m in el.get("members") or []:
                if isinstance(m, dict) and m.get("type") == "way":
                    in_relations.add(m.get("ref"))

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
            if theme in force_polygon_themes or theme in force_line_themes:
                continue
            points.append({
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": [float(el["lon"]), float(el["lat"])]},
            })

        elif el_type == "way" and "geometry" in el:
            if el.get("id") in in_relations and not tags:
                continue
            coords = [[float(pt["lon"]), float(pt["lat"])] for pt in el["geometry"] if isinstance(pt, dict) and "lon" in pt and "lat" in pt]
            if len(coords) < 2:
                continue
            is_closed = len(coords) >= 4 and coords[0] == coords[-1]
            has_linear = any(k in tags for k in linear_keys) and tags.get("area") != "yes"
            is_waterway_area = tags.get("waterway") in ("riverbank", "dock", "boatyard")
            is_area = is_closed and (
                is_waterway_area
                or theme in force_polygon_themes
                or (not has_linear and (any(k in tags for k in area_keys) or tags.get("area") == "yes"))
            )
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
            outer_segments: list[list[list[float]]] = []
            inner_segments: list[list[list[float]]] = []
            for m in el.get("members") or []:
                if isinstance(m, dict) and m.get("type") == "way" and m.get("geometry"):
                    seg = [[float(pt["lon"]), float(pt["lat"])] for pt in m["geometry"] if isinstance(pt, dict) and "lon" in pt and "lat" in pt]
                    if len(seg) >= 2:
                        role = str(m.get("role") or "outer").lower()
                        if role == "inner":
                            inner_segments.append(seg)
                        else:
                            outer_segments.append(seg)
            outer_rings = _stitch_osm_rings(outer_segments)
            inner_rings = _stitch_osm_rings(inner_segments)
            if outer_rings:
                if len(outer_rings) == 1:
                    poly_coords = [outer_rings[0]] + inner_rings
                    polygons.append({
                        "type": "Feature",
                        "properties": props,
                        "geometry": {"type": "Polygon", "coordinates": poly_coords},
                    })
                else:
                    polygons.append({
                        "type": "Feature",
                        "properties": props,
                        "geometry": {"type": "MultiPolygon", "coordinates": [[r] for r in outer_rings]},
                    })

    # If user requested a polygon theme (e.g. water, buildings, parks) and we got polygons,
    # omit stray unclosed lines unless there are zero polygons
    if theme in force_polygon_themes and polygons:
        return {"polygons": polygons, "lines": [], "points": []}
    if theme in force_line_themes and lines:
        return {"polygons": [], "lines": lines, "points": []}

    return {"polygons": polygons, "lines": lines, "points": points}


def _parse_custom_tag_clauses(raw_tag: str) -> list[str]:
    """Safely parse any custom_tag format from LLM into valid Overpass QL statements."""
    s = raw_tag.strip().rstrip(";")
    if not s:
        return []
    # If LLM already wrote full Overpass statement like way["natural"="water"] or nwr["shop"]
    if re.match(r"^(node|way|relation|rel|nwr|nw|wr)\s*\[", s):
        return [s if s.endswith(";") else f"{s};"]
    # Strip surrounding brackets if LLM passed ["natural"="water"]
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    # Handle key=value or "key"="value"
    if "=" in s and "~" not in s:
        k, v = s.split("=", 1)
        k = k.strip().strip('"').strip("'")
        v = v.strip().strip('"').strip("'")
        if v in ("*", ""):
            return [f'nwr["{k}"];']
        return [f'nwr["{k}"="{v}"];']
    if "~" in s:
        k, v = s.split("~", 1)
        k = k.strip().strip('"').strip("'")
        v = v.strip().strip('"').strip("'")
        return [f'nwr["{k}"~"{v}"];']
    k = s.strip('"').strip("'")
    return [f'nwr["{k}"];']


def _fetch_single_overpass(endpoint: str, post_bytes: bytes, timeout: float) -> tuple[str, dict]:
    req = urllib.request.Request(
        endpoint,
        data=post_bytes,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not isinstance(data, dict) or "elements" not in data:
        raise ValueError("Invalid Overpass JSON response")
    remark = str(data.get("remark") or "").lower()
    if ("runtime error" in remark or "out of memory" in remark) and not data.get("elements"):
        raise RuntimeError(f"Overpass server remark: {data.get('remark')}")
    return endpoint, data


def _query_overpass_fast(ql: str, timeout: float = 25.0) -> tuple[dict | None, str, str]:
    """Query public Overpass mirrors in parallel with fast-failover race."""
    post_bytes = urllib.parse.urlencode({"data": ql}).encode("utf-8")
    errors: list[str] = []

    # Race public Overpass mirrors in parallel so the fastest responsive mirror wins
    mirrors = list(OVERPASS_ENDPOINTS)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(mirrors))
    futures = {
        executor.submit(_fetch_single_overpass, ep, post_bytes, min(20.0, timeout)): ep
        for ep in mirrors
    }
    try:
        for fut in concurrent.futures.as_completed(futures, timeout=min(22.0, timeout + 2.0)):
            ep = futures[fut]
            try:
                used_ep, data = fut.result()
                executor.shutdown(wait=False, cancel_futures=True)
                return data, used_ep, ""
            except Exception as exc:
                errors.append(f"{ep}: {exc}")
    except Exception as exc:
        errors.append(f"mirror_race: {exc}")
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return None, "", "; ".join(errors[:3])


def tool_fetch_osm_features(iface, args: dict, run_on_main=None) -> dict:
    raw_cat = str(args.get("category") or args.get("theme") or "buildings").strip().lower()
    place = str(args.get("place") or "").strip()
    bbox = args.get("bbox")
    custom_tag = str(args.get("custom_tag") or args.get("osm_key") or "").strip()
    osm_value = str(args.get("osm_value") or "").strip()
    if custom_tag and osm_value and "=" not in custom_tag:
        custom_tag = f"{custom_tag}={osm_value}"

    # Normalize common category aliases
    alias_map = {
        "water_bodies": "water",
        "waterbodies": "water",
        "lakes": "water",
        "river": "rivers",
        "waterways": "rivers",
        "road": "roads",
        "major_roads": "major_roads",
        "highway": "highways",
        "building": "buildings",
        "park": "parks",
        "hospital": "hospitals",
        "school": "schools",
        "railway": "railways",
    }
    theme = alias_map.get(raw_cat, raw_cat)

    # 1. Resolve bounding box [xmin, ymin, xmax, ymax] in EPSG:4326
    resolved_place = ""
    if isinstance(bbox, dict):
        west = float(bbox.get("west", bbox.get("xmin", 0)))
        south = float(bbox.get("south", bbox.get("ymin", 0)))
        east = float(bbox.get("east", bbox.get("xmax", 0)))
        north = float(bbox.get("north", bbox.get("ymax", 0)))
        bbox_4326 = [west, south, east, north]
    elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        bbox_4326 = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
    elif place:
        bbox_4326, resolved_place = _resolve_place_bbox_wgs84(place)
        if not bbox_4326:
            return {"error": f"Could not resolve bounding box for place '{place}'."}
    else:
        if callable(run_on_main):
            bbox_4326 = run_on_main(lambda: _canvas_bbox_wgs84(iface))
        else:
            bbox_4326 = _canvas_bbox_wgs84(iface)
        if not bbox_4326:
            return {"error": "Please provide a 'place' name (e.g. 'Udaipur', 'Jaipur') or zoom the map to a city."}

    west, south, east, north = bbox_4326
    if west > east:
        west, east = east, west
    if south > north:
        south, north = north, south

    # Clamp overly wide district/state bounding boxes to an optimal urban extent (~10-15km)
    # so free public community Overpass servers never get overloaded with 502/timeouts
    span_lon = abs(east - west)
    span_lat = abs(north - south)
    max_span = 0.10 if theme in ("buildings", "roads", "major_roads", "amenities") else 0.16
    cx, cy = (west + east) / 2.0, (south + north) / 2.0
    if span_lon > max_span or span_lat > max_span:
        half_lon = min(span_lon / 2.0, max_span / 2.0)
        half_lat = min(span_lat / 2.0, max_span / 2.0)
        west, south, east, north = cx - half_lon, cy - half_lat, cx + half_lon, cy + half_lat

    overpass_bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"

    # 2. Build clean Overpass QL using bounding box filter
    if custom_tag:
        clauses = _parse_custom_tag_clauses(custom_tag)
        label_stem = _safe_slug(custom_tag)[:24] or theme
    else:
        filters = OSM_THEME_FILTERS.get(theme)
        if not filters:
            clauses = [f'nwr["{theme}"];']
        else:
            clauses = [f"{flt};" for flt in filters]
        label_stem = theme

    ql = f"[out:json][timeout:25][bbox:{overpass_bbox}];(\n  " + "\n  ".join(clauses) + "\n);out geom;"

    # 3. Query Overpass public mirrors in parallel
    raw_data, endpoint_used, err_detail = _query_overpass_fast(ql, timeout=25.0)

    # If public mirrors are overloaded or gave 502/timeout, auto-retry on central urban core
    if not raw_data or not raw_data.get("elements"):
        tight_half = 0.045
        t_w, t_s, t_e, t_n = cx - tight_half, cy - tight_half, cx + tight_half, cy + tight_half
        t_bbox = f"{t_s:.6f},{t_w:.6f},{t_n:.6f},{t_e:.6f}"
        if theme in ("major_roads", "highways", "roads"):
            retry_clauses = ['way["highway"~"^(motorway|trunk|primary)$"];']
        else:
            retry_clauses = clauses
        ql_tight = f"[out:json][timeout:20][bbox:{t_bbox}];(\n  " + "\n  ".join(retry_clauses) + "\n);out geom;"
        tight_data, ep_tight, _ = _query_overpass_fast(ql_tight, timeout=20.0)
        if tight_data and tight_data.get("elements"):
            raw_data = tight_data
            endpoint_used = ep_tight
            west, south, east, north = t_w, t_s, t_e, t_n

    # If a custom_tag query returned 0 or failed and a valid category was also provided, fallback to category filters
    if (raw_data is None or not raw_data.get("elements")) and custom_tag and theme in OSM_THEME_FILTERS:
        clauses = [f"{flt};" for flt in OSM_THEME_FILTERS[theme]]
        ql_fallback = f"[out:json][timeout:25][bbox:{overpass_bbox}];(\n  " + "\n  ".join(clauses) + "\n);out geom;"
        raw_data, endpoint_used, err_detail = _query_overpass_fast(ql_fallback, timeout=25.0)
        label_stem = theme

    if not isinstance(raw_data, dict) or "elements" not in raw_data:
        return {
            "error": (
                f"Overpass public servers are temporarily busy ({err_detail or 'timeout'}). "
                "FREE TIPS for large areas: 1) Zoom your QGIS map canvas to the city center and re-run. "
                "2) For whole administrative boundaries or districts, use fetch_place_boundary."
            )
        }

    grouped = _osm_elements_to_geojson(raw_data.get("elements") or [], theme=theme)
    total_found = sum(len(v) for v in grouped.values())
    if total_found == 0:
        return {
            "status": "empty",
            "theme": label_stem,
            "bbox_wgs84": [round(west, 5), round(south, 5), round(east, 5), round(north, 5)],
            "message": f"No OpenStreetMap features found for '{label_stem}' in the target area.",
        }

    theme_colors = {
        "buildings": "#F59E0B",
        "roads": "#475569",
        "major_roads": "#DC2626",
        "highways": "#DC2626",
        "rivers": "#0EA5E9",
        "water": "#2563EB",
        "railways": "#6366F1",
        "parks": "#10B981",
        "landuse": "#84CC16",
        "hospitals": "#EC4899",
        "schools": "#8B5CF6",
    }
    base_color = theme_colors.get(theme, "#0284C7")

    place_tag = f" ({place.title()})" if place else ""
    base_layer_name = str(args.get("layer_name") or f"OSM {label_stem.replace('_', ' ').title()}{place_tag}").strip()

    prepared_files: list[tuple[str, str, str, int]] = []
    non_empty_families = [k for k, v in grouped.items() if v]
    for geom_family in non_empty_families:
        feats = grouped[geom_family]
        suffix = f" ({geom_family.title()})" if len(non_empty_families) > 1 else ""
        lname = f"{base_layer_name}{suffix}"
        out_path = os.path.join(_datasets_dir(), f"osm_{_safe_slug(lname)}_{int(time.time() * 1000) % 1000000}.geojson")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump({"type": "FeatureCollection", "features": feats}, fh, ensure_ascii=False)
        prepared_files.append((geom_family, lname, out_path, len(feats)))

    zoom_flag = bool(args.get("zoom", True))

    def _create_layers_on_main() -> list[dict]:
        from .gis_tools import _PROCESSING_LAYER_REFS, _tool_style_vector_layer
        loaded = []
        for geom_family, lname, out_path, fcount in prepared_files:
            vlyr = QgsVectorLayer(out_path, lname, "ogr")
            if not vlyr.isValid():
                continue
            _PROCESSING_LAYER_REFS.append(vlyr)
            QgsProject.instance().addMapLayer(vlyr)
            _tool_style_vector_layer(iface, {
                "layer": vlyr.id(),
                "style_type": "single",
                "color": base_color,
                "outline_color": "#1D4ED8" if theme == "water" else "#1E293B",
                "opacity": 0.80,
            })
            loaded.append({
                "id": vlyr.id(),
                "name": vlyr.name(),
                "geometry": geom_family,
                "feature_count": fcount,
                "file_path": out_path,
            })
        if zoom_flag and loaded and iface and iface.mapCanvas():
            first_lyr = QgsProject.instance().mapLayer(loaded[0]["id"])
            if first_lyr:
                ext = iface.mapCanvas().mapSettings().layerToMapCoordinates(first_lyr, first_lyr.extent())
                if not ext.isEmpty():
                    ext.scale(1.1)
                    iface.mapCanvas().setExtent(ext)
            iface.mapCanvas().refresh()
        return loaded

    loaded_layers = run_on_main(_create_layers_on_main) if callable(run_on_main) else _create_layers_on_main()

    return {
        "status": "loaded",
        "theme": label_stem,
        "place": resolved_place or place or "map_canvas",
        "source_endpoint": endpoint_used,
        "bbox_wgs84": [round(west, 5), round(south, 5), round(east, 5), round(north, 5)],
        "total_features": total_found,
        "layers": loaded_layers,
    }


# ============================================================================
# 3. LIVE ROAD NETWORK ROUTING (OSRM Public API)
# ============================================================================

def tool_compute_road_route(iface, args: dict, run_on_main=None) -> dict:
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

    def _load_route_on_main() -> str | None:
        vlyr = QgsVectorLayer(out_path, layer_name, "ogr")
        if not vlyr.isValid():
            return None
        from .gis_tools import _PROCESSING_LAYER_REFS, _tool_style_vector_layer
        _PROCESSING_LAYER_REFS.append(vlyr)
        QgsProject.instance().addMapLayer(vlyr)
        _tool_style_vector_layer(iface, {
            "layer": vlyr.id(),
            "style_type": "single",
            "color": "#2563EB",
            "size": 1.8,
            "opacity": 0.95,
        })
        if iface and iface.mapCanvas():
            ext = iface.mapCanvas().mapSettings().layerToMapCoordinates(vlyr, vlyr.extent())
            if not ext.isEmpty():
                ext.scale(1.15)
                iface.mapCanvas().setExtent(ext)
                iface.mapCanvas().refresh()
        return vlyr.id()

    layer_id = run_on_main(_load_route_on_main) if callable(run_on_main) else _load_route_on_main()

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
# 4. MICROSOFT PLANETARY COMPUTER STAC EARTH OBSERVATION DATA (COGs)
# ============================================================================

STAC_DATASETS: dict[str, tuple[str, str, str]] = {
    "dem": ("cop-dem-glo-30", "data", "Copernicus 30m DEM Elevation"),
    "elevation": ("cop-dem-glo-30", "data", "Copernicus 30m DEM Elevation"),
    "nasadem": ("nasadem", "elevation", "NASADEM 30m Elevation"),
    "sentinel2": ("sentinel-2-l2a", "visual", "Sentinel-2 True Color (10m)"),
    "sentinel2_rgb": ("sentinel-2-l2a", "visual", "Sentinel-2 True Color (10m)"),
    "sentinel2_nir": ("sentinel-2-l2a", "B08", "Sentinel-2 NIR Band 8 (10m)"),
    "sentinel2_red": ("sentinel-2-l2a", "B04", "Sentinel-2 Red Band 4 (10m)"),
    "sentinel2_green": ("sentinel-2-l2a", "B03", "Sentinel-2 Green Band 3 (10m)"),
    "sentinel2_blue": ("sentinel-2-l2a", "B02", "Sentinel-2 Blue Band 2 (10m)"),
    "sentinel2_swir": ("sentinel-2-l2a", "B11", "Sentinel-2 SWIR Band 11 (20m)"),
    "sentinel2_swir2": ("sentinel-2-l2a", "B12", "Sentinel-2 SWIR Band 12 (20m)"),
    "lulc": ("io-lulc-annual-v02", "data", "Esri 10m Land Cover (LULC)"),
    "landcover": ("io-lulc-annual-v02", "data", "Esri 10m Land Cover (LULC)"),
    "landsat": ("landsat-c2-l2", "visual", "Landsat 8/9 True Color (30m)"),
    "landsat8": ("landsat-c2-l2", "visual", "Landsat 8/9 True Color (30m)"),
    "sar": ("sentinel-1-rtc", "vv", "Sentinel-1 10m Cloud-Penetrating SAR Radar"),
    "sentinel1": ("sentinel-1-rtc", "vv", "Sentinel-1 10m Cloud-Penetrating SAR Radar"),
    "radar": ("sentinel-1-rtc", "vv", "Sentinel-1 10m Cloud-Penetrating SAR Radar"),
}


def _sign_planetary_computer_href(raw_href: str) -> str:
    sign_url = "https://planetarycomputer.microsoft.com/api/sas/v1/sign?" + urllib.parse.urlencode({"href": raw_href})
    try:
        signed_data = _http_get_json(sign_url, timeout=15)
        return str(signed_data.get("href") or raw_href)
    except Exception:
        return raw_href


def _apply_raster_transparency(rlayer: QgsRasterLayer) -> None:
    """Make black satellite background (0 values) 100% transparent so black tile borders disappear."""
    try:
        for b in range(1, rlayer.bandCount() + 1):
            rlayer.dataProvider().setNoDataValue(b, 0.0)
            rlayer.dataProvider().setUseSourceNoDataValue(b, True)

        from qgis.core import (
            QgsRasterTransparency,
            QgsRasterTransparencyPixel,
            QgsRasterTransparencySingleValuePixel,
        )

        tr = QgsRasterTransparency()
        if rlayer.bandCount() >= 3 and rlayer.renderer():
            p = QgsRasterTransparencyPixel()
            p.red = 0.0
            p.green = 0.0
            p.blue = 0.0
            p.percentTransparent = 100.0
            tr.setTransparentThreeValuePixelList([p])
            rlayer.renderer().setRasterTransparency(tr)
        elif rlayer.bandCount() == 1 and rlayer.renderer():
            sp = QgsRasterTransparencySingleValuePixel()
            sp.min = 0.0
            sp.max = 0.0
            sp.percentTransparent = 100.0
            tr.setTransparentSingleValuePixelList([sp])
            rlayer.renderer().setRasterTransparency(tr)
        rlayer.triggerRepaint()
    except Exception:
        pass


def _apply_pseudocolor_ramp(layer: QgsRasterLayer, items: list[tuple[float, str, str]]) -> None:
    try:
        from qgis.core import (
            QgsColorRampShader,
            QgsRasterShader,
            QgsSingleBandPseudoColorRenderer,
        )
        from qgis.PyQt.QtGui import QColor

        fcn = QgsColorRampShader()
        fcn.setColorRampType(QgsColorRampShader.Interpolated)
        ramp_items = [
            QgsColorRampShader.ColorRampItem(val, QColor(hex_col), label)
            for val, hex_col, label in items
        ]
        fcn.setColorRampItemList(ramp_items)
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(fcn)
        renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
        layer.setRenderer(renderer)
        layer.triggerRepaint()
    except Exception:
        pass


def _apply_ndvi_style(layer: QgsRasterLayer) -> None:
    _apply_pseudocolor_ramp(layer, [
        (-1.0, "#0000FF", "Water (-1.0)"),
        (-0.05, "#A52A2A", "Barren (-0.05)"),
        (0.1, "#DAA520", "Soil/Rock (0.1)"),
        (0.25, "#FFFF00", "Sparse Veg (0.25)"),
        (0.45, "#90EE90", "Moderate Veg (0.45)"),
        (0.65, "#228B22", "Dense Veg (0.65)"),
        (1.0, "#006400", "Very Dense Veg (1.0)"),
    ])


def _apply_ndwi_style(layer: QgsRasterLayer) -> None:
    _apply_pseudocolor_ramp(layer, [
        (-1.0, "#8B4513", "Dry/Vegetation (-1.0)"),
        (-0.2, "#D2B48C", "Low Moisture (-0.2)"),
        (0.0, "#E0FFFF", "Moist Soil (0.0)"),
        (0.2, "#00BFFF", "Shallow Water (0.2)"),
        (0.5, "#0000FF", "Water Body (0.5)"),
        (1.0, "#000080", "Deep Water (1.0)"),
    ])


def _apply_ndbi_style(layer: QgsRasterLayer) -> None:
    _apply_pseudocolor_ramp(layer, [
        (-1.0, "#228B22", "Vegetation/Water (-1.0)"),
        (-0.1, "#90EE90", "Open Soil (-0.1)"),
        (0.0, "#FFFFE0", "Suburban/Mixed (0.0)"),
        (0.2, "#FFA500", "Moderate Built-up (0.2)"),
        (0.5, "#FF4500", "Dense Urban (0.5)"),
        (1.0, "#800080", "High Density Built-up (1.0)"),
    ])


def tool_fetch_stac_earth_data(iface, args: dict, run_on_main=None) -> dict:
    dataset_key = str(args.get("dataset") or "dem").strip().lower()
    place = str(args.get("place") or "").strip()
    bbox = args.get("bbox")
    max_cloud = float(args.get("max_cloud_cover") if args.get("max_cloud_cover") is not None else 20.0)

    is_ndvi = dataset_key in ("ndvi", "sentinel2_ndvi")
    is_ndwi = dataset_key in ("ndwi", "sentinel2_ndwi", "water_index")
    is_ndbi = dataset_key in ("ndbi", "sentinel2_ndbi", "builtup_index")
    is_slope = dataset_key in ("slope", "dem_slope")
    is_hillshade = dataset_key in ("hillshade", "dem_hillshade")
    is_bands = dataset_key in ("sentinel2_bands", "sentinel2_multispectral", "full_bands")

    if is_ndvi or is_ndwi or is_ndbi or is_bands or dataset_key.startswith("sentinel2"):
        collection = "sentinel-2-l2a"
        asset_key = STAC_DATASETS.get(dataset_key, ("sentinel-2-l2a", "visual", "Sentinel-2"))[1]
        label_prefix = "Sentinel-2"
    elif is_slope or is_hillshade or dataset_key in ("dem", "elevation"):
        collection = "cop-dem-glo-30"
        asset_key = "data"
        label_prefix = "Copernicus 30m DEM"
    elif dataset_key in STAC_DATASETS:
        collection, asset_key, label_prefix = STAC_DATASETS[dataset_key]
    else:
        collection = dataset_key
        asset_key = str(args.get("asset_key") or "data")
        label_prefix = f"STAC {collection}"

    if args.get("asset_key"):
        asset_key = str(args["asset_key"]).strip()

    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        bbox_4326 = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
    elif place:
        bbox_4326, _ = _resolve_place_bbox_wgs84(place)
        if not bbox_4326:
            return {"error": f"Could not resolve location '{place}'."}
    else:
        bbox_4326 = run_on_main(lambda: _canvas_bbox_wgs84(iface)) if callable(run_on_main) else _canvas_bbox_wgs84(iface)
        if not bbox_4326:
            return {"error": "Provide a 'place' name or 'bbox' [xmin, ymin, xmax, ymax]."}

    # Target center coordinate for optimal satellite granule footprint alignment
    cx = (bbox_4326[0] + bbox_4326[2]) / 2.0
    cy = (bbox_4326[1] + bbox_4326[3]) / 2.0

    search_payload: dict[str, Any] = {
        "collections": [collection],
        "bbox": bbox_4326,
        "limit": 8,
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

    # Best-granule scoring: choose the item that covers the city center with maximum AOI overlap and lowest cloud cover
    best_item = features[0]
    best_score = -999999.0
    for feat in features:
        item_bb = feat.get("bbox") or []
        cloud = float(feat.get("properties", {}).get("eo:cloud_cover", 0.0) or 0.0)
        score = 0.0
        if len(item_bb) == 4:
            if item_bb[0] <= cx <= item_bb[2] and item_bb[1] <= cy <= item_bb[3]:
                score += 2000.0
            ix_min, iy_min = max(bbox_4326[0], item_bb[0]), max(bbox_4326[1], item_bb[1])
            ix_max, iy_max = min(bbox_4326[2], item_bb[2]), min(bbox_4326[3], item_bb[3])
            if ix_max > ix_min and iy_max > iy_min:
                score += (ix_max - ix_min) * (iy_max - iy_min) * 500.0
        score -= cloud * 10.0
        if score > best_score:
            best_score = score
            best_item = feat

    item = best_item
    item_id = item.get("id", "item")
    assets = item.get("properties") or {}
    item_assets = item.get("assets") or {}
    place_suffix = f" ({place.title()})" if place else ""

    # Helper to zoom canvas to AOI
    def _zoom_canvas_to_aoi() -> None:
        if iface and iface.mapCanvas() and args.get("zoom", True):
            try:
                from qgis.core import QgsRectangle
                rect = QgsRectangle(bbox_4326[0], bbox_4326[1], bbox_4326[2], bbox_4326[3])
                iface.mapCanvas().setExtent(rect)
                iface.mapCanvas().refresh()
            except Exception:
                pass

    # ========================================================================
    # CASE A: SPECTRAL INDICES (NDVI, NDWI, NDBI)
    # ========================================================================
    if is_ndvi or is_ndwi or is_ndbi:
        if is_ndvi:
            b_high_key, b_low_key = "B08", "B04"
            idx_name = "NDVI"
            formula = "(B08 - B04) / (B08 + B04)"
            style_fn = _apply_ndvi_style
        elif is_ndwi:
            b_high_key, b_low_key = "B03", "B08"
            idx_name = "NDWI"
            formula = "(B03 - B08) / (B03 + B08)"
            style_fn = _apply_ndwi_style
        else:
            b_high_key, b_low_key = "B11", "B08"
            idx_name = "NDBI"
            formula = "(B11 - B08) / (B11 + B08)"
            style_fn = _apply_ndbi_style

        bh_obj = item_assets.get(b_high_key)
        bl_obj = item_assets.get(b_low_key)
        if not bh_obj or not bl_obj:
            return {"error": f"STAC item '{item_id}' does not have required bands {b_high_key} and {b_low_key}."}

        signed_h = _sign_planetary_computer_href(str(bh_obj["href"]))
        signed_l = _sign_planetary_computer_href(str(bl_obj["href"]))

        def _calc_index_on_main() -> dict:
            from .gis_tools import _PROCESSING_LAYER_REFS

            lh_name = f"Sentinel-2 {b_high_key}{place_suffix}"
            ll_name = f"Sentinel-2 {b_low_key}{place_suffix}"

            layer_h = QgsRasterLayer(f"/vsicurl/{signed_h}", lh_name, "gdal")
            layer_l = QgsRasterLayer(f"/vsicurl/{signed_l}", ll_name, "gdal")

            if not layer_h.isValid() or not layer_l.isValid():
                return {"error": f"Could not stream Sentinel-2 {b_high_key}/{b_low_key} bands from STAC."}

            _apply_raster_transparency(layer_h)
            _apply_raster_transparency(layer_l)

            _PROCESSING_LAYER_REFS.extend([layer_h, layer_l])
            QgsProject.instance().addMapLayer(layer_h)
            QgsProject.instance().addMapLayer(layer_l)

            calc_layer_name = str(args.get("layer_name") or f"Sentinel-2 {idx_name} (10m){place_suffix}").strip()
            out_file = os.path.join(data_dir(), f"{idx_name.lower()}_{_safe_slug(place or item_id[:16])}.tif")

            calc_layer = None
            try:
                import processing
                from qgis.PyQt.QtCore import QCoreApplication
                QCoreApplication.processEvents()

                # Fast AOI-clipped calculation: compute only for the target city extent
                # to avoid streaming 120 Megapixels over HTTP which causes lag/crashes!
                xmin, ymin, xmax, ymax = bbox_4326
                ext_str = f"{xmin},{xmax},{ymin},{ymax} [EPSG:4326]"

                calc_res = processing.run(
                    "qgis:rastercalculator",
                    {
                        "EXPRESSION": f'("{lh_name}@1" - "{ll_name}@1") / ("{lh_name}@1" + "{ll_name}@1")',
                        "LAYERS": [layer_h, layer_l],
                        "EXTENT": ext_str,
                        "CRS": "EPSG:4326",
                        "CELLSIZE": 0.0001,
                        "OUTPUT": out_file,
                    },
                )
                QCoreApplication.processEvents()
                act_out = calc_res.get("OUTPUT", out_file)
                if os.path.exists(act_out):
                    calc_layer = QgsRasterLayer(act_out, calc_layer_name, "gdal")
            except Exception:
                pass

            if calc_layer is not None and calc_layer.isValid():
                _apply_raster_transparency(calc_layer)
                style_fn(calc_layer)
                _PROCESSING_LAYER_REFS.append(calc_layer)
                QgsProject.instance().addMapLayer(calc_layer)
                _zoom_canvas_to_aoi()
                return {
                    "status": f"{idx_name.lower()}_calculated_successfully",
                    "index": idx_name,
                    "layer_name": calc_layer.name(),
                    "layer_id": calc_layer.id(),
                    "formula": formula,
                    "resolution": "10m",
                    "cloud_cover": assets.get("eo:cloud_cover"),
                    "datetime": assets.get("datetime"),
                    "file_path": out_file,
                }
            else:
                _zoom_canvas_to_aoi()
                return {
                    "status": "bands_loaded",
                    "band1": lh_name,
                    "band2": ll_name,
                    "message": f"Loaded both Sentinel-2 {b_high_key} and {b_low_key} layers for {idx_name}. Formula: ('{lh_name}@1' - '{ll_name}@1') / ('{lh_name}@1' + '{ll_name}@1').",
                }

        return run_on_main(_calc_index_on_main) if callable(run_on_main) else _calc_index_on_main()

    # ========================================================================
    # CASE B: TERRAIN ANALYSIS (SLOPE & HILLSHADE FROM DEM)
    # ========================================================================
    if is_slope or is_hillshade:
        asset_obj = item_assets.get("data")
        if not asset_obj or not asset_obj.get("href"):
            return {"error": "DEM GeoTIFF asset not found."}
        signed_dem = _sign_planetary_computer_href(str(asset_obj["href"]))

        def _calc_terrain_on_main() -> dict:
            from .gis_tools import _PROCESSING_LAYER_REFS
            dem_name = f"Copernicus 30m DEM{place_suffix}"
            dem_layer = QgsRasterLayer(f"/vsicurl/{signed_dem}", dem_name, "gdal")
            if not dem_layer.isValid():
                return {"error": "Could not stream DEM raster."}
            _apply_raster_transparency(dem_layer)
            _PROCESSING_LAYER_REFS.append(dem_layer)
            QgsProject.instance().addMapLayer(dem_layer)

            target_out = os.path.join(data_dir(), f"{'slope' if is_slope else 'hillshade'}_{_safe_slug(place or item_id[:16])}.tif")
            res_layer = None
            try:
                import processing
                from qgis.PyQt.QtCore import QCoreApplication
                QCoreApplication.processEvents()
                alg = "native:slope" if is_slope else "native:hillshade"
                xmin, ymin, xmax, ymax = bbox_4326
                clipped_dem = os.path.join(data_dir(), f"dem_clip_{_safe_slug(place or item_id[:16])}.tif")
                clip_res = processing.run(
                    "gdal:cliprasterbyextent",
                    {
                        "INPUT": dem_layer,
                        "PROJWIN": f"{xmin},{xmax},{ymin},{ymax} [EPSG:4326]",
                        "OUTPUT": clipped_dem,
                    },
                )
                input_for_alg = clip_res.get("OUTPUT", dem_layer)
                p_res = processing.run(alg, {"INPUT": input_for_alg, "OUTPUT": target_out})
                QCoreApplication.processEvents()
                out_p = p_res.get("OUTPUT", target_out)
                if os.path.exists(out_p):
                    res_layer = QgsRasterLayer(out_p, f"Copernicus {'Slope (Degrees)' if is_slope else 'Hillshade'}{place_suffix}", "gdal")
            except Exception:
                pass

            if res_layer is not None and res_layer.isValid():
                _apply_raster_transparency(res_layer)
                _PROCESSING_LAYER_REFS.append(res_layer)
                QgsProject.instance().addMapLayer(res_layer)
                _zoom_canvas_to_aoi()
                return {"status": "terrain_analysis_complete", "layer_name": res_layer.name(), "file_path": target_out}
            _zoom_canvas_to_aoi()
            return {"status": "dem_loaded", "layer_name": dem_layer.name()}

        return run_on_main(_calc_terrain_on_main) if callable(run_on_main) else _calc_terrain_on_main()

    # ========================================================================
    # CASE C: MULTISPECTRAL BANDS (Loads B04, B08, B03, B02 & True Color)
    # ========================================================================
    if is_bands:
        band_keys = [("visual", "True Color RGB"), ("B08", "NIR Band 8"), ("B04", "Red Band 4"), ("B03", "Green Band 3"), ("B02", "Blue Band 2")]
        loaded_info = []

        def _load_all_bands_on_main() -> dict:
            from .gis_tools import _PROCESSING_LAYER_REFS
            for bkey, bdesc in band_keys:
                b_obj = item_assets.get(bkey)
                if b_obj and b_obj.get("href"):
                    shref = _sign_planetary_computer_href(str(b_obj["href"]))
                    lyr_name = f"Sentinel-2 {bdesc}{place_suffix}"
                    rlayer = QgsRasterLayer(f"/vsicurl/{shref}", lyr_name, "gdal")
                    if rlayer.isValid():
                        _apply_raster_transparency(rlayer)
                        _PROCESSING_LAYER_REFS.append(rlayer)
                        QgsProject.instance().addMapLayer(rlayer)
                        loaded_info.append(lyr_name)
            _zoom_canvas_to_aoi()
            return {
                "status": "sentinel2_bands_loaded",
                "bands_loaded": loaded_info,
                "item_id": item_id,
                "datetime": assets.get("datetime"),
            }

        return run_on_main(_load_all_bands_on_main) if callable(run_on_main) else _load_all_bands_on_main()

    # ========================================================================
    # CASE D: STANDARD SINGLE/RGB RASTER (DEM, LULC, Visual Sentinel-2, Landsat, SAR)
    # ========================================================================
    asset_obj = item_assets.get(asset_key) or next(
        (v for v in item_assets.values() if "tiff" in str(v.get("type", "")).lower()),
        None,
    )
    if not asset_obj or not asset_obj.get("href"):
        return {"error": f"No GeoTIFF asset '{asset_key}' found in STAC item '{item_id}'."}

    signed_href = _sign_planetary_computer_href(str(asset_obj["href"]))
    vsi_uri = f"/vsicurl/{signed_href}"
    layer_name = str(args.get("layer_name") or f"{label_prefix}{place_suffix} [{item_id[:18]}]").strip()

    def _load_cog_on_main() -> dict:
        rlayer = QgsRasterLayer(vsi_uri, layer_name, "gdal")
        if not rlayer.isValid():
            return {"error": f"GDAL could not stream COG raster from '{signed_href[:120]}'."}

        _apply_raster_transparency(rlayer)

        from .gis_tools import _PROCESSING_LAYER_REFS
        _PROCESSING_LAYER_REFS.append(rlayer)
        QgsProject.instance().addMapLayer(rlayer)
        _zoom_canvas_to_aoi()
        return {
            "status": "streamed_cog_loaded",
            "collection": collection,
            "item_id": item_id,
            "asset_key": asset_key,
            "datetime": assets.get("datetime"),
            "cloud_cover": assets.get("eo:cloud_cover"),
            "layer_id": rlayer.id(),
            "layer_name": rlayer.name(),
            "crs": rlayer.crs().authid(),
            "width": rlayer.width(),
            "height": rlayer.height(),
            "bands": rlayer.bandCount(),
        }

    return run_on_main(_load_cog_on_main) if callable(run_on_main) else _load_cog_on_main()


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
    conn_name = str(args.get("connection_name") or args.get("name") or "").strip()
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
        from .gis_tools import _PROCESSING_LAYER_REFS
        _PROCESSING_LAYER_REFS.append(rlayer)
        QgsProject.instance().addMapLayer(rlayer)
        return {"status": "loaded", "type": "xyz", "name": matched, "layer_id": rlayer.id()}

    return {"error": f"Unsupported connection_type '{conn_type}'. Currently supports 'xyz'."}
