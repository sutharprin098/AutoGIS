from __future__ import annotations

import html
import json
import math
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from qgis.core import (
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsFontUtils,
    QgsGradientColorRamp,
    QgsGradientStop,
    QgsLayoutExporter,
    QgsLayoutItemLabel,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsLayoutItemScaleBar,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsMapLayer,
    QgsPrintLayout,
    QgsProject,
    QgsRasterBandStats,
    QgsRasterLayer,
    QgsRasterShader,
    QgsRectangle,
    QgsSingleBandPseudoColorRenderer,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QFont

from .config import data_dir, log_info, log_warn

RASTER_PALETTES: dict[str, list[str]] = {
    "viridis": ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    "rdylgn": ["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#91cf60", "#1a9850"],
    "spectral": ["#d53e4f", "#fc8d59", "#fee08b", "#e6f598", "#99d594", "#3288bd"],
    "terrain": ["#1d4ed8", "#10b981", "#84cc16", "#eab308", "#b45309", "#f8fafc"],
    "reds": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"],
    "blues": ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
    "greens": ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
    "magma": ["#000004", "#51127c", "#b73779", "#fc8961", "#fcfdbf"],
}

INDIA_AND_GLOBAL_SERVICES: dict[str, dict[str, str]] = {
    "esa_worldcover_10m": {
        "title": "ESA WorldCover 10m Land Cover (WMS)",
        "kind": "wms",
        "uri": "contextualWMSLegend=0&crs=EPSG:4326&dpiMode=7&featureCount=10&format=image/png&layers=WORLDCOVER_2021_MAP&styles=&url=https://services.terrascope.be/wms/v2",
    },
    "isro_bhuvan_lulc": {
        "title": "ISRO Bhuvan Land Use Land Cover (WMS)",
        "kind": "wms",
        "uri": "contextualWMSLegend=0&crs=EPSG:4326&dpiMode=7&featureCount=10&format=image/png&layers=lulc:BR_LULC50K_1516&styles=&url=https://bhuvan-vec2.nrsc.gov.in/bhuvan/wms",
    },
    "copernicus_hillshade": {
        "title": "OpenTopoMap Shaded Relief Terrain",
        "kind": "xyz",
        "uri": "type=xyz&url=https://tile.opentopomap.org/{z}/{x}/{y}.png&zmax=17&zmin=0",
    },
    "esri_world_hydro": {
        "title": "Esri World Hydro Reference Overlay",
        "kind": "xyz",
        "uri": "type=xyz&url=https://tiles.arcgis.com/tiles/P3ePLMYs2RVChkJx/arcgis/rest/services/Esri_Hydro_Reference_Overlay/MapServer/tile/{z}/{y}/{x}&zmax=19&zmin=0",
    },
    "esri_world_imagery": {
        "title": "Esri World Imagery (High-Res Satellite)",
        "kind": "xyz",
        "uri": "type=xyz&url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}&zmax=19&zmin=0",
    },
}


def _find_layer(name_or_id: str) -> QgsMapLayer | None:
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


def tool_inspect_raster_layer(iface, args: dict[str, Any]) -> dict[str, Any]:
    """Inspect a raster layer's bands, resolution, CRS, extent, NoData, and band statistics."""
    layer_ref = str(args.get("layer") or "").strip()
    lyr = _find_layer(layer_ref)
    if lyr is None or not isinstance(lyr, QgsRasterLayer):
        return {"error": f"Raster layer '{layer_ref}' not found in the current QGIS project."}

    prov = lyr.dataProvider()
    band_count = lyr.bandCount()
    bands_info: list[dict[str, Any]] = []
    for b in range(1, min(band_count, 12) + 1):
        b_info: dict[str, Any] = {
            "band": b,
            "name": lyr.bandName(b),
        }
        if prov is not None:
            try:
                stats = prov.bandStatistics(b, QgsRasterBandStats.All, lyr.extent(), 0)
                b_info.update({
                    "min": round(float(stats.minimumValue), 6) if math.isfinite(stats.minimumValue) else None,
                    "max": round(float(stats.maximumValue), 6) if math.isfinite(stats.maximumValue) else None,
                    "mean": round(float(stats.mean), 6) if math.isfinite(stats.mean) else None,
                    "std_dev": round(float(stats.stdDev), 6) if math.isfinite(stats.stdDev) else None,
                })
            except Exception as err:
                log_warn(f"Band {b} stats warning: {err}")
            try:
                if prov.sourceHasNoDataValue(b):
                    b_info["nodata"] = prov.sourceNoDataValue(b)
            except Exception as err:
                _ = err
        bands_info.append(b_info)

    ext = lyr.extent()
    return {
        "id": lyr.id(),
        "name": lyr.name(),
        "crs": lyr.crs().authid(),
        "width_px": lyr.width(),
        "height_px": lyr.height(),
        "pixel_size_x": round(lyr.rasterUnitsPerPixelX(), 6),
        "pixel_size_y": round(lyr.rasterUnitsPerPixelY(), 6),
        "band_count": band_count,
        "extent": [
            round(ext.xMinimum(), 6),
            round(ext.yMinimum(), 6),
            round(ext.xMaximum(), 6),
            round(ext.yMaximum(), 6),
        ],
        "bands": bands_info,
    }


def tool_style_raster_layer(iface, args: dict[str, Any]) -> dict[str, Any]:
    """Apply a pseudocolor ramp (Viridis, RdYlGn, Terrain, Spectral, etc.) to a raster layer."""
    layer_ref = str(args.get("layer") or "").strip()
    lyr = _find_layer(layer_ref)
    if lyr is None or not isinstance(lyr, QgsRasterLayer):
        return {"error": f"Raster layer '{layer_ref}' not found in the current QGIS project."}

    band = int(args.get("band") or 1)
    palette_name = str(args.get("palette") or "viridis").strip().lower()
    colors = RASTER_PALETTES.get(palette_name, RASTER_PALETTES["viridis"])
    invert = bool(args.get("invert", False))
    if invert:
        colors = list(reversed(colors))

    prov = lyr.dataProvider()
    if prov is None:
        return {"error": f"Raster layer '{lyr.name()}' has no data provider."}

    min_val = args.get("min_value")
    max_val = args.get("max_value")
    if min_val is None or max_val is None:
        stats = prov.bandStatistics(band, QgsRasterBandStats.All, lyr.extent(), 0)
        if min_val is None:
            min_val = float(stats.minimumValue) if math.isfinite(stats.minimumValue) else 0.0
        if max_val is None:
            max_val = float(stats.maximumValue) if math.isfinite(stats.maximumValue) else 1.0

    min_f = float(min_val)
    max_f = float(max_val)
    if max_f <= min_f:
        max_f = min_f + 1.0

    shader = QgsRasterShader()
    ramp_shader = QgsColorRampShader(min_f, max_f)
    ramp_shader.setColorRampType(QgsColorRampShader.Interpolated)

    items: list[QgsColorRampShader.ColorRampItem] = []
    n = len(colors)
    for idx, hex_col in enumerate(colors):
        frac = idx / max(1, n - 1)
        val = min_f + frac * (max_f - min_f)
        items.append(QgsColorRampShader.ColorRampItem(val, QColor(hex_col), f"{val:.2f}"))
    ramp_shader.setColorRampItemList(items)
    shader.setRasterShaderFunction(ramp_shader)

    renderer = QgsSingleBandPseudoColorRenderer(prov, band, shader)
    opacity = float(args.get("opacity") or 0.9)
    renderer.setOpacity(max(0.1, min(1.0, opacity)))
    lyr.setRenderer(renderer)
    lyr.triggerRepaint()
    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {
        "status": "styled",
        "layer": lyr.name(),
        "band": band,
        "palette": palette_name,
        "min_value": round(min_f, 4),
        "max_value": round(max_f, 4),
        "opacity": opacity,
    }


def tool_compute_zonal_statistics(iface, args: dict[str, Any]) -> dict[str, Any]:
    """Compute zonal statistics (mean, min, max, sum, std) of a raster inside each polygon of a vector layer."""
    vector_ref = str(args.get("zones_layer") or "").strip()
    raster_ref = str(args.get("raster_layer") or "").strip()
    v_lyr = _find_layer(vector_ref)
    r_lyr = _find_layer(raster_ref)
    if v_lyr is None or not isinstance(v_lyr, QgsVectorLayer):
        return {"error": f"Polygon zones layer '{vector_ref}' not found."}
    if r_lyr is None or not isinstance(r_lyr, QgsRasterLayer):
        return {"error": f"Raster layer '{raster_ref}' not found."}

    prefix = str(args.get("column_prefix") or "zonal_").strip()
    band = int(args.get("band") or 1)
    out_name = str(args.get("output_name") or f"{v_lyr.name()}_{r_lyr.name()}_ZonalStats").strip()

    try:
        import processing
    except ImportError as exc:
        return {"error": f"QGIS processing module unavailable: {exc}"}

    out_path = os.path.join(data_dir(), f"zonal_{int(time.time())}.gpkg")
    try:
        res = processing.run(
            "native:zonalstatisticsfb",
            {
                "INPUT": v_lyr,
                "INPUT_RASTER": r_lyr,
                "RASTER_BAND": band,
                "COLUMN_PREFIX": prefix,
                "STATISTICS": [0, 1, 2, 4, 5, 6],  # count, sum, mean, stdev, min, max
                "OUTPUT": out_path,
            },
        )
        out_ref = res.get("OUTPUT")
        out_lyr = out_ref if isinstance(out_ref, QgsVectorLayer) else QgsVectorLayer(str(out_ref), out_name, "ogr")
        if not out_lyr or not out_lyr.isValid():
            return {"error": "Zonal statistics output layer could not be loaded."}
        out_lyr.setName(out_name)
        QgsProject.instance().addMapLayer(out_lyr)
        if iface and iface.mapCanvas():
            iface.mapCanvas().refresh()
        return {
            "status": "completed",
            "output_layer": out_lyr.name(),
            "feature_count": out_lyr.featureCount(),
            "added_fields": [f.name() for f in out_lyr.fields() if f.name().startswith(prefix)],
            "output_path": out_path,
        }
    except Exception as exc:
        return {"error": f"Zonal statistics failed: {exc}"}


def tool_export_publication_map(iface, args: dict[str, Any]) -> dict[str, Any]:
    """Generate a publication-grade 300 DPI cartographic map layout (PDF and PNG) with Title, Legend, Scale Bar, North Arrow, and Attribution."""
    proj = QgsProject.instance()
    title_text = str(args.get("title") or proj.title() or "Geospatial Analysis Map").strip()
    subtitle_text = str(args.get("subtitle") or f"CRS: {proj.crs().authid()} | Generated by AutoGIS Studio").strip()
    dpi = max(96, min(int(args.get("dpi") or 300), 600))
    target_layer_ref = str(args.get("focus_layer") or "").strip()

    layout = QgsPrintLayout(proj)
    layout.initializeDefaults()
    layout.setName(f"AutoGIS_Layout_{int(time.time())}")

    # Page setup: A4 Landscape (297 x 210 mm)
    # Left 215x175mm = Map Frame; Right 65mm = Title + Legend + Scale Bar + Metadata
    map_item = QgsLayoutItemMap(layout)
    map_item.attemptMove(QgsLayoutPoint(10, 22, QgsUnitTypes.LayoutMillimeters))
    map_item.attemptResize(QgsLayoutSize(205, 175, QgsUnitTypes.LayoutMillimeters))
    map_item.setFrameEnabled(True)

    extent: QgsRectangle | None = None
    if target_layer_ref:
        focus_lyr = _find_layer(target_layer_ref)
        if focus_lyr is not None:
            ext = focus_lyr.extent()
            if focus_lyr.crs() != proj.crs():
                try:
                    xform = QgsCoordinateTransform(focus_lyr.crs(), proj.crs(), proj)
                    ext = xform.transformBoundingBox(ext)
                except Exception as err:
                    _ = err
            if not ext.isEmpty():
                ext.scale(1.08)
                extent = ext

    if extent is None and iface and iface.mapCanvas():
        extent = iface.mapCanvas().extent()
    if extent is None or extent.isEmpty():
        extent = QgsRectangle(68.0, 6.0, 97.5, 37.0)

    map_item.setExtent(extent)
    layout.addLayoutItem(map_item)

    # Title Banner
    title_label = QgsLayoutItemLabel(layout)
    title_label.setText(title_text)
    title_font = QFont("Arial", 16, QFont.Weight.Bold)
    title_label.setFont(title_font)
    title_label.attemptMove(QgsLayoutPoint(10, 6, QgsUnitTypes.LayoutMillimeters))
    title_label.attemptResize(QgsLayoutSize(205, 10, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(title_label)

    # Subtitle
    sub_label = QgsLayoutItemLabel(layout)
    sub_label.setText(subtitle_text)
    sub_font = QFont("Arial", 9)
    sub_label.setFont(sub_font)
    sub_label.attemptMove(QgsLayoutPoint(10, 15, QgsUnitTypes.LayoutMillimeters))
    sub_label.attemptResize(QgsLayoutSize(205, 6, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(sub_label)

    # North Arrow Badge
    north_label = QgsLayoutItemLabel(layout)
    north_label.setText("N\n▲")
    north_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
    north_label.setHAlign(Qt.AlignmentFlag.AlignHCenter)
    north_label.attemptMove(QgsLayoutPoint(200, 25, QgsUnitTypes.LayoutMillimeters))
    north_label.attemptResize(QgsLayoutSize(12, 16, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(north_label)

    # Legend on Right Panel
    legend = QgsLayoutItemLegend(layout)
    legend.setTitle("Legend")
    legend.setLinkedMap(map_item)
    legend.setLegendFilterByMapEnabled(True)
    legend.attemptMove(QgsLayoutPoint(220, 22, QgsUnitTypes.LayoutMillimeters))
    legend.attemptResize(QgsLayoutSize(67, 145, QgsUnitTypes.LayoutMillimeters))
    legend.setFrameEnabled(True)
    layout.addLayoutItem(legend)

    # Scale Bar
    scale_bar = QgsLayoutItemScaleBar(layout)
    scale_bar.setStyle("Single Box")
    scale_bar.setLinkedMap(map_item)
    scale_bar.applyDefaultSize()
    scale_bar.attemptMove(QgsLayoutPoint(220, 174, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(scale_bar)

    # Footer / Attribution
    footer = QgsLayoutItemLabel(layout)
    footer.setText(f"Coordinate System: {proj.crs().authid()} | DPI: {dpi} | AutoGIS Studio")
    footer.setFont(QFont("Arial", 8))
    footer.attemptMove(QgsLayoutPoint(10, 199, QgsUnitTypes.LayoutMillimeters))
    footer.attemptResize(QgsLayoutSize(277, 6, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(footer)

    out_dir = os.path.join(data_dir(), "publications")
    os.makedirs(out_dir, exist_ok=True)
    stamp = int(time.time() * 1000)
    png_path = str(args.get("output_png_path") or os.path.join(out_dir, f"publication_map_{stamp}.png"))
    pdf_path = str(args.get("output_pdf_path") or os.path.join(out_dir, f"publication_map_{stamp}.pdf"))

    exporter = QgsLayoutExporter(layout)
    img_settings = QgsLayoutExporter.ImageExportSettings()
    img_settings.dpi = dpi
    exporter.exportToImage(png_path, img_settings)

    pdf_settings = QgsLayoutExporter.PdfExportSettings()
    pdf_settings.dpi = dpi
    exporter.exportToPdf(pdf_path, pdf_settings)

    return {
        "status": "exported",
        "title": title_text,
        "dpi": dpi,
        "image_path": png_path,
        "pdf_path": pdf_path,
    }


def tool_export_interactive_webmap(iface, args: dict[str, Any]) -> dict[str, Any]:
    """Export visible QGIS vector layers into a standalone interactive 3D MapLibre GL JS HTML file."""
    proj = QgsProject.instance()
    title = str(args.get("title") or proj.title() or "AutoGIS Interactive 3D Web Map").strip()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")

    exported_layers: list[dict[str, Any]] = []
    bounds = [180.0, 90.0, -180.0, -90.0]

    for lyr in proj.mapLayers().values():
        if not isinstance(lyr, QgsVectorLayer) or not lyr.isValid():
            continue
        node = proj.layerTreeRoot().findLayer(lyr.id())
        if node is not None and not node.isVisible():
            continue

        xform = None
        if lyr.crs() != wgs84:
            try:
                xform = QgsCoordinateTransform(lyr.crs(), wgs84, proj)
            except Exception as err:
                _ = err

        feats_out: list[dict[str, Any]] = []
        field_names = [f.name() for f in lyr.fields()][:15]
        for idx, feat in enumerate(lyr.getFeatures()):
            if idx >= 5000:
                break
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue
            if xform is not None:
                try:
                    geom.transform(xform)
                except Exception as err:
                    _ = err
                    continue
            bbox = geom.boundingBox()
            bounds[0] = min(bounds[0], bbox.xMinimum())
            bounds[1] = min(bounds[1], bbox.yMinimum())
            bounds[2] = max(bounds[2], bbox.xMaximum())
            bounds[3] = max(bounds[3], bbox.yMaximum())

            props: dict[str, Any] = {}
            for fn in field_names:
                val = feat[fn]
                if val is not None and not (hasattr(val, "isNull") and callable(val.isNull) and val.isNull()):
                    props[fn] = val if isinstance(val, (int, float, str, bool)) else str(val)
            try:
                geom_json = json.loads(geom.asJson())
            except Exception as err:
                _ = err
                continue
            feats_out.append({
                "type": "Feature",
                "properties": props,
                "geometry": geom_json,
            })

        if feats_out:
            exported_layers.append({
                "id": f"lyr_{ len(exported_layers) }",
                "name": lyr.name(),
                "geom_type": lyr.geometryType(),
                "geojson": {"type": "FeatureCollection", "features": feats_out},
            })

    if bounds[0] > bounds[2]:
        bounds = [68.0, 8.0, 97.0, 36.0]

    out_dir = os.path.join(data_dir(), "webmaps")
    os.makedirs(out_dir, exist_ok=True)
    out_path = str(args.get("output_path") or os.path.join(out_dir, f"webmap_{int(time.time())}.html"))

    layers_json = json.dumps(exported_layers, ensure_ascii=False)
    bounds_json = json.dumps(bounds)
    safe_title = html.escape(title)

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>{safe_title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  body, html {{ margin: 0; padding: 0; height: 100%; font-family: system-ui, -apple-system, sans-serif; background: #0f172a; }}
  #map {{ width: 100%; height: 100%; }}
  .panel {{ position: absolute; top: 14px; left: 14px; z-index: 10; background: rgba(15,23,42,0.92); color: #f8fafc;
            padding: 14px 16px; border-radius: 10px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); max-width: 300px; border: 1px solid #334155; }}
  .panel h2 {{ margin: 0 0 8px 0; font-size: 15px; color: #38bdf8; }}
  .layer-row {{ display: flex; align-items: center; gap: 8px; margin: 6px 0; font-size: 13px; }}
</style>
</head>
<body>
<div class="panel">
  <h2>{safe_title}</h2>
  <div id="layers-list"></div>
</div>
<div id="map"></div>
<script>
const LAYERS = {layers_json};
const BOUNDS = {bounds_json};
const COLORS = ["#38bdf8", "#f43f5e", "#10b981", "#f59e0b", "#a855f7", "#06b6d4"];
const map = new maplibregl.Map({{
  container: "map",
  style: "https://tiles.openfreemap.org/styles/liberty",
  bounds: BOUNDS,
  fitBoundsOptions: {{ padding: 48 }}
}});
map.addControl(new maplibregl.NavigationControl({{ visualizePitch: true }}), "top-right");
map.addControl(new maplibregl.ScaleControl(), "bottom-left");
map.on("load", () => {{
  const listEl = document.getElementById("layers-list");
  LAYERS.forEach((lyr, i) => {{
    const col = COLORS[i % COLORS.length];
    map.addSource(lyr.id, {{ type: "geojson", data: lyr.geojson }});
    if (lyr.geom_type === 2) {{
      map.addLayer({{ id: lyr.id, type: "fill", source: lyr.id, paint: {{ "fill-color": col, "fill-opacity": 0.45, "fill-outline-color": "#0f172a" }} }});
    }} else if (lyr.geom_type === 1) {{
      map.addLayer({{ id: lyr.id, type: "line", source: lyr.id, paint: {{ "line-color": col, "line-width": 2.5 }} }});
    }} else {{
      map.addLayer({{ id: lyr.id, type: "circle", source: lyr.id, paint: {{ "circle-radius": 6, "circle-color": col, "circle-stroke-width": 1.5, "circle-stroke-color": "#fff" }} }});
    }}
    map.on("click", lyr.id, (e) => {{
      const props = e.features[0]?.properties || {{}};
      const rows = Object.entries(props).map(([k, v]) => `<b>${{k}}:</b> ${{v}}`).join("<br/>") || lyr.name;
      new maplibregl.Popup().setLngLat(e.lngLat).setHTML(`<div><strong>${{lyr.name}}</strong><hr/>${{rows}}</div>`).addTo(map);
    }});
    const row = document.createElement("label");
    row.className = "layer-row";
    row.innerHTML = `<input type="checkbox" checked data-id="${{lyr.id}}"/> <span style="color:${{col}}">●</span> ${{lyr.name}} (${{lyr.geojson.features.length}})`;
    row.querySelector("input").addEventListener("change", (ev) => {{
      map.setLayoutProperty(lyr.id, "visibility", ev.target.checked ? "visible" : "none");
    }});
    listEl.appendChild(row);
  }});
}});
</script>
</body>
</html>"""

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page_html)

    return {
        "status": "exported",
        "output_path": out_path,
        "layer_count": len(exported_layers),
        "bounds": bounds,
    }


def tool_fetch_live_hazard_feed(iface, args: dict[str, Any], run_on_main=None) -> dict[str, Any]:
    """Fetch live global/regional hazard feeds (USGS Earthquakes or NASA EONET Active Natural Events) and load into QGIS."""
    feed = str(args.get("feed") or "earthquakes_7d").strip().lower()
    bbox = args.get("bbox")

    urls = {
        "earthquakes_24h": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson",
        "earthquakes_7d": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson",
        "earthquakes_30d": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson",
        "nasa_eonet_events": "https://eonet.gsfc.nasa.gov/api/v3/events/geojson?status=open&limit=200",
    }
    url = urls.get(feed, urls["earthquakes_7d"])
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"error": f"Disallowed URL scheme: {parsed.scheme}"}

    req = urllib.request.Request(url, headers={"User-Agent": "AutoGIS-QGIS-Plugin/1.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
        data = json.loads(resp.read().decode("utf-8", errors="replace"))

    features = data.get("features") or []
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        xmin, ymin, xmax, ymax = [float(x) for x in bbox]
        filtered = []
        for f in features:
            coords = (f.get("geometry") or {}).get("coordinates") or []
            if len(coords) >= 2 and isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
                if xmin <= float(coords[0]) <= xmax and ymin <= float(coords[1]) <= ymax:
                    filtered.append(f)
        features = filtered

    out_path = os.path.join(data_dir(), f"hazard_{feed}_{int(time.time())}.geojson")
    fc = {"type": "FeatureCollection", "features": features}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh, ensure_ascii=False)

    layer_name = str(args.get("layer_name") or f"Live_{feed.upper()}").strip()

    def _load() -> dict[str, Any]:
        v_lyr = QgsVectorLayer(out_path, layer_name, "ogr")
        if not v_lyr.isValid():
            return {"error": f"Could not load hazard feed GeoJSON from {out_path}."}
        QgsProject.instance().addMapLayer(v_lyr)
        if iface and iface.mapCanvas():
            iface.mapCanvas().refresh()
        return {
            "status": "loaded",
            "feed": feed,
            "layer": v_lyr.name(),
            "feature_count": v_lyr.featureCount(),
            "path": out_path,
        }

    if callable(run_on_main):
        return run_on_main(_load)
    return _load()


def tool_load_india_national_gis(iface, args: dict[str, Any], run_on_main=None) -> dict[str, Any]:
    """Load authoritative India & Global GIS services (ISRO Bhuvan LULC, ESA WorldCover 10m, Hydro Overlay, Shaded Relief)."""
    service_key = str(args.get("service") or "esa_worldcover_10m").strip().lower()
    entry = INDIA_AND_GLOBAL_SERVICES.get(service_key)
    if entry is None:
        return {
            "error": f"Unknown service '{service_key}'. Available: {', '.join(INDIA_AND_GLOBAL_SERVICES.keys())}"
        }

    def _add() -> dict[str, Any]:
        lyr = QgsRasterLayer(entry["uri"], entry["title"], "wms")
        if not lyr.isValid():
            return {"error": f"Service layer '{entry['title']}' failed to connect."}
        QgsProject.instance().addMapLayer(lyr)
        if iface and iface.mapCanvas():
            iface.mapCanvas().refresh()
        return {
            "status": "loaded",
            "service": service_key,
            "layer": lyr.name(),
        }

    if callable(run_on_main):
        return run_on_main(_add)
    return _add()
