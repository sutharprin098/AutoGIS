from __future__ import annotations

import contextlib
import io
import json
import math
import os
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFillSymbol,
    QgsGraduatedSymbolRenderer,
    QgsGradientColorRamp,
    QgsHeatmapRenderer,
    QgsLineSymbol,
    QgsMapLayer,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsRendererCategory,
    QgsRendererRange,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QSize, QVariant
from qgis.PyQt.QtGui import QColor, QFont, QImage

from .config import data_dir, log_info, log_warn

_NO_GEOM_FLAG = getattr(
    QgsFeatureRequest,
    "NoGeometry",
    getattr(getattr(QgsFeatureRequest, "Flag", None), "NoGeometry", 2),
)


@dataclass
class GISToolSpec:
    name: str
    description: str
    risk: str  # "read" or "write"
    parameters: dict[str, Any]
    handler: Callable[[Any, dict[str, Any]], dict[str, Any]]


BASEMAP_SOURCES: dict[str, tuple[str, str]] = {
    "osm": (
        "OpenStreetMap Standard",
        "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0",
    ),
    "google_satellite": (
        "Google Satellite",
        "type=xyz&url=https://mt1.google.com/vt/lyrs%3Ds%26x%3D{x}%26y%3D{y}%26z%3D{z}&zmax=20&zmin=0",
    ),
    "google_hybrid": (
        "Google Hybrid (Satellite + Labels)",
        "type=xyz&url=https://mt1.google.com/vt/lyrs%3Dy%26x%3D{x}%26y%3D{y}%26z%3D{z}&zmax=20&zmin=0",
    ),
    "esri_satellite": (
        "Esri World Imagery",
        "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}&zmax=19&zmin=0",
    ),
    "carto_dark": (
        "CartoDB Dark Matter",
        "type=xyz&url=https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png&zmax=19&zmin=0",
    ),
    "carto_light": (
        "CartoDB Positron Light",
        "type=xyz&url=https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png&zmax=19&zmin=0",
    ),
    "opentopomap": (
        "OpenTopoMap Terrain",
        "type=xyz&url=https://tile.opentopomap.org/{z}/{x}/{y}.png&zmax=17&zmin=0",
    ),
}

COLOR_PALETTES: dict[str, list[str]] = {
    "viridis": ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    "spectral": ["#d53e4f", "#fc8d59", "#fee08b", "#e6f598", "#99d594", "#3288bd"],
    "reds": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"],
    "blues": ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
    "greens": ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
    "magma": ["#000004", "#51127c", "#b73779", "#fc8961", "#fcfdbf"],
    "rdylgn": ["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#91cf60", "#1a9850"],
    "vibrant": ["#00F5D4", "#00BBF9", "#FEE440", "#F15BB5", "#9B5DE5", "#FB5607"],
}


def _resolve_layer(name_or_id: str) -> QgsMapLayer | None:
    target = str(name_or_id or "").strip()
    if not target:
        return None
    proj = QgsProject.instance()
    by_id = proj.mapLayer(target)
    if by_id is not None:
        return by_id
    by_name = proj.mapLayersByName(target)
    if by_name:
        return by_name[0]
    target_low = target.lower()
    for lyr in proj.mapLayers().values():
        if lyr.name().lower() == target_low or target_low in lyr.name().lower():
            return lyr
    return None


def _safe_val(val: Any) -> Any:
    if val is None:
        return None
    if hasattr(val, "isNull") and callable(val.isNull) and val.isNull():
        return None
    if isinstance(val, (int, float, str, bool)):
        return val
    return str(val)


def _geom_type_label(layer: QgsMapLayer) -> str:
    if isinstance(layer, QgsVectorLayer):
        return QgsWkbTypes.displayString(layer.wkbType()) or QgsWkbTypes.geometryDisplayString(layer.geometryType())
    if isinstance(layer, QgsRasterLayer):
        return "Raster"
    return "Other"


def _interpolate_color(hex_colors: list[str], t: float) -> QColor:
    if not hex_colors:
        return QColor("#00BBF9")
    if len(hex_colors) == 1 or t <= 0.0:
        return QColor(hex_colors[0])
    if t >= 1.0:
        return QColor(hex_colors[-1])
    scaled = t * (len(hex_colors) - 1)
    idx = int(math.floor(scaled))
    frac = scaled - idx
    c1 = QColor(hex_colors[idx])
    c2 = QColor(hex_colors[min(idx + 1, len(hex_colors) - 1)])
    r = int(c1.red() + (c2.red() - c1.red()) * frac)
    g = int(c1.green() + (c2.green() - c1.green()) * frac)
    b = int(c1.blue() + (c2.blue() - c1.blue()) * frac)
    return QColor(r, g, b)


# ============================================================================
# TOOL IMPLEMENTATIONS
# ============================================================================

def _tool_get_project_overview(iface, args: dict) -> dict:
    proj = QgsProject.instance()
    canvas = iface.mapCanvas() if iface else None
    extent_dict = {}
    if canvas is not None:
        ext = canvas.extent()
        extent_dict = {
            "xmin": round(ext.xMinimum(), 6),
            "ymin": round(ext.yMinimum(), 6),
            "xmax": round(ext.xMaximum(), 6),
            "ymax": round(ext.yMaximum(), 6),
            "scale": round(canvas.scale(), 2),
        }
    layers_summary = []
    root = proj.layerTreeRoot()
    for lyr in proj.mapLayers().values():
        node = root.findLayer(lyr.id()) if root else None
        vis = bool(node.isVisible()) if node is not None else True
        info: dict[str, Any] = {
            "id": lyr.id(),
            "name": lyr.name(),
            "type": "vector" if isinstance(lyr, QgsVectorLayer) else ("raster" if isinstance(lyr, QgsRasterLayer) else "other"),
            "geometry": _geom_type_label(lyr),
            "crs": lyr.crs().authid() if lyr.crs().isValid() else "",
            "visible": vis,
        }
        if isinstance(lyr, QgsVectorLayer):
            info["feature_count"] = lyr.featureCount()
            info["fields"] = [f.name() for f in lyr.fields()][:20]
        layers_summary.append(info)

    active = iface.activeLayer() if iface else None
    return {
        "project_file": proj.fileName() or "(unsaved project)",
        "project_title": proj.title() or "",
        "crs": proj.crs().authid() if proj.crs().isValid() else "EPSG:4326",
        "crs_description": proj.crs().description() if proj.crs().isValid() else "",
        "distance_units": str(proj.distanceUnits()),
        "map_canvas": extent_dict,
        "active_layer": active.name() if active else None,
        "layer_count": len(layers_summary),
        "layers": layers_summary,
    }


def _tool_list_layers(iface, args: dict) -> dict:
    proj = QgsProject.instance()
    root = proj.layerTreeRoot()
    items = []
    for lyr in proj.mapLayers().values():
        node = root.findLayer(lyr.id()) if root else None
        ext = lyr.extent()
        item: dict[str, Any] = {
            "id": lyr.id(),
            "name": lyr.name(),
            "type": "vector" if isinstance(lyr, QgsVectorLayer) else ("raster" if isinstance(lyr, QgsRasterLayer) else "other"),
            "geometry": _geom_type_label(lyr),
            "crs": lyr.crs().authid(),
            "visible": bool(node.isVisible()) if node is not None else True,
            "provider": lyr.providerType() if hasattr(lyr, "providerType") else "",
            "extent": [round(ext.xMinimum(), 5), round(ext.yMinimum(), 5), round(ext.xMaximum(), 5), round(ext.yMaximum(), 5)] if not ext.isEmpty() else [],
        }
        if isinstance(lyr, QgsVectorLayer):
            item["feature_count"] = lyr.featureCount()
            item["selected_count"] = lyr.selectedFeatureCount()
            item["field_count"] = len(lyr.fields())
        elif isinstance(lyr, QgsRasterLayer):
            item["width"] = lyr.width()
            item["height"] = lyr.height()
            item["band_count"] = lyr.bandCount()
        items.append(item)
    return {"count": len(items), "layers": items}


