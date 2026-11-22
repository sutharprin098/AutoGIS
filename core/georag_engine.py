from __future__ import annotations

import os
import re
import time
from typing import Any

from qgis.core import (
    QgsExpression,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsFields,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from .config import log_info, log_warn


def execute_georag_query(
    iface,
    query_text: str,
    target_layer_or_database: str = "",
    create_result_layer: bool = True,
    output_layer_name: str = "",
) -> dict[str, Any]:
    """Execute GeoRAG Spatial Database Query over local vector layers, GeoPackage, or SpatiaLite.
    
    Translates natural language spatial intent or Spatial SQL queries into executed spatial selections,
    attribute filters, and new vector sub-layers.
    """
    t0 = time.monotonic()
    proj = QgsProject.instance()

    # 1. Resolve Target Layer
    lyr: QgsVectorLayer | None = None
    if target_layer_or_database:
        for l in proj.mapLayers().values():
            if isinstance(l, QgsVectorLayer) and (l.name() == target_layer_or_database or l.id() == target_layer_or_database):
                lyr = l
                break

    if lyr is None and iface and iface.activeLayer() and isinstance(iface.activeLayer(), QgsVectorLayer):
        lyr = iface.activeLayer()

    if lyr is None:
        for l in proj.mapLayers().values():
            if isinstance(l, QgsVectorLayer):
                lyr = l
                break

    if lyr is None or not lyr.isValid():
        return {
            "error": "No valid vector layer available for GeoRAG spatial query. Please load a layer first."
        }

    # 2. Translate Natural Language or Spatial SQL into QGIS Filter Expression
    q_lower = query_text.lower().strip()
    expr_str = ""

    # Check for direct SQL SELECT ... WHERE clause
    where_match = re.search(r"where\s+(.+)$", query_text, re.IGNORECASE)
    if where_match:
        raw_where = where_match.group(1).strip()
        # Clean standard SQL dialect to QGIS Expression syntax
        cleaned_where = re.sub(r"\bST_Area\(geom\)", "$area", raw_where, flags=re.IGNORECASE)
        cleaned_where = re.sub(r"\bST_Length\(geom\)", "$length", cleaned_where, flags=re.IGNORECASE)
        cleaned_where = re.sub(r"\barea\b", "$area", cleaned_where, flags=re.IGNORECASE)
        cleaned_where = re.sub(r"\blength\b", "$length", cleaned_where, flags=re.IGNORECASE)
        expr_str = cleaned_where
    else:
        # Heuristic Natural Language to Expression Translation
        available_fields = [f.name() for f in lyr.fields()]
        field_names_lower = {f.name().lower(): f.name() for f in lyr.fields()}

        # Numerical comparison patterns (e.g. area > 500, population < 10000)
        num_patterns = [
            (r"(?:area|area_sqm|shape_area)\s*(>|<|>=|<=|=)\s*(\d+(?:\.\d+)?)", lambda op, val: f"$area {op} {val}"),
            (r"(?:length|perimeter)\s*(>|<|>=|<=|=)\s*(\d+(?:\.\d+)?)", lambda op, val: f"$length {op} {val}"),
        ]

        clauses = []
        for pat, builder in num_patterns:
            m = re.search(pat, q_lower)
            if m:
                clauses.append(builder(m.group(1), m.group(2)))

        # Attribute field matches (e.g. "where state is Rajasthan" or "type = residential")
        for fn_lower, fn_orig in field_names_lower.items():
            field_match = re.search(rf"\b{fn_lower}\b\s*(?:is|=|==|contains)\s*['\"]?([a-zA-Z0-9_\s]+)['\"]?", q_lower)
            if field_match:
                val = field_match.group(1).strip()
                clauses.append(f'"{fn_orig}" ILIKE \'%{val}%\'')

        if clauses:
            expr_str = " AND ".join(clauses)
        else:
            # Fallback: Top features or non-null geometry
            expr_str = "$geometry IS NOT NULL"

    # 3. Execute Filter Query
    expr = QgsExpression(expr_str)
    req = QgsFeatureRequest(expr)

    matching_features: list[QgsFeature] = []
    for f in lyr.getFeatures(req):
        matching_features.append(QgsFeature(f))
        if len(matching_features) >= 5000:
            break

    # 4. Optional Result Layer Creation
    res_layer_name = output_layer_name or f"GeoRAG_Result_{lyr.name()}"
    if create_result_layer and matching_features:
        crs_authid = lyr.crs().authid() if lyr.crs().isValid() else "EPSG:4326"
        geom_type = lyr.geometryType()
        type_str = {0: "Point", 1: "LineString", 2: "Polygon", 3: "Unknown"}.get(int(geom_type), "Polygon")
        out_vlyr = QgsVectorLayer(f"{type_str}?crs={crs_authid}&index=yes", res_layer_name, "memory")
        out_pr = out_vlyr.dataProvider()
        out_pr.addAttributes(lyr.fields().toList())
        out_vlyr.updateFields()
        out_pr.addFeatures(matching_features)
        out_vlyr.updateExtents()
        proj.addMapLayer(out_vlyr)

    # Highlight / select matching features on canvas
    if iface:
        lyr.selectByIds([f.id() for f in matching_features])
        if iface.mapCanvas():
            iface.mapCanvas().refresh()

    elapsed = int((time.monotonic() - t0) * 1000)
    log_info(f"GeoRAG: Executed spatial query '{expr_str}' -> {len(matching_features)} features in {elapsed}ms")

    return {
        "status": "success",
        "query_text": query_text,
        "translated_expression": expr_str,
        "source_layer": lyr.name(),
        "total_source_features": lyr.featureCount(),
        "matching_features_count": len(matching_features),
        "result_layer": res_layer_name if (create_result_layer and matching_features) else None,
        "elapsed_ms": elapsed,
    }