def _tool_inspect_layer(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    lyr = _resolve_layer(target)
    if lyr is None:
        return {"error": f"Layer '{target}' not found in project."}
    ext = lyr.extent()
    res: dict[str, Any] = {
        "id": lyr.id(),
        "name": lyr.name(),
        "source": lyr.publicSource() if hasattr(lyr, "publicSource") else lyr.source(),
        "crs": lyr.crs().authid(),
        "crs_description": lyr.crs().description(),
        "geometry": _geom_type_label(lyr),
        "extent": {
            "xmin": round(ext.xMinimum(), 6),
            "ymin": round(ext.yMinimum(), 6),
            "xmax": round(ext.xMaximum(), 6),
            "ymax": round(ext.yMaximum(), 6),
        } if not ext.isEmpty() else {},
    }
    if isinstance(lyr, QgsVectorLayer):
        res["feature_count"] = lyr.featureCount()
        res["selected_count"] = lyr.selectedFeatureCount()
        res["fields"] = [
            {"name": f.name(), "type": f.typeName(), "length": f.length()}
            for f in lyr.fields()
        ]
        renderer = lyr.renderer()
        res["renderer_type"] = renderer.type() if renderer else "none"
        res["labels_enabled"] = bool(lyr.labelsEnabled())
        sample_rows = []
        req = QgsFeatureRequest().setLimit(int(args.get("sample_limit") or 5))
        for feat in lyr.getFeatures(req):
            row = {f.name(): _safe_val(feat[f.name()]) for f in lyr.fields()}
            row["_fid"] = feat.id()
            sample_rows.append(row)
        res["sample_features"] = sample_rows
    elif isinstance(lyr, QgsRasterLayer):
        res["width"] = lyr.width()
        res["height"] = lyr.height()
        res["band_count"] = lyr.bandCount()
        res["bands"] = [lyr.bandName(b) for b in range(1, lyr.bandCount() + 1)]
        band_stats = []
        try:
            from qgis.core import QgsRasterBandStats
            dp = lyr.dataProvider()
            if dp is not None:
                stats_flag = getattr(QgsRasterBandStats, "All", getattr(getattr(QgsRasterBandStats, "Stats", None), "All", 15))
                for b in range(1, min(lyr.bandCount(), 8) + 1):
                    st = dp.bandStatistics(b, stats_flag, lyr.extent(), 250000)
                    band_stats.append({
                        "band": b,
                        "name": lyr.bandName(b),
                        "min": round(float(st.minimumValue), 4) if not math.isnan(st.minimumValue) else None,
                        "max": round(float(st.maximumValue), 4) if not math.isnan(st.maximumValue) else None,
                        "mean": round(float(st.mean), 4) if not math.isnan(st.mean) else None,
                        "std_dev": round(float(st.stdDev), 4) if not math.isnan(st.stdDev) else None,
                    })
        except Exception:
            pass
        if band_stats:
            res["band_statistics"] = band_stats
    return res


def _tool_query_features(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}
    expr_str = str(args.get("filter_expression") or "").strip()
    limit = max(1, min(int(args.get("limit") or 25), 500))
    include_geom = bool(args.get("include_geometry", False))
    requested_fields = args.get("fields") or []

    req = QgsFeatureRequest().setLimit(limit)
    if expr_str:
        req.setFilterExpression(expr_str)
    if not include_geom:
        req.setFlags(_NO_GEOM_FLAG)

    all_field_names = [f.name() for f in lyr.fields()]
    use_fields = [f for f in requested_fields if f in all_field_names] if requested_fields else all_field_names

    features_out = []
    for feat in lyr.getFeatures(req):
        attrs = {fn: _safe_val(feat[fn]) for fn in use_fields}
        item: dict[str, Any] = {"fid": feat.id(), "attributes": attrs}
        if include_geom and feat.hasGeometry():
            geom = feat.geometry()
            wkt = geom.asWkt(4)
            item["geometry_wkt"] = wkt[:300] + ("..." if len(wkt) > 300 else "")
        features_out.append(item)

    return {
        "layer": lyr.name(),
        "total_layer_features": lyr.featureCount(),
        "returned_count": len(features_out),
        "filter_expression": expr_str or None,
        "features": features_out,
    }


def _tool_compute_field_stats(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    field_name = str(args.get("field") or "").strip()
    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}
    idx = lyr.fields().indexFromName(field_name)
    if idx < 0:
        return {"error": f"Field '{field_name}' not found. Available fields: {[f.name() for f in lyr.fields()]}"}

    values = []
    null_count = 0
    freq: dict[str, int] = {}
    req = QgsFeatureRequest().setFlags(_NO_GEOM_FLAG).setSubsetOfAttributes([idx])
    for feat in lyr.getFeatures(req):
        v = _safe_val(feat[idx])
        if v is None or v == "":
            null_count += 1
            continue
        s_val = str(v)
        freq[s_val] = freq.get(s_val, 0) + 1
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            pass

    top_values = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:15]
    result: dict[str, Any] = {
        "layer": lyr.name(),
        "field": field_name,
        "non_null_count": sum(freq.values()),
        "null_count": null_count,
        "unique_count": len(freq),
        "top_values": [{"value": k, "count": c} for k, c in top_values],
    }
    if values:
        values.sort()
        n = len(values)
        mean_val = sum(values) / n
        median_val = values[n // 2] if n % 2 == 1 else (values[n // 2 - 1] + values[n // 2]) / 2.0
        variance = sum((x - mean_val) ** 2 for x in values) / n
        result["numeric_stats"] = {
            "min": round(values[0], 6),
            "max": round(values[-1], 6),
            "sum": round(sum(values), 6),
            "mean": round(mean_val, 6),
            "median": round(median_val, 6),
            "std_dev": round(math.sqrt(variance), 6),
        }
    return result


def _tool_evaluate_expression(iface, args: dict) -> dict:
    expr_str = str(args.get("expression") or "").strip()
    if not expr_str:
        return {"error": "Expression string is required."}
    exp = QgsExpression(expr_str)
    if exp.hasParserError():
        return {"error": f"Parser error: {exp.parserErrorString()}"}

    ctx = QgsExpressionContext()
    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(_resolve_layer(args.get("layer") or "")))
    lyr = _resolve_layer(args.get("layer") or "")
    if isinstance(lyr, QgsVectorLayer):
        for feat in lyr.getFeatures(QgsFeatureRequest().setLimit(1)):
            ctx.setFeature(feat)
            break
    val = exp.evaluate(ctx)
    if exp.hasEvalError():
        return {"error": f"Evaluation error: {exp.evalErrorString()}"}
    return {"expression": expr_str, "result": _safe_val(val)}


def _tool_select_features(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    expr_str = str(args.get("expression") or "").strip()
    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}
    if not expr_str:
        lyr.removeSelection()
        return {"layer": lyr.name(), "selected_count": 0, "message": "Selection cleared."}
    lyr.selectByExpression(expr_str)
    count = lyr.selectedFeatureCount()
    if args.get("zoom_to_selection", True) and count > 0 and iface and iface.mapCanvas():
        iface.mapCanvas().zoomToSelected(lyr)
        iface.mapCanvas().refresh()
    return {"layer": lyr.name(), "expression": expr_str, "selected_count": count}


def _tool_add_basemap(iface, args: dict) -> dict:
    key = str(args.get("basemap") or "osm").strip().lower()
    if key not in BASEMAP_SOURCES:
        key = "osm"
    title, uri = BASEMAP_SOURCES[key]
    rlayer = QgsRasterLayer(uri, title, "wms")
    if not rlayer.isValid():
        return {"error": f"Failed to initialize basemap '{title}'."}
    proj = QgsProject.instance()
    proj.addMapLayer(rlayer, False)
    # Place basemap at the bottom of the layer tree so vector layers stay visible on top
    root = proj.layerTreeRoot()
    if root is not None:
        root.insertLayer(-1, rlayer)
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()
    return {"status": "added", "layer_id": rlayer.id(), "name": title, "basemap_key": key}


def _tool_load_dataset(iface, args: dict) -> dict:
    path_or_uri = str(args.get("path") or "").strip()
    if not path_or_uri:
        return {"error": "A file path or URI is required."}
    layer_name = str(args.get("name") or "").strip()
    if not layer_name:
        layer_name = os.path.splitext(os.path.basename(path_or_uri.split("|")[0]))[0] or "Loaded_Layer"

    ext = os.path.splitext(path_or_uri.split("|")[0])[1].lower()
    is_raster = ext in (".tif", ".tiff", ".img", ".asc", ".dem", ".jp2", ".ecw", ".vrt", ".nc") or str(args.get("layer_type") or "").lower() == "raster"

    if is_raster:
        lyr = QgsRasterLayer(path_or_uri, layer_name)
    elif ext == ".csv" and not path_or_uri.startswith("file:"):
        lon_col = args.get("x_field") or "lon"
        lat_col = args.get("y_field") or "lat"
        crs_str = args.get("crs") or "EPSG:4326"
        norm_path = path_or_uri.replace("\\", "/")
        uri = f"file:///{norm_path.lstrip('/')}?delimiter=,&xField={lon_col}&yField={lat_col}&crs={crs_str}"
        lyr = QgsVectorLayer(uri, layer_name, "delimitedtext")
        if not lyr.isValid():
            lyr = QgsVectorLayer(path_or_uri, layer_name, "ogr")
    else:
        lyr = QgsVectorLayer(path_or_uri, layer_name, str(args.get("provider") or "ogr"))

    if not lyr.isValid():
        return {"error": f"Could not load dataset from '{path_or_uri}'. Check path and format."}

    QgsProject.instance().addMapLayer(lyr)
    if args.get("zoom", True) and iface and iface.mapCanvas():
        iface.setActiveLayer(lyr)
        iface.zoomToActiveLayer()
        iface.mapCanvas().refresh()

    out: dict[str, Any] = {
        "status": "loaded",
        "id": lyr.id(),
        "name": lyr.name(),
        "geometry": _geom_type_label(lyr),
        "crs": lyr.crs().authid(),
    }
    if isinstance(lyr, QgsVectorLayer):
        out["feature_count"] = lyr.featureCount()
        out["fields"] = [f.name() for f in lyr.fields()]
    return out


def _tool_create_memory_layer(iface, args: dict) -> dict:
    name = str(args.get("name") or "New_Layer").strip()
    geom_type = str(args.get("geometry_type") or "Point").strip()
    crs = str(args.get("crs") or QgsProject.instance().crs().authid() or "EPSG:4326").strip()
    fields_spec = args.get("fields") or []
    features_spec = args.get("features") or []

    uri = f"{geom_type}?crs={crs}"
    lyr = QgsVectorLayer(uri, name, "memory")
    if not lyr.isValid():
        return {"error": f"Could not create memory layer with URI '{uri}'."}

    pr = lyr.dataProvider()
    qgs_fields = []
    type_map = {
        "string": QVariant.String,
        "text": QVariant.String,
        "int": QVariant.Int,
        "integer": QVariant.Int,
        "float": QVariant.Double,
        "double": QVariant.Double,
        "number": QVariant.Double,
        "bool": QVariant.Bool,
    }
    for fdef in fields_spec:
        if isinstance(fdef, dict) and fdef.get("name"):
            ftype = type_map.get(str(fdef.get("type") or "string").lower(), QVariant.String)
            qgs_fields.append(QgsField(str(fdef["name"]), ftype))
    if qgs_fields:
        pr.addAttributes(qgs_fields)
        lyr.updateFields()

    added = 0
    if features_spec:
        new_feats = []
        from qgis.core import QgsGeometry
        for fitem in features_spec:
            if not isinstance(fitem, dict):
                continue
            feat = QgsFeature(lyr.fields())
            wkt = str(fitem.get("wkt") or "").strip()
            if wkt:
                feat.setGeometry(QgsGeometry.fromWkt(wkt))
            attrs = fitem.get("attributes") or {}
            if isinstance(attrs, dict):
                for k, v in attrs.items():
                    if lyr.fields().indexFromName(k) >= 0:
                        feat.setAttribute(k, v)
            new_feats.append(feat)
        if new_feats:
            ok, out_f = pr.addFeatures(new_feats)
            if ok:
                added = len(out_f)
            lyr.updateExtents()

    QgsProject.instance().addMapLayer(lyr)
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()
    return {
        "status": "created",
        "id": lyr.id(),
        "name": lyr.name(),
        "geometry_type": geom_type,
        "crs": crs,
        "fields": [f.name() for f in lyr.fields()],
        "features_added": added,
    }


def _tool_add_features(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}
    features_spec = args.get("features") or []
    if not features_spec:
        return {"error": "No features provided to add."}

    from qgis.core import QgsGeometry
    new_feats = []
    for fitem in features_spec:
        if not isinstance(fitem, dict):
            continue
        feat = QgsFeature(lyr.fields())
        wkt = str(fitem.get("wkt") or "").strip()
        if wkt:
            feat.setGeometry(QgsGeometry.fromWkt(wkt))
        attrs = fitem.get("attributes") or {}
        if isinstance(attrs, dict):
            for k, v in attrs.items():
                if lyr.fields().indexFromName(k) >= 0:
                    feat.setAttribute(k, v)
        new_feats.append(feat)

    ok, added_feats = lyr.dataProvider().addFeatures(new_feats)
    lyr.updateExtents()
    lyr.triggerRepaint()
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()
    return {
        "layer": lyr.name(),
        "success": bool(ok),
        "added_count": len(added_feats) if ok else 0,
        "total_features": lyr.featureCount(),
    }


def _tool_calculate_or_add_field(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    field_name = str(args.get("field_name") or "").strip()
    field_type = str(args.get("field_type") or "double").strip().lower()
    expression_str = str(args.get("expression") or "").strip()

    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}
    if not field_name or not expression_str:
        return {"error": "Both 'field_name' and 'expression' are required."}

    exp = QgsExpression(expression_str)
    if exp.hasParserError():
        return {"error": f"Invalid expression: {exp.parserErrorString()}"}

    idx = lyr.fields().indexFromName(field_name)
    if idx < 0:
        type_map = {
            "string": QVariant.String,
            "text": QVariant.String,
            "int": QVariant.Int,
            "integer": QVariant.Int,
            "double": QVariant.Double,
            "float": QVariant.Double,
        }
        qtype = type_map.get(field_type, QVariant.Double)
        lyr.dataProvider().addAttributes([QgsField(field_name, qtype)])
        lyr.updateFields()
        idx = lyr.fields().indexFromName(field_name)
        if idx < 0:
            return {"error": f"Could not add field '{field_name}' to layer '{lyr.name()}'."}

    ctx = QgsExpressionContext()
    ctx.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(lyr))
    exp.prepare(ctx)

    updates: dict[int, dict[int, Any]] = {}
    for feat in lyr.getFeatures():
        ctx.setFeature(feat)
        val = exp.evaluate(ctx)
        updates[feat.id()] = {idx: val}

    if updates:
        lyr.dataProvider().changeAttributeValues(updates)
    lyr.triggerRepaint()
    return {
        "layer": lyr.name(),
        "field_name": field_name,
        "expression": expression_str,
        "updated_features": len(updates),
    }


def _tool_delete_features(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    expr_str = str(args.get("filter_expression") or "").strip()
    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}
    if not expr_str:
        return {"error": "'filter_expression' is required to delete features safely."}

    req = QgsFeatureRequest().setFilterExpression(expr_str).setFlags(_NO_GEOM_FLAG).setNoAttributes()
    fids = [f.id() for f in lyr.getFeatures(req)]
    if not fids:
        return {"layer": lyr.name(), "deleted_count": 0, "message": "No features matched the filter expression."}

    ok = lyr.dataProvider().deleteFeatures(fids)
    lyr.updateExtents()
    lyr.triggerRepaint()
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()
    return {"layer": lyr.name(), "deleted_count": len(fids) if ok else 0, "remaining_features": lyr.featureCount()}


def _create_symbol_for_layer(lyr: QgsVectorLayer, fill_color: QColor, outline_color: QColor,
                             size_or_width: float, opacity: float) -> QgsSymbol:
    glabel = _geom_type_label(lyr)
    if glabel == "Point":
        sym = QgsMarkerSymbol.createSimple({
            "name": "circle",
            "color": fill_color.name(),
            "outline_color": outline_color.name(),
            "outline_width": "0.4",
            "size": str(max(1.0, size_or_width)),
        })
    elif glabel == "LineString":
        sym = QgsLineSymbol.createSimple({
            "color": fill_color.name(),
            "width": str(max(0.2, size_or_width)),
        })
    else:
        sym = QgsFillSymbol.createSimple({
            "color": fill_color.name(),
            "outline_color": outline_color.name(),
            "outline_width": str(max(0.1, min(size_or_width, 2.0))),
        })
    sym.setOpacity(max(0.05, min(1.0, opacity)))
    return sym


def _tool_style_vector_layer(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}

    style_type = str(args.get("style_type") or "single").strip().lower()
    field_name = str(args.get("field") or "").strip()
    color_hex = str(args.get("color") or "#00BBF9").strip()
    outline_hex = str(args.get("outline_color") or "#1E293B").strip()
    palette_name = str(args.get("palette") or "viridis").strip().lower()
    palette = COLOR_PALETTES.get(palette_name, COLOR_PALETTES["viridis"])
    opacity = float(args.get("opacity") if args.get("opacity") is not None else 0.85)
    glabel = _geom_type_label(lyr)
    default_size = 3.2 if glabel == "Point" else (1.2 if glabel == "LineString" else 0.4)
    size_val = float(args.get("size") if args.get("size") is not None else default_size)

    if style_type == "single":
        sym = _create_symbol_for_layer(lyr, QColor(color_hex), QColor(outline_hex), size_val, opacity)
        lyr.setRenderer(QgsSingleSymbolRenderer(sym))

    elif style_type == "categorized":
        idx = lyr.fields().indexFromName(field_name)
        if idx < 0:
            return {"error": f"Field '{field_name}' not found for categorized styling."}
        unique_vals = sorted(
            [v for v in lyr.uniqueValues(idx) if v is not None and str(v) != ""],
            key=lambda x: str(x),
        )[:50]
        if not unique_vals:
            return {"error": f"No unique non-null values found in field '{field_name}'."}
        categories = []
        n = len(unique_vals)
        for i, val in enumerate(unique_vals):
            t = i / max(1, n - 1) if n > 1 else 0.5
            col = _interpolate_color(palette, t)
            sym = _create_symbol_for_layer(lyr, col, QColor(outline_hex), size_val, opacity)
            categories.append(QgsRendererCategory(val, sym, str(val)))
        renderer = QgsCategorizedSymbolRenderer(field_name, categories)
        lyr.setRenderer(renderer)

    elif style_type == "graduated":
        idx = lyr.fields().indexFromName(field_name)
        if idx < 0:
            return {"error": f"Numeric field '{field_name}' not found for graduated styling."}
        classes = max(2, min(int(args.get("classes") or 5), 12))
        num_vals = []
        for feat in lyr.getFeatures(QgsFeatureRequest().setFlags(_NO_GEOM_FLAG).setSubsetOfAttributes([idx])):
            try:
                v = feat[idx]
                if v is not None:
                    num_vals.append(float(v))
            except (TypeError, ValueError):
                pass
        if not num_vals:
            return {"error": f"Field '{field_name}' contains no numeric values."}
        num_vals.sort()
        ranges = []
        for i in range(classes):
            p_low = int(round((i / classes) * (len(num_vals) - 1)))
            p_high = int(round(((i + 1) / classes) * (len(num_vals) - 1)))
            low_v = num_vals[p_low]
            high_v = num_vals[p_high]
            col = _interpolate_color(palette, i / max(1, classes - 1))
            sym = _create_symbol_for_layer(lyr, col, QColor(outline_hex), size_val, opacity)
            label = f"{low_v:.2f} - {high_v:.2f}"
            ranges.append(QgsRendererRange(low_v, high_v, sym, label))
        renderer = QgsGraduatedSymbolRenderer(field_name, ranges)
        lyr.setRenderer(renderer)

    elif style_type == "heatmap":
        if glabel != "Point":
            return {"error": "Heatmap renderer is only supported on Point vector layers."}
        hm = QgsHeatmapRenderer()
        hm.setRadius(float(args.get("radius") or 15.0))
        ramp = QgsGradientColorRamp(QColor(255, 255, 255, 0), QColor(palette[-1]))
        hm.setColorRamp(ramp)
        lyr.setRenderer(hm)
    else:
        return {"error": f"Unsupported style_type '{style_type}'. Choose single, categorized, graduated, or heatmap."}

    lyr.triggerRepaint()
    if iface:
        if iface.layerTreeView():
            iface.layerTreeView().refreshLayerSymbology(lyr.id())
        if iface.mapCanvas():
            iface.mapCanvas().refresh()

    return {
        "status": "styled",
        "layer": lyr.name(),
        "style_type": style_type,
        "field": field_name or None,
        "palette": palette_name if style_type != "single" else color_hex,
    }


def _tool_configure_labels(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}

    enabled = bool(args.get("enabled", True))
    if not enabled:
        lyr.setLabelsEnabled(False)
        lyr.triggerRepaint()
        return {"layer": lyr.name(), "labels_enabled": False}

    field_name = str(args.get("field") or "").strip()
    if not field_name:
        fields = [f.name() for f in lyr.fields()]
        field_name = fields[0] if fields else ""
    if not field_name:
        return {"error": f"Layer '{lyr.name()}' has no fields to label."}

    pal = QgsPalLayerSettings()
    pal.fieldName = field_name
    pal.enabled = True

    fmt = QgsTextFormat()
    font = QFont("Segoe UI", int(args.get("font_size") or 9))
    font.setBold(bool(args.get("bold", True)))
    fmt.setFont(font)
    fmt.setSize(float(args.get("font_size") or 9))
    fmt.setColor(QColor(str(args.get("color") or "#0F172A")))

    if args.get("halo", True):
        buf = QgsTextBufferSettings()
        buf.setEnabled(True)
        buf.setSize(1.0)
        buf.setColor(QColor("#FFFFFF"))
        fmt.setBuffer(buf)

    pal.setFormat(fmt)
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    lyr.setLabelsEnabled(True)
    lyr.triggerRepaint()
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()
    return {"layer": lyr.name(), "labels_enabled": True, "field": field_name}


def _tool_zoom_map(iface, args: dict) -> dict:
    if not iface or not iface.mapCanvas():
        return {"error": "Map canvas is not available."}
    canvas = iface.mapCanvas()
    layer_name = str(args.get("layer") or "").strip()
    bbox = args.get("bbox")
    center = args.get("center")

    if layer_name:
        lyr = _resolve_layer(layer_name)
        if lyr is None:
            return {"error": f"Layer '{layer_name}' not found."}
        if bool(args.get("selected_only", False)) and isinstance(lyr, QgsVectorLayer) and lyr.selectedFeatureCount() > 0:
            canvas.zoomToSelected(lyr)
        else:
            ext = canvas.mapSettings().layerToMapCoordinates(lyr, lyr.extent())
            if not ext.isEmpty():
                ext.scale(1.08)
                canvas.setExtent(ext)
        canvas.refresh()
        return {"status": "zoomed_to_layer", "layer": lyr.name()}

    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        rect = QgsRectangle(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        src_crs_str = str(args.get("crs") or "").strip()
        if src_crs_str:
            src_crs = QgsCoordinateReferenceSystem(src_crs_str)
            dst_crs = QgsProject.instance().crs()
            if src_crs.isValid() and dst_crs.isValid() and src_crs != dst_crs:
                xform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
                rect = xform.transformBoundingBox(rect)
        canvas.setExtent(rect)
        canvas.refresh()
        return {"status": "zoomed_to_bbox", "bbox": bbox}

    if isinstance(center, (list, tuple)) and len(center) == 2:
        from qgis.core import QgsPointXY
        pt = QgsPointXY(float(center[0]), float(center[1]))
        canvas.setCenter(pt)
        if args.get("scale"):
            canvas.zoomScale(float(args["scale"]))
        canvas.refresh()
        return {"status": "centered", "center": center}

    canvas.zoomToFullExtent()
    canvas.refresh()
    return {"status": "zoomed_full_extent"}


def _tool_manage_layer_tree(iface, args: dict) -> dict:
    action = str(args.get("action") or "visibility").strip().lower()
    target = str(args.get("layer") or "").strip()
    proj = QgsProject.instance()

    if action == "set_project_crs":
        crs_id = str(args.get("crs") or "EPSG:4326").strip()
        crs = QgsCoordinateReferenceSystem(crs_id)
        if not crs.isValid():
            return {"error": f"Invalid CRS '{crs_id}'."}
        proj.setCrs(crs)
        if iface and iface.mapCanvas():
            iface.mapCanvas().refresh()
        return {"status": "project_crs_updated", "crs": crs.authid()}

    lyr = _resolve_layer(target)
    if lyr is None:
        return {"error": f"Layer '{target}' not found."}

    if action == "remove":
        lid, lname = lyr.id(), lyr.name()
        proj.removeMapLayer(lid)
        if iface and iface.mapCanvas():
            iface.mapCanvas().refresh()
        return {"status": "removed", "layer": lname}

    if action == "rename":
        new_name = str(args.get("new_name") or "").strip()
        if not new_name:
            return {"error": "'new_name' is required for rename action."}
        old_name = lyr.name()
        lyr.setName(new_name)
        return {"status": "renamed", "old_name": old_name, "new_name": new_name}

    # Default: visibility
    visible = bool(args.get("visible", True))
    node = proj.layerTreeRoot().findLayer(lyr.id())
    if node is not None:
        node.setItemVisibilityChecked(visible)
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()
    return {"status": "visibility_updated", "layer": lyr.name(), "visible": visible}


def _tool_run_processing_algorithm(iface, args: dict) -> dict:
    alg_id = str(args.get("algorithm_id") or "").strip()
    params = dict(args.get("parameters") or {})
    load_output = bool(args.get("load_output", True))
    output_name = str(args.get("output_layer_name") or "").strip()

    if not alg_id:
        return {"error": "'algorithm_id' (e.g. 'native:buffer') is required."}

    import processing

    # Resolve layer names to actual QgsMapLayer objects where appropriate
    for k, v in list(params.items()):
        if isinstance(v, str) and not v.startswith("memory:") and not os.path.exists(v):
            resolved = _resolve_layer(v)
            if resolved is not None:
                params[k] = resolved

    if "OUTPUT" not in params:
        params["OUTPUT"] = "TEMPORARY_OUTPUT"

    t0 = time.monotonic()
    feedback = None
    try:
        from qgis.core import QgsProcessingContext, QgsProcessingFeedback
        ctx = QgsProcessingContext()
        ctx.setProject(QgsProject.instance())
        skip_flag = getattr(
            QgsFeatureRequest,
            "GeometrySkipInvalid",
            getattr(getattr(QgsFeatureRequest, "InvalidGeometryCheck", None), "GeometrySkipInvalid", 1),
        )
        try:
            ctx.setInvalidGeometryCheck(skip_flag)
        except Exception:
            pass
        feedback = QgsProcessingFeedback()
        result = processing.run(alg_id, params, context=ctx, feedback=feedback)
    except Exception as exc:
        fb_log = ""
        if feedback is not None:
            try:
                fb_log = feedback.textLog()[-1200:]
            except Exception:
                pass
        return {
            "error": f"Processing algorithm '{alg_id}' failed: {exc}",
            "algorithm_id": alg_id,
            "feedback_log": fb_log,
        }
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    loaded_layers = []
    out_summary: dict[str, Any] = {}
    for k, val in (result or {}).items():
        if isinstance(val, QgsMapLayer):
            if output_name and k == "OUTPUT":
                val.setName(output_name)
            if load_output and QgsProject.instance().mapLayer(val.id()) is None:
                QgsProject.instance().addMapLayer(val)
                loaded_layers.append({"id": val.id(), "name": val.name(), "features": val.featureCount() if isinstance(val, QgsVectorLayer) else None})
            out_summary[k] = f"<Layer: {val.name()} ({val.id()})>"
        elif isinstance(val, str) and os.path.exists(val) and load_output:
            lname = output_name or os.path.splitext(os.path.basename(val))[0]
            ext = os.path.splitext(val)[1].lower()
            if ext in (".tif", ".tiff", ".img", ".asc", ".dem", ".vrt"):
                rlyr = QgsRasterLayer(val, lname)
                if rlyr.isValid():
                    QgsProject.instance().addMapLayer(rlyr)
                    loaded_layers.append({"id": rlyr.id(), "name": rlyr.name(), "type": "raster"})
            else:
                vlyr = QgsVectorLayer(val, lname, "ogr")
                if vlyr.isValid():
                    QgsProject.instance().addMapLayer(vlyr)
                    loaded_layers.append({"id": vlyr.id(), "name": vlyr.name(), "features": vlyr.featureCount()})
            out_summary[k] = val
        else:
            out_summary[k] = _safe_val(val)

    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {
        "algorithm_id": alg_id,
        "elapsed_ms": elapsed_ms,
        "outputs": out_summary,
        "loaded_layers": loaded_layers,
    }


def _tool_search_processing_algorithms(iface, args: dict) -> dict:
    query = str(args.get("query") or "").strip().lower()
    limit = max(1, min(int(args.get("limit") or 20), 60))
    from qgis.core import QgsApplication
    reg = QgsApplication.processingRegistry()
    matches = []
    for alg in reg.algorithms():
        text = f"{alg.id()} {alg.displayName()} {alg.group()} {alg.shortDescription()}".lower()
        if not query or all(part in text for part in query.split()):
            matches.append({
                "id": alg.id(),
                "name": alg.displayName(),
                "group": alg.group(),
                "description": alg.shortDescription() or "",
            })
            if len(matches) >= limit:
                break
    return {"query": query, "count": len(matches), "algorithms": matches}


def _tool_get_algorithm_help(iface, args: dict) -> dict:
    alg_id = str(args.get("algorithm_id") or "").strip()
    from qgis.core import QgsApplication
    alg = QgsApplication.processingRegistry().algorithmById(alg_id)
    if alg is None:
        return {"error": f"Algorithm '{alg_id}' not found in QGIS Processing registry."}
    params = []
    for p in alg.parameterDefinitions():
        params.append({
            "name": p.name(),
            "description": p.description(),
            "type": p.type(),
            "default": _safe_val(p.defaultValue()),
            "optional": bool(p.flags() & p.Flag.FlagOptional) if hasattr(p, "Flag") else False,
        })
    return {
        "id": alg.id(),
        "display_name": alg.displayName(),
        "group": alg.group(),
        "short_description": alg.shortDescription(),
        "parameters": params,
    }


def _tool_spatial_buffer(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    distance = float(args.get("distance") or 100.0)
    dissolve = bool(args.get("dissolve", False))
    output_name = str(args.get("output_name") or f"{target}_buffer_{distance}").strip()

    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}

    return _tool_run_processing_algorithm(iface, {
        "algorithm_id": "native:buffer",
        "parameters": {
            "INPUT": lyr,
            "DISTANCE": distance,
            "SEGMENTS": 16,
            "DISSOLVE": dissolve,
            "OUTPUT": "TEMPORARY_OUTPUT",
        },
        "load_output": True,
        "output_layer_name": output_name,
    })


def _tool_spatial_overlay(iface, args: dict) -> dict:
    op = str(args.get("operation") or "clip").strip().lower()
    input_lyr = _resolve_layer(args.get("input_layer") or "")
    if not isinstance(input_lyr, QgsVectorLayer):
        return {"error": f"Input vector layer '{args.get('input_layer')}' not found."}

    output_name = str(args.get("output_name") or f"{input_lyr.name()}_{op}").strip()

    if op == "dissolve":
        fields = args.get("dissolve_fields") or []
        return _tool_run_processing_algorithm(iface, {
            "algorithm_id": "native:dissolve",
            "parameters": {"INPUT": input_lyr, "FIELD": fields, "OUTPUT": "TEMPORARY_OUTPUT"},
            "load_output": True,
            "output_layer_name": output_name,
        })

    overlay_lyr = _resolve_layer(args.get("overlay_layer") or "")
    if not isinstance(overlay_lyr, QgsVectorLayer):
        return {"error": f"Overlay vector layer '{args.get('overlay_layer')}' not found."}

    alg_map = {
        "clip": "native:clip",
        "intersection": "native:intersection",
        "difference": "native:difference",
        "union": "native:union",
    }
    alg_id = alg_map.get(op, "native:clip")
    return _tool_run_processing_algorithm(iface, {
        "algorithm_id": alg_id,
        "parameters": {"INPUT": input_lyr, "OVERLAY": overlay_lyr, "OUTPUT": "TEMPORARY_OUTPUT"},
        "load_output": True,
        "output_layer_name": output_name,
    })


def _tool_export_layer(iface, args: dict) -> dict:
    target = args.get("layer") or ""
    output_path = str(args.get("output_path") or "").strip()
    lyr = _resolve_layer(target)
    if not isinstance(lyr, QgsVectorLayer):
        return {"error": f"Vector layer '{target}' not found."}
    if not output_path:
        output_path = os.path.join(data_dir(), f"{lyr.name()}.geojson")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    ext = os.path.splitext(output_path)[1].lower()
    driver_map = {
        ".geojson": "GeoJSON",
        ".json": "GeoJSON",
        ".gpkg": "GPKG",
        ".shp": "ESRI Shapefile",
        ".csv": "CSV",
        ".kml": "KML",
    }
    driver = driver_map.get(ext, "GPKG")

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = driver
    options.fileEncoding = "UTF-8"
    if bool(args.get("selected_only", False)):
        options.onlySelectedFeatures = True

    err = QgsVectorFileWriter.writeAsVectorFormatV3(
        lyr,
        output_path,
        QgsProject.instance().transformContext(),
        options,
    )
    code = err[0] if isinstance(err, tuple) else err
    if code != QgsVectorFileWriter.WriterError.NoError:
        msg = err[1] if isinstance(err, tuple) and len(err) > 1 else str(code)
        return {"error": f"Export failed: {msg}"}

    return {"status": "exported", "layer": lyr.name(), "output_path": output_path, "driver": driver}


def _tool_capture_map_canvas(iface, args: dict) -> dict:
    out_dir = os.path.join(data_dir(), "captures")
    os.makedirs(out_dir, exist_ok=True)
    out_path = str(args.get("output_path") or os.path.join(out_dir, f"map_{int(time.time() * 1000)}.png"))

    canvas = iface.mapCanvas() if iface else None
    if canvas is not None:
        try:
            pix = canvas.grab()
            if not pix.isNull():
                pix.save(out_path, "PNG")
                return {
                    "status": "captured",
                    "image_path": out_path,
                    "width": pix.width(),
                    "height": pix.height(),
                }
        except Exception:
            pass
        try:
            canvas.saveAsImage(out_path)
            if os.path.exists(out_path):
                return {"status": "captured", "image_path": out_path}
        except Exception:
            pass

    width = max(320, min(int(args.get("width") or 800), 1600))
    height = max(240, min(int(args.get("height") or 500), 1200))
    image = QImage(QSize(width, height), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#F8FAFC"))
    image.save(out_path, "PNG")
    return {
        "status": "captured",
        "image_path": out_path,
        "width": width,
        "height": height,
    }


def _tool_execute_pyqgis(iface, args: dict) -> dict:
    code = str(args.get("code") or "").strip()
    if not code:
        return {"error": "No Python code provided."}

    stdout_buf = io.StringIO()
    import qgis.core
    import qgis.gui
    try:
        import processing
    except ImportError:
        processing = None

    env: dict[str, Any] = {
        "__builtins__": __builtins__,
        "iface": iface,
        "QgsProject": QgsProject,
        "project": QgsProject.instance(),
        "qgis": qgis,
        "processing": processing,
        "QgsVectorLayer": QgsVectorLayer,
        "QgsRasterLayer": QgsRasterLayer,
        "QgsFeature": QgsFeature,
        "QgsField": QgsField,
        "QgsExpression": QgsExpression,
        "QgsCoordinateReferenceSystem": QgsCoordinateReferenceSystem,
        "QColor": QColor,
        "result": None,
    }

    try:
        with contextlib.redirect_stdout(stdout_buf):
            exec(compile(code, "<AutoGIS_PyQGIS>", "exec"), env, env)
        if iface and iface.mapCanvas():
            iface.mapCanvas().refresh()
        return {
            "status": "executed",
            "stdout": stdout_buf.getvalue()[:8000],
            "result": _safe_val(env.get("result")),
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "traceback": traceback.format_exc()[-2000:],
            "stdout": stdout_buf.getvalue()[:4000],
        }


def _tool_save_project(iface, args: dict) -> dict:
    proj = QgsProject.instance()
    path = str(args.get("path") or proj.fileName() or "").strip()
    if not path:
        return {"error": "Project has not been saved yet; please provide a file 'path' ending in .qgz or .qgs."}
    ok = proj.write(path)
    return {"status": "saved" if ok else "failed", "path": proj.fileName()}


def _tool_update_agent_plan(iface, args: dict) -> dict:
    title = str(args.get("title") or "Autonomous GIS Plan").strip()
    raw_steps = args.get("steps") or []
    cleaned_steps = []
    for idx, item in enumerate(raw_steps, 1):
        if isinstance(item, dict):
            s_text = str(item.get("step") or item.get("title") or f"Step {idx}").strip()
            s_stat = str(item.get("status") or "pending").strip().lower()
        else:
            s_text = str(item).strip()
            s_stat = "pending"
        if s_stat not in ("pending", "in_progress", "completed", "skipped"):
            s_stat = "pending"
        cleaned_steps.append({"step": s_text, "status": s_stat})
    return {
        "status": "plan_updated",
        "plan_title": title,
        "steps": cleaned_steps,
    }


from .document_tools import tool_read_uploaded_file_or_pdf
from .live_data_tools import (
    tool_compute_road_route,
    tool_fetch_osm_features,
    tool_fetch_place_boundary,
    tool_fetch_stac_earth_data,
    tool_list_saved_qgis_connections,
    tool_load_saved_qgis_connection,
)


# ============================================================================
# TOOL REGISTRY BUILDER
# ============================================================================

def build_autogis_tools() -> dict[str, GISToolSpec]:
    specs = [
        GISToolSpec(
            name="read_uploaded_file_or_pdf",
            description="Read, paginate, or search inside any user-uploaded file or folder — including large PDFs (.pdf, GeoPDFs), Word documents (.docx), Excel spreadsheets (.xlsx), CSVs, JSON/GeoJSON, scripts, or entire project folders. Can also load a GeoPDF directly onto the QGIS map canvas.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Full path to the uploaded file or folder."},
                    "start_page": {"type": "integer", "description": "Start page number (for PDFs, default 1) or chunk index."},
                    "end_page": {"type": "integer", "description": "End page number (for PDFs, default 15)."},
                    "search_query": {"type": "string", "description": "Optional keyword/phrase to search across all pages/lines of a large PDF or file."},
                    "load_geopdf_to_map": {"type": "boolean", "description": "If true and the file is a GeoPDF/map PDF, load it as a QGIS layer."},
                },
                "required": ["path"],
            },
            handler=tool_read_uploaded_file_or_pdf,
        ),
        GISToolSpec(
            name="update_agent_plan",
            description="Create or update a visible step-by-step autonomous GIS execution plan checklist in the UI. Call this at the start of multi-step workflows and update step statuses ('pending', 'in_progress', 'completed') as you progress.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short title for the workflow plan."},
                    "steps": {
                        "type": "array",
                        "description": "Ordered list of workflow steps and their current status.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string", "description": "Description of the step."},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "skipped"]},
                            },
                            "required": ["step", "status"],
                        },
                    },
                },
                "required": ["title", "steps"],
            },
            handler=_tool_update_agent_plan,
        ),
        GISToolSpec(
            name="fetch_place_boundary",
            description="Geocode any city, district, state, country, or landmark name worldwide via OpenStreetMap Nominatim/Photon and download its exact administrative Polygon boundary (or Point) directly into QGIS.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "place": {"type": "string", "description": "Place name to search (e.g. 'Jaipur, India', 'Varanasi', 'Delhi', 'New York')."},
                    "layer_name": {"type": "string", "description": "Optional custom layer name."},
                    "zoom": {"type": "boolean", "description": "Zoom map canvas to the boundary (default true)."},
                },
                "required": ["place"],
            },
            handler=tool_fetch_place_boundary,
        ),
        GISToolSpec(
            name="fetch_osm_features",
            description="Download live OpenStreetMap vector features (buildings, roads, rivers, water, railways, landuse, parks, hospitals, schools, power, boundary, or custom OSM tags) for any place name, bbox, or current map canvas via Overpass API and load styled GeoJSON layers into QGIS.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["buildings", "roads", "rivers", "water", "railways", "landuse", "parks", "amenities", "hospitals", "schools", "power", "boundary"],
                        "description": "Category of OSM features to fetch.",
                    },
                    "place": {"type": "string", "description": "City, district, neighborhood, or area name (e.g. 'Connaught Place, New Delhi', 'Udaipur'). If omitted, uses bbox or current map canvas."},
                    "bbox": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Optional [xmin, ymin, xmax, ymax] in EPSG:4326.",
                    },
                    "custom_tag": {"type": "string", "description": "Optional custom Overpass tag filter, e.g. '\"tourism\"=\"hotel\"' or '\"shop\"'."},
                    "limit": {"type": "integer", "description": "Max OSM elements to fetch (default 2500, max 10000)."},
                    "zoom": {"type": "boolean", "description": "Zoom to downloaded layer(s) (default true)."},
                },
                "required": ["category"],
            },
            handler=tool_fetch_osm_features,
        ),
        GISToolSpec(
            name="compute_road_route",
            description="Calculate the real shortest/fastest road network route (driving, walking, or cycling) between an origin and destination (place names or [lon, lat] coordinates) via OSRM and load the route line layer with distance (km) and duration (minutes) into QGIS.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "origin": {"description": "Start place name (e.g. 'India Gate, Delhi') or [lon, lat] array."},
                    "destination": {"description": "Destination place name (e.g. 'Qutub Minar, Delhi') or [lon, lat] array."},
                    "profile": {"type": "string", "enum": ["driving", "walking", "cycling"], "description": "Routing profile (default 'driving')."},
                    "layer_name": {"type": "string", "description": "Optional output layer name."},
                    "zoom": {"type": "boolean", "description": "Zoom to route layer (default true)."},
                },
                "required": ["origin", "destination"],
            },
            handler=tool_compute_road_route,
        ),
        GISToolSpec(
            name="fetch_stac_earth_data",
            description="Search and stream live Cloud-Optimized GeoTIFF (COG) Earth Observation rasters from Microsoft Planetary Computer STAC API directly into QGIS: 'dem' (Copernicus 30m Elevation DEM), 'sentinel2' (10m True Color Satellite Imagery), or 'lulc' (Esri 10m Land Use / Land Cover).",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "dataset": {
                        "type": "string",
                        "enum": ["dem", "sentinel2", "lulc"],
                        "description": "'dem' for Copernicus 30m DEM, 'sentinel2' for Sentinel-2 L2A 10m True Color, 'lulc' for Esri 10m Land Cover.",
                    },
                    "place": {"type": "string", "description": "Optional place name (e.g. 'Dehradun', 'Shimla'). If omitted, uses bbox or current canvas extent."},
                    "bbox": {"type": "array", "items": {"type": "number"}, "description": "Optional [xmin, ymin, xmax, ymax] in EPSG:4326."},
                    "max_cloud_cover": {"type": "number", "description": "For sentinel2: maximum cloud cover percentage (default 20)."},
                    "layer_name": {"type": "string", "description": "Optional display name for the raster layer."},
                    "zoom": {"type": "boolean", "description": "Zoom to loaded raster (default true)."},
                },
                "required": ["dataset"],
            },
            handler=tool_fetch_stac_earth_data,
        ),
        GISToolSpec(
            name="list_saved_qgis_connections",
            description="List all saved XYZ Tile servers, WMS/WMTS servers (e.g. ISRO Bhuvan), WFS servers (e.g. India Biodiversity), and PostGIS database connections configured in the user's QGIS profile.",
            risk="read",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=tool_list_saved_qgis_connections,
        ),
        GISToolSpec(
            name="load_saved_qgis_connection",
            description="Load a layer from the user's saved QGIS XYZ, WMS, or WFS connections by connection name.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "connection_type": {"type": "string", "enum": ["xyz", "wms", "wfs"], "description": "Connection type ('xyz', 'wms', or 'wfs')."},
                    "name": {"type": "string", "description": "Saved connection name (or substring match)."},
                    "typename": {"type": "string", "description": "Optional sub-layer typename for WFS/WMS."},
                },
                "required": ["connection_type", "name"],
            },
            handler=tool_load_saved_qgis_connection,
        ),
        GISToolSpec(
            name="get_project_overview",
            description="Get a full summary of the current QGIS project including CRS, canvas extent, scale, active layer, and all loaded layers.",
            risk="read",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=_tool_get_project_overview,
        ),
        GISToolSpec(
            name="list_layers",
            description="List all vector and raster layers in the current QGIS project with their IDs, names, geometry types, CRS, feature counts, and extents.",
            risk="read",
            parameters={"type": "object", "properties": {}, "required": []},
            handler=_tool_list_layers,
        ),
        GISToolSpec(
            name="inspect_layer",
            description="Inspect a specific layer in detail: field definitions, sample attribute rows, extent, CRS, renderer type, and labeling status.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Layer name or ID."},
                    "sample_limit": {"type": "integer", "description": "Number of sample features to return (default 5)."},
                },
                "required": ["layer"],
            },
            handler=_tool_inspect_layer,
        ),
        GISToolSpec(
            name="query_features",
            description="Query features from a vector layer with an optional QGIS filter expression, field subset, limit, and optional WKT geometry.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Vector layer name or ID."},
                    "filter_expression": {"type": "string", "description": "Optional QGIS filter expression (e.g. \"population > 50000\")."},
                    "fields": {"type": "array", "items": {"type": "string"}, "description": "Optional list of field names to include."},
                    "limit": {"type": "integer", "description": "Max features to return (default 25, max 500)."},
                    "include_geometry": {"type": "boolean", "description": "Whether to include truncated WKT geometry."},
                },
                "required": ["layer"],
            },
            handler=_tool_query_features,
        ),
        GISToolSpec(
            name="compute_field_stats",
            description="Calculate statistical summary (count, min, max, sum, mean, median, std_dev, null count, and top unique values) for a field in a vector layer.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Vector layer name or ID."},
                    "field": {"type": "string", "description": "Attribute field name."},
                },
                "required": ["layer", "field"],
            },
            handler=_tool_compute_field_stats,
        ),
        GISToolSpec(
            name="evaluate_expression",
            description="Evaluate a QGIS expression string against the project or a specific layer.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "QGIS expression to evaluate."},
                    "layer": {"type": "string", "description": "Optional layer name or ID for context."},
                },
                "required": ["expression"],
            },
            handler=_tool_evaluate_expression,
        ),
        GISToolSpec(
            name="select_features",
            description="Select features on a vector layer using a QGIS filter expression and optionally zoom to the selection.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Vector layer name or ID."},
                    "expression": {"type": "string", "description": "Filter expression to select features (pass empty string to clear selection)."},
                    "zoom_to_selection": {"type": "boolean", "description": "Zoom map canvas to selected features (default true)."},
                },
                "required": ["layer", "expression"],
            },
            handler=_tool_select_features,
        ),
        GISToolSpec(
            name="add_basemap",
            description="Add an XYZ web tile basemap to the bottom of the QGIS layer tree.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "basemap": {
                        "type": "string",
                        "enum": ["osm", "google_satellite", "google_hybrid", "esri_satellite", "carto_dark", "carto_light", "opentopomap"],
                        "description": "Basemap provider key.",
                    },
                },
                "required": ["basemap"],
            },
            handler=_tool_add_basemap,
        ),
        GISToolSpec(
            name="load_dataset",
            description="Load a vector, raster, CSV, GeoJSON, GeoPackage, or Shapefile dataset from disk or URL into the QGIS project.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path or data source URI."},
                    "name": {"type": "string", "description": "Optional display name for the layer."},
                    "layer_type": {"type": "string", "enum": ["vector", "raster"], "description": "Optional explicit layer type."},
                    "x_field": {"type": "string", "description": "For CSV files: longitude/X column name."},
                    "y_field": {"type": "string", "description": "For CSV files: latitude/Y column name."},
                    "crs": {"type": "string", "description": "For CSV files: CRS auth ID (default EPSG:4326)."},
                    "zoom": {"type": "boolean", "description": "Zoom to layer after loading (default true)."},
                },
                "required": ["path"],
            },
            handler=_tool_load_dataset,
        ),
        GISToolSpec(
            name="create_memory_layer",
            description="Create a new scratch/memory vector layer (Point, LineString, or Polygon) with custom fields and optional initial features.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the new layer."},
                    "geometry_type": {"type": "string", "enum": ["Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"]},
                    "crs": {"type": "string", "description": "CRS authid (e.g. 'EPSG:4326')."},
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string", "enum": ["string", "int", "double", "bool"]},
                            },
                            "required": ["name"],
                        },
                    },
                    "features": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "wkt": {"type": "string", "description": "WKT geometry string, e.g. 'POINT(77.2 28.6)'."},
                                "attributes": {"type": "object", "description": "Key-value attribute dictionary."},
                            },
                        },
                    },
                },
                "required": ["name", "geometry_type"],
            },
            handler=_tool_create_memory_layer,
        ),
        GISToolSpec(
            name="add_features",
            description="Add one or more features (using WKT geometry and attribute values) to an existing vector layer.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Target vector layer name or ID."},
                    "features": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "wkt": {"type": "string"},
                                "attributes": {"type": "object"},
                            },
                        },
                    },
                },
                "required": ["layer", "features"],
            },
            handler=_tool_add_features,
        ),
        GISToolSpec(
            name="calculate_or_add_field",
            description="Add a new attribute field or update an existing field in a vector layer using a QGIS expression (e.g. '$area / 1000000').",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Vector layer name or ID."},
                    "field_name": {"type": "string", "description": "Field name to create or update."},
                    "field_type": {"type": "string", "enum": ["double", "int", "string"], "description": "Field data type if creating a new field."},
                    "expression": {"type": "string", "description": "QGIS expression to compute values."},
                },
                "required": ["layer", "field_name", "expression"],
            },
            handler=_tool_calculate_or_add_field,
        ),
        GISToolSpec(
            name="delete_features",
            description="Delete features from a vector layer that match a QGIS filter expression.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Vector layer name or ID."},
                    "filter_expression": {"type": "string", "description": "QGIS filter expression selecting features to delete."},
                },
                "required": ["layer", "filter_expression"],
            },
            handler=_tool_delete_features,
        ),
        GISToolSpec(
            name="style_vector_layer",
            description="Apply cartographic styling to a vector layer: 'single' color, 'categorized' by unique field values, 'graduated' choropleth by numeric field, or point 'heatmap'.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Vector layer name or ID."},
                    "style_type": {"type": "string", "enum": ["single", "categorized", "graduated", "heatmap"]},
                    "field": {"type": "string", "description": "Field name (required for categorized and graduated styles)."},
                    "color": {"type": "string", "description": "Hex color for single symbol (e.g. '#00BBF9')."},
                    "outline_color": {"type": "string", "description": "Hex outline color (default '#1E293B')."},
                    "palette": {"type": "string", "enum": ["viridis", "spectral", "reds", "blues", "greens", "magma", "rdylgn", "vibrant"]},
                    "classes": {"type": "integer", "description": "Number of classes for graduated renderer (default 5)."},
                    "size": {"type": "number", "description": "Marker size or line width in mm."},
                    "opacity": {"type": "number", "description": "Layer opacity from 0.1 to 1.0 (default 0.85)."},
                },
                "required": ["layer", "style_type"],
            },
            handler=_tool_style_vector_layer,
        ),
        GISToolSpec(
            name="configure_labels",
            description="Enable, style, or disable text labels on a vector layer.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Vector layer name or ID."},
                    "enabled": {"type": "boolean", "description": "True to show labels, False to hide."},
                    "field": {"type": "string", "description": "Attribute field name to display as label."},
                    "font_size": {"type": "integer", "description": "Font size in points (default 9)."},
                    "color": {"type": "string", "description": "Hex text color (default '#0F172A')."},
                    "halo": {"type": "boolean", "description": "Draw white halo buffer around text (default true)."},
                },
                "required": ["layer"],
            },
            handler=_tool_configure_labels,
        ),
        GISToolSpec(
            name="zoom_map",
            description="Zoom the QGIS map canvas to a layer, bounding box [xmin, ymin, xmax, ymax], or center coordinate [x, y].",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Layer name or ID to zoom to."},
                    "selected_only": {"type": "boolean", "description": "Zoom to selected features of the layer."},
                    "bbox": {"type": "array", "items": {"type": "number"}, "description": "[xmin, ymin, xmax, ymax]."},
                    "crs": {"type": "string", "description": "Optional CRS of bbox (e.g. 'EPSG:4326')."},
                    "center": {"type": "array", "items": {"type": "number"}, "description": "[x, y] center coordinate."},
                    "scale": {"type": "number", "description": "Optional target map scale."},
                },
                "required": [],
            },
            handler=_tool_zoom_map,
        ),
        GISToolSpec(
            name="manage_layer_tree",
            description="Show/hide a layer, rename a layer, remove a layer, or change the project CRS.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["visibility", "rename", "remove", "set_project_crs"]},
                    "layer": {"type": "string", "description": "Layer name or ID."},
                    "visible": {"type": "boolean", "description": "For 'visibility' action: true or false."},
                    "new_name": {"type": "string", "description": "For 'rename' action: new layer name."},
                    "crs": {"type": "string", "description": "For 'set_project_crs' action: CRS auth ID (e.g. 'EPSG:3857')."},
                },
                "required": ["action"],
            },
            handler=_tool_manage_layer_tree,
        ),
        GISToolSpec(
            name="run_processing_algorithm",
            description="Execute any QGIS Processing algorithm (e.g. 'native:buffer', 'native:clip', 'native:intersection', 'native:dissolve', 'native:centroids', 'native:reprojectlayer') and load the result into QGIS.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "algorithm_id": {"type": "string", "description": "Processing algorithm ID, e.g. 'native:buffer'."},
                    "parameters": {"type": "object", "description": "Algorithm input parameters dictionary."},
                    "output_layer_name": {"type": "string", "description": "Optional name for the generated output layer."},
                    "load_output": {"type": "boolean", "description": "Automatically add output layer to project (default true)."},
                },
                "required": ["algorithm_id", "parameters"],
            },
            handler=_tool_run_processing_algorithm,
        ),
        GISToolSpec(
            name="search_processing_algorithms",
            description="Search the QGIS Processing registry by keyword to find algorithm IDs.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword (e.g. 'voronoi', 'kriging', 'shortest path')."},
                    "limit": {"type": "integer", "description": "Max results (default 20)."},
                },
                "required": ["query"],
            },
            handler=_tool_search_processing_algorithms,
        ),
        GISToolSpec(
            name="get_algorithm_help",
            description="Get parameter names, types, and documentation for a specific QGIS Processing algorithm ID.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "algorithm_id": {"type": "string", "description": "Algorithm ID, e.g. 'native:buffer'."},
                },
                "required": ["algorithm_id"],
            },
            handler=_tool_get_algorithm_help,
        ),
        GISToolSpec(
            name="spatial_buffer",
            description="Create a buffer zone around features of a vector layer and add the buffered layer to the project.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Input vector layer name or ID."},
                    "distance": {"type": "number", "description": "Buffer distance in layer CRS units."},
                    "dissolve": {"type": "boolean", "description": "Dissolve overlapping buffers into a single geometry."},
                    "output_name": {"type": "string", "description": "Name for the output buffer layer."},
                },
                "required": ["layer", "distance"],
            },
            handler=_tool_spatial_buffer,
        ),
        GISToolSpec(
            name="spatial_overlay",
            description="Perform spatial overlay operations ('clip', 'intersection', 'difference', 'union', or 'dissolve') on vector layers.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["clip", "intersection", "difference", "union", "dissolve"]},
                    "input_layer": {"type": "string", "description": "Primary input vector layer name or ID."},
                    "overlay_layer": {"type": "string", "description": "Overlay/clip layer name or ID (not needed for dissolve)."},
                    "dissolve_fields": {"type": "array", "items": {"type": "string"}, "description": "Optional field list when operation is 'dissolve'."},
                    "output_name": {"type": "string", "description": "Name for the output layer."},
                },
                "required": ["operation", "input_layer"],
            },
            handler=_tool_spatial_overlay,
        ),
        GISToolSpec(
            name="export_layer",
            description="Export a vector layer to a file on disk (.geojson, .gpkg, .shp, .csv, .kml).",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "layer": {"type": "string", "description": "Vector layer name or ID."},
                    "output_path": {"type": "string", "description": "Destination file path."},
                    "selected_only": {"type": "boolean", "description": "Export only selected features."},
                },
                "required": ["layer", "output_path"],
            },
            handler=_tool_export_layer,
        ),
        GISToolSpec(
            name="capture_map_canvas",
            description="Render and capture the current QGIS map canvas as a PNG image and display it inline in the AutoGIS chat.",
            risk="read",
            parameters={
                "type": "object",
                "properties": {
                    "width": {"type": "integer", "description": "Image width in pixels (default 900)."},
                    "height": {"type": "integer", "description": "Image height in pixels (default 600)."},
                    "background": {"type": "string", "enum": ["light", "dark"], "description": "Canvas background color."},
                },
                "required": [],
            },
            handler=_tool_capture_map_canvas,
        ),
        GISToolSpec(
            name="execute_pyqgis",
            description="Execute custom PyQGIS Python code on the QGIS main thread with `iface`, `QgsProject`, `project`, `processing`, and `qgis.core` pre-imported. Assign to `result` or `print()` to return data.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Valid Python / PyQGIS code to execute."},
                },
                "required": ["code"],
            },
            handler=_tool_execute_pyqgis,
        ),
        GISToolSpec(
            name="save_project",
            description="Save the current QGIS project (.qgz / .qgs) to disk.",
            risk="write",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Optional file path if saving a new project."},
                },
                "required": [],
            },
            handler=_tool_save_project,
        ),
    ]
    return {s.name: s for s in specs}
