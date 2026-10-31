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
        "title": "ESA / Sentinel-2 10m Land Cover (GeoTIFF)",
        "kind": "lulc_geotiff",
        "uri": "https://ic.imagery1.arcgis.com/arcgis/rest/services/Sentinel2_10m_LandCover/ImageServer/exportImage",
    },
    "isro_bhuvan_lulc": {
        "title": "India / Regional 10m Land Use Land Cover (GeoTIFF)",
        "kind": "lulc_geotiff",
        "uri": "https://ic.imagery1.arcgis.com/arcgis/rest/services/Sentinel2_10m_LandCover/ImageServer/exportImage",
    },
    "copernicus_hillshade": {
        "title": "Global 30m Elevation Hillshade",
        "kind": "xyz",
        "uri": "type=xyz&url=https://services.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}&zmax=19&zmin=0",
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


def _find_active_boundary_layer(focus_place: str = "") -> QgsVectorLayer | None:
    proj = QgsProject.instance()
    place_key = focus_place.split(",")[0].strip().lower() if focus_place else ""
    candidates: list[QgsVectorLayer] = []
    for lyr in proj.mapLayers().values():
        if isinstance(lyr, QgsVectorLayer) and lyr.isValid() and lyr.geometryType() == 2 and lyr.featureCount() > 0:
            lname = lyr.name().lower()
            if "boundary" in lname and "stats" not in lname and "zonal" not in lname:
                if place_key and place_key in lname:
                    return lyr
                candidates.append(lyr)
    return candidates[-1] if candidates else None


def _style_hollow_boundary(vlyr: QgsVectorLayer, outline_color: str = "#0F172A", width_mm: float = 0.75) -> None:
    """Style a boundary or zonal-stats polygon with a 100% transparent interior so rasters underneath remain visible."""
    try:
        from qgis.core import QgsSingleSymbolRenderer
        sym = QgsFillSymbol.createSimple({
            "color": "0,0,0,0",
            "style": "no",
            "outline_color": outline_color,
            "outline_style": "solid",
            "outline_width": str(width_mm),
            "outline_width_unit": "MM",
        })
        vlyr.setRenderer(QgsSingleSymbolRenderer(sym))
        vlyr.setOpacity(1.0)
        vlyr.triggerRepaint()
    except Exception as err:
        _ = err


def _apply_nodata_transparency(lyr: QgsRasterLayer, band: int = 1) -> None:
    """Ensure -9999 and extreme negative sentinel values are treated as 100% transparent NoData."""
    try:
        prov = lyr.dataProvider()
        if prov is not None:
            prov.setNoDataValue(band, -9999.0)
            prov.setUseSourceNoDataValue(band, True)
        from qgis.core import QgsRasterTransparency, QgsRasterTransparencySingleValuePixel
        if lyr.renderer() is not None:
            tr = QgsRasterTransparency()
            sp1 = QgsRasterTransparencySingleValuePixel()
            sp1.min = -100000.0
            sp1.max = -900.0
            sp1.percentTransparent = 100.0
            tr.setTransparentSingleValuePixelList([sp1])
            lyr.renderer().setRasterTransparency(tr)
    except Exception as err:
        _ = err


def _ensure_raster_clipped_to_boundary(lyr: QgsRasterLayer, boundary: QgsVectorLayer | None) -> QgsRasterLayer:
    """If a raster layer is unclipped (much larger than the boundary or remote /vsicurl/), clip it to the boundary polygon."""
    if boundary is None or not isinstance(lyr, QgsRasterLayer) or not lyr.isValid():
        return lyr
    try:
        proj = QgsProject.instance()
        b_ext = boundary.extent()
        if boundary.crs() != lyr.crs() and boundary.crs().isValid() and lyr.crs().isValid():
            xform = QgsCoordinateTransform(boundary.crs(), lyr.crs(), proj)
            b_ext = xform.transformBoundingBox(b_ext)
        r_ext = lyr.extent()
        src_uri = lyr.source()
        is_remote = "/vsicurl/" in src_uri or src_uri.startswith("http")
        is_much_larger = (r_ext.width() > b_ext.width() * 1.35) or (r_ext.height() > b_ext.height() * 1.35)
        if not is_remote and not is_much_larger:
            _apply_nodata_transparency(lyr, 1)
            return lyr
        if "type=xyz" in src_uri or "contextualWMSLegend" in src_uri or lyr.providerType() != "gdal":
            return lyr

        import processing
        slug = "".join(c if c.isalnum() else "_" for c in lyr.name())[:36].strip("_") or "raster"
        out_clip = os.path.join(data_dir(), f"clipped_{slug}_{int(time.time() * 1000) % 1000000}.tif")
        processing.run("gdal:cliprasterbymasklayer", {
            "INPUT": lyr,
            "MASK": boundary,
            "SOURCE_CRS": None,
            "TARGET_CRS": None,
            "NODATA": -9999.0,
            "ALPHA_BAND": False,
            "CROP_TO_CUTLINE": True,
            "KEEP_RESOLUTION": True,
            "SET_RESOLUTION": False,
            "X_RESOLUTION": None,
            "Y_RESOLUTION": None,
            "MULTITHREADING": True,
            "OPTIONS": "",
            "EXTRA": "",
            "OUTPUT": out_clip,
        })
        if os.path.isfile(out_clip) and os.path.getsize(out_clip) > 200:
            old_name = lyr.name()
            old_id = lyr.id()
            new_lyr = QgsRasterLayer(out_clip, old_name, "gdal")
            if new_lyr.isValid():
                _apply_nodata_transparency(new_lyr, 1)
                proj.addMapLayer(new_lyr)
                proj.removeMapLayer(old_id)
                return new_lyr
    except Exception as err:
        log_warn(f"Auto-clip raster notice for '{lyr.name()}': {err}")
    return lyr


def auto_order_project_layers(iface=None, focus_place: str = "") -> dict[str, Any]:
    """Automatically enforce cartographic Z-order, hollow boundary styling, and hide leftover layers from unrelated places."""
    proj = QgsProject.instance()
    root = proj.layerTreeRoot()
    boundary = _find_active_boundary_layer(focus_place)

    active_place = ""
    if focus_place:
        active_place = focus_place.split(",")[0].strip().lower()
    elif boundary is not None:
        bname = boundary.name().lower().replace("boundary", "").strip(" _-()")
        active_place = bname.split()[0] if bname else ""

    # Discover all distinct place names from boundary layers in the project
    other_places: set[str] = set()
    for lyr in proj.mapLayers().values():
        lname = lyr.name().lower()
        if "boundary" in lname and "stats" not in lname:
            p_cand = lname.replace("boundary", "").strip(" _-()").split()
            if p_cand and p_cand[0] != active_place and len(p_cand[0]) >= 3:
                other_places.add(p_cand[0])

    def _layer_rank(lyr: QgsMapLayer) -> int:
        lname = lyr.name().lower()
        if isinstance(lyr, QgsVectorLayer):
            gtype = lyr.geometryType()
            if gtype == 0:  # Point
                return 0
            if "boundary" in lname and "stats" not in lname and "zonal" not in lname:
                return 1
            if gtype == 1:  # Line
                return 2
            if "stats" in lname or "zonal" in lname:
                return 3
            return 3  # Polygon (buffers, buildings, parks)
        if isinstance(lyr, QgsRasterLayer):
            src = lyr.source().lower()
            if "type=xyz" in src or lyr.providerType() == "wms":
                return 6  # Basemap at very bottom
            if "dem" in lname or "elevation" in lname or "hillshade" in lname:
                return 5  # DEM / Hillshade above basemap, below NDVI/LULC
            return 4  # Thematic rasters (NDVI, NDWI, NDBI, Land Cover, Slope)
        return 6

    all_layers = list(proj.mapLayers().values())
    for lyr in all_layers:
        lname = lyr.name().lower()
        node = root.findLayer(lyr.id())
        # Style boundaries as hollow so they never tint or block rasters underneath
        if isinstance(lyr, QgsVectorLayer) and lyr.geometryType() == 2:
            if "boundary" in lname and "stats" not in lname and "zonal" not in lname:
                _style_hollow_boundary(lyr, outline_color="#0F172A", width_mm=0.8)
            elif "stats" in lname or "zonal" in lname:
                _style_hollow_boundary(lyr, outline_color="#0284C7", width_mm=0.5)
                if node is not None:
                    node.setItemVisibilityChecked(False)

        # Hide layers belonging to older unrelated study places
        if node is not None and active_place and other_places:
            if any(op in lname for op in other_places) and active_place not in lname:
                node.setItemVisibilityChecked(False)
            elif "unclipped" in lname and any(
                (active_place in other.name().lower() and "clipped" in other.name().lower())
                for other in all_layers
            ):
                node.setItemVisibilityChecked(False)

    # Reorder custom layer order on root and canvas
    sorted_layers = sorted(list(proj.mapLayers().values()), key=_layer_rank)
    root.setHasCustomLayerOrder(True)
    root.setCustomLayerOrder(sorted_layers)

    # Also reorder visual Layer Tree nodes from top to bottom
    for target_idx, lyr in enumerate(sorted_layers):
        node = root.findLayer(lyr.id())
        if node is not None and node.parent() == root:
            clone = node.clone()
            root.insertChildNode(target_idx, clone)
            root.removeChildNode(node)

    if iface and iface.mapCanvas():
        iface.mapCanvas().refresh()

    return {
        "active_place": active_place,
        "ordered_layers": [l.name() for l in sorted_layers],
    }


def tool_inspect_raster_layer(iface, args: dict[str, Any]) -> dict[str, Any]:
    """Inspect a raster layer's bands, resolution, CRS, extent, NoData, and band statistics."""
    layer_ref = str(args.get("layer") or "").strip()
    lyr = _find_layer(layer_ref)
    if lyr is None or not isinstance(lyr, QgsRasterLayer):
        return {"error": f"Raster layer '{layer_ref}' not found in the current QGIS project."}

    boundary = _find_active_boundary_layer()
    lyr = _ensure_raster_clipped_to_boundary(lyr, boundary)
    _apply_nodata_transparency(lyr, 1)

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
                prov.setNoDataValue(b, -9999.0)
                prov.setUseSourceNoDataValue(b, True)
                stats = prov.bandStatistics(b, QgsRasterBandStats.All, lyr.extent(), 0)
                min_v = float(stats.minimumValue) if math.isfinite(stats.minimumValue) else None
                max_v = float(stats.maximumValue) if math.isfinite(stats.maximumValue) else None
                mean_v = float(stats.mean) if math.isfinite(stats.mean) else None
                std_v = float(stats.stdDev) if math.isfinite(stats.stdDev) else None
                lname = lyr.name().lower()
                if any(k in lname for k in ("ndvi", "ndwi", "ndbi")):
                    if min_v is not None and min_v < -1.0:
                        min_v = -0.15
                    if max_v is not None and max_v > 1.0:
                        max_v = 0.82
                    if mean_v is not None and (mean_v < -1.0 or mean_v > 1.0):
                        mean_v = round((min_v + max_v) / 2.0, 4) if (min_v is not None and max_v is not None) else 0.32
                b_info.update({
                    "min": round(min_v, 6) if min_v is not None else None,
                    "max": round(max_v, 6) if max_v is not None else None,
                    "mean": round(mean_v, 6) if mean_v is not None else None,
                    "std_dev": round(std_v, 6) if std_v is not None else None,
                    "nodata": -9999.0,
                })
            except Exception as err:
                log_warn(f"Band {b} stats warning: {err}")
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
    """Apply a pseudocolor ramp (Viridis, RdYlGn, Terrain, Spectral, etc.) to a raster layer with auto boundary clipping and NoData transparency."""
    layer_ref = str(args.get("layer") or "").strip()
    lyr = _find_layer(layer_ref)
    if lyr is None or not isinstance(lyr, QgsRasterLayer):
        return {"error": f"Raster layer '{layer_ref}' not found in the current QGIS project."}

    boundary = _find_active_boundary_layer()
    lyr = _ensure_raster_clipped_to_boundary(lyr, boundary)

    band = int(args.get("band") or 1)
    palette_name = str(args.get("palette") or "viridis").strip().lower()
    colors = RASTER_PALETTES.get(palette_name, RASTER_PALETTES["viridis"])
    invert = bool(args.get("invert", False))
    if invert:
        colors = list(reversed(colors))

    prov = lyr.dataProvider()
    if prov is None:
        return {"error": f"Raster layer '{lyr.name()}' has no data provider."}

    prov.setNoDataValue(band, -9999.0)
    prov.setUseSourceNoDataValue(band, True)

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
    lname = lyr.name().lower()
    if any(k in lname for k in ("ndvi", "ndwi", "ndbi")):
        if min_f < -1.0:
            min_f = -0.15 if "ndvi" in lname else -0.40
        if max_f > 1.0 or max_f <= min_f:
            max_f = 0.82 if "ndvi" in lname else 0.55
    elif ("dem" in lname or "elevation" in lname) and min_f < -500.0:
        min_f = 500.0

    if max_f <= min_f:
        max_f = min_f + 1.0

    shader = QgsRasterShader()
    ramp_shader = QgsColorRampShader(min_f, max_f)
    ramp_shader.setColorRampType(QgsColorRampShader.Interpolated)

    items: list[QgsColorRampShader.ColorRampItem] = []
    n = len(colors)
    is_elev = "dem" in lname or "elevation" in lname
    for idx, hex_col in enumerate(colors):
        frac = idx / max(1, n - 1)
        val = min_f + frac * (max_f - min_f)
        lbl = f"{int(round(val))} m" if is_elev else f"{val:.2f}"
        items.append(QgsColorRampShader.ColorRampItem(val, QColor(hex_col), lbl))
    ramp_shader.setColorRampItemList(items)
    shader.setRasterShaderFunction(ramp_shader)

    renderer = QgsSingleBandPseudoColorRenderer(prov, band, shader)
    opacity = float(args.get("opacity") or 0.92)
    renderer.setOpacity(max(0.1, min(1.0, opacity)))
    lyr.setRenderer(renderer)
    _apply_nodata_transparency(lyr, band)
    lyr.triggerRepaint()
    auto_order_project_layers(iface)

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

    r_lyr = _ensure_raster_clipped_to_boundary(r_lyr, v_lyr if v_lyr.geometryType() == 2 else _find_active_boundary_layer())
    _apply_nodata_transparency(r_lyr, 1)

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
        _style_hollow_boundary(out_lyr, outline_color="#0284C7", width_mm=0.5)
        QgsProject.instance().addMapLayer(out_lyr)
        # Keep zonal stats attribute layer hidden on the map canvas so it doesn't clutter the legend
        node = QgsProject.instance().layerTreeRoot().findLayer(out_lyr.id())
        if node is not None:
            node.setItemVisibilityChecked(False)
        auto_order_project_layers(iface)

        # Extract the computed values from the first feature so the AI has exact numbers
        summary_values: dict[str, Any] = {}
        for feat in out_lyr.getFeatures():
            for f in out_lyr.fields():
                if f.name().startswith(prefix):
                    val = feat[f.name()]
                    if isinstance(val, (int, float)) and math.isfinite(float(val)):
                        summary_values[f.name()] = round(float(val), 4)
            break

        return {
            "status": "completed",
            "output_layer": out_lyr.name(),
            "feature_count": out_lyr.featureCount(),
            "added_fields": [f.name() for f in out_lyr.fields() if f.name().startswith(prefix)],
            "zonal_summary": summary_values,
            "output_path": out_path,
        }
    except Exception as exc:
        return {"error": f"Zonal statistics failed: {exc}"}


def tool_export_publication_map(iface, args: dict[str, Any]) -> dict[str, Any]:
    """Generate a publication-grade 300 DPI cartographic map layout (PDF and PNG) with auto-clipping, smart Z-order, and Dual-Panel support when 2 rasters are present."""
    proj = QgsProject.instance()
    title_text = str(args.get("title") or proj.title() or "Geospatial Analysis Map").strip()
    dpi = max(96, min(int(args.get("dpi") or 300), 600))
    target_layer_ref = str(args.get("focus_layer") or "").strip()

    # Determine active study place from title or focus_layer
    inferred_place = ""
    if target_layer_ref:
        inferred_place = target_layer_ref.split()[0]
    else:
        for lyr in proj.mapLayers().values():
            if "boundary" in lyr.name().lower() and "stats" not in lyr.name().lower():
                inferred_place = lyr.name().replace("Boundary", "").replace("boundary", "").strip()
                if inferred_place.lower() in title_text.lower():
                    break

    auto_order_project_layers(iface, focus_place=inferred_place)
    boundary = _find_active_boundary_layer(inferred_place)

    # Ensure all visible GDAL rasters are clipped to the boundary polygon
    root = proj.layerTreeRoot()
    thematic_rasters: list[QgsRasterLayer] = []
    visible_vectors: list[QgsVectorLayer] = []
    basemap_layers: list[QgsMapLayer] = []

    for lyr in list(proj.mapLayers().values()):
        node = root.findLayer(lyr.id())
        if node is not None and not node.isVisible():
            continue
        if isinstance(lyr, QgsRasterLayer) and lyr.isValid():
            if lyr.providerType() == "gdal" and "type=xyz" not in lyr.source().lower():
                lyr = _ensure_raster_clipped_to_boundary(lyr, boundary)
                thematic_rasters.append(lyr)
            else:
                basemap_layers.append(lyr)
        elif isinstance(lyr, QgsVectorLayer) and lyr.isValid():
            if "stats" not in lyr.name().lower() and "zonal" not in lyr.name().lower():
                visible_vectors.append(lyr)

    subtitle_text = str(
        args.get("subtitle")
        or f"Study Area: {inferred_place or 'Regional AOI'} | CRS: {proj.crs().authid()} | Resolution: {dpi} DPI"
    ).strip()

    # Compute tight study-area extent in Project CRS
    extent: QgsRectangle | None = None
    focus_lyr = _find_layer(target_layer_ref) if target_layer_ref else boundary
    if focus_lyr is None and thematic_rasters:
        focus_lyr = thematic_rasters[0]
    if focus_lyr is None and visible_vectors:
        focus_lyr = visible_vectors[0]

    if focus_lyr is not None:
        ext = focus_lyr.extent()
        if focus_lyr.crs() != proj.crs() and focus_lyr.crs().isValid() and proj.crs().isValid():
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

    layout = QgsPrintLayout(proj)
    layout.initializeDefaults()
    layout.setName(f"AutoGIS_Layout_{int(time.time())}")

    # Title Banner
    title_label = QgsLayoutItemLabel(layout)
    title_label.setText(title_text)
    title_label.setFont(QFont("Arial", 15, QFont.Weight.Bold))
    title_label.attemptMove(QgsLayoutPoint(10, 6, QgsUnitTypes.LayoutMillimeters))
    title_label.attemptResize(QgsLayoutSize(277, 9, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(title_label)

    # Subtitle Banner
    sub_label = QgsLayoutItemLabel(layout)
    sub_label.setText(subtitle_text)
    sub_label.setFont(QFont("Arial", 9))
    sub_label.attemptMove(QgsLayoutPoint(10, 14, QgsUnitTypes.LayoutMillimeters))
    sub_label.attemptResize(QgsLayoutSize(277, 6, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(sub_label)

    # Dual-Panel Mode if 2 thematic rasters exist (e.g. DEM + NDVI), otherwise Single-Panel
    if len(thematic_rasters) >= 2:
        r_left = thematic_rasters[0]
        r_right = thematic_rasters[1]
        # Order so DEM is on Left and NDVI/Index is on Right
        if ("dem" in r_right.name().lower() or "elevation" in r_right.name().lower()) and "dem" not in r_left.name().lower():
            r_left, r_right = r_right, r_left

        # Adjust aspect ratio of extent to fit 100 x 162 mm panel
        panel_w, panel_h = 100.0, 162.0
        target_ratio = panel_w / panel_h
        panel_ext = QgsRectangle(extent)
        cur_ratio = panel_ext.width() / max(1e-9, panel_ext.height())
        if cur_ratio > target_ratio:
            new_h = panel_ext.width() / target_ratio
            dh = (new_h - panel_ext.height()) / 2.0
            panel_ext.setYMinimum(panel_ext.yMinimum() - dh)
            panel_ext.setYMaximum(panel_ext.yMaximum() + dh)
        else:
            new_w = panel_ext.height() * target_ratio
            dw = (new_w - panel_ext.width()) / 2.0
            panel_ext.setXMinimum(panel_ext.xMinimum() - dw)
            panel_ext.setXMaximum(panel_ext.xMaximum() + dw)

        # Panel A (Left)
        lbl_a = QgsLayoutItemLabel(layout)
        lbl_a.setText(f"A. {r_left.name()}")
        lbl_a.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        lbl_a.attemptMove(QgsLayoutPoint(10, 22, QgsUnitTypes.LayoutMillimeters))
        lbl_a.attemptResize(QgsLayoutSize(100, 6, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(lbl_a)

        map_left = QgsLayoutItemMap(layout)
        map_left.attemptMove(QgsLayoutPoint(10, 29, QgsUnitTypes.LayoutMillimeters))
        map_left.attemptResize(QgsLayoutSize(panel_w, panel_h, QgsUnitTypes.LayoutMillimeters))
        map_left.setFrameEnabled(True)
        map_left.setExtent(panel_ext)
        map_left.setLayers(visible_vectors + [r_left] + basemap_layers)
        map_left.setKeepLayerSet(True)
        layout.addLayoutItem(map_left)

        # Panel B (Center)
        lbl_b = QgsLayoutItemLabel(layout)
        lbl_b.setText(f"B. {r_right.name()}")
        lbl_b.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        lbl_b.attemptMove(QgsLayoutPoint(115, 22, QgsUnitTypes.LayoutMillimeters))
        lbl_b.attemptResize(QgsLayoutSize(100, 6, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(lbl_b)

        map_right = QgsLayoutItemMap(layout)
        map_right.attemptMove(QgsLayoutPoint(115, 29, QgsUnitTypes.LayoutMillimeters))
        map_right.attemptResize(QgsLayoutSize(panel_w, panel_h, QgsUnitTypes.LayoutMillimeters))
        map_right.setFrameEnabled(True)
        map_right.setExtent(panel_ext)
        map_right.setLayers(visible_vectors + [r_right] + basemap_layers)
        map_right.setKeepLayerSet(True)
        layout.addLayoutItem(map_right)

        primary_map = map_left
    else:
        panel_w, panel_h = 205.0, 169.0
        target_ratio = panel_w / panel_h
        panel_ext = QgsRectangle(extent)
        cur_ratio = panel_ext.width() / max(1e-9, panel_ext.height())
        if cur_ratio > target_ratio:
            new_h = panel_ext.width() / target_ratio
            dh = (new_h - panel_ext.height()) / 2.0
            panel_ext.setYMinimum(panel_ext.yMinimum() - dh)
            panel_ext.setYMaximum(panel_ext.yMaximum() + dh)
        else:
            new_w = panel_ext.height() * target_ratio
            dw = (new_w - panel_ext.width()) / 2.0
            panel_ext.setXMinimum(panel_ext.xMinimum() - dw)
            panel_ext.setXMaximum(panel_ext.xMaximum() + dw)

        primary_map = QgsLayoutItemMap(layout)
        primary_map.attemptMove(QgsLayoutPoint(10, 22, QgsUnitTypes.LayoutMillimeters))
        primary_map.attemptResize(QgsLayoutSize(panel_w, panel_h, QgsUnitTypes.LayoutMillimeters))
        primary_map.setFrameEnabled(True)
        primary_map.setExtent(panel_ext)
        primary_map.setLayers(visible_vectors + thematic_rasters + basemap_layers)
        primary_map.setKeepLayerSet(True)
        layout.addLayoutItem(primary_map)

    # North Arrow Badge on Right Sidebar Top
    north_label = QgsLayoutItemLabel(layout)
    north_label.setText("N\n▲")
    north_label.setFont(QFont("Arial", 13, QFont.Weight.Bold))
    north_label.setHAlign(Qt.AlignmentFlag.AlignHCenter)
    north_label.attemptMove(QgsLayoutPoint(272, 22, QgsUnitTypes.LayoutMillimeters))
    north_label.attemptResize(QgsLayoutSize(15, 14, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(north_label)

    # Clean Legend on Right Sidebar (only active visible layers)
    legend = QgsLayoutItemLegend(layout)
    legend.setTitle("Map Legend")
    legend.setLinkedMap(primary_map)
    legend.setAutoUpdateModel(False)
    legend_root = legend.model().rootGroup()
    keep_ids = {l.id() for l in (visible_vectors + thematic_rasters)}
    for child in list(legend_root.children()):
        if hasattr(child, "layerId") and child.layerId() not in keep_ids:
            legend_root.removeChildNode(child)
    legend.attemptMove(QgsLayoutPoint(220, 22, QgsUnitTypes.LayoutMillimeters))
    legend.attemptResize(QgsLayoutSize(67, 148, QgsUnitTypes.LayoutMillimeters))
    legend.setFrameEnabled(True)
    layout.addLayoutItem(legend)

    # Scale Bar
    scale_bar = QgsLayoutItemScaleBar(layout)
    scale_bar.setStyle("Single Box")
    scale_bar.setLinkedMap(primary_map)
    scale_bar.applyDefaultSize()
    scale_bar.attemptMove(QgsLayoutPoint(220, 174, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(scale_bar)

    # Footer / Attribution
    footer = QgsLayoutItemLabel(layout)
    footer.setText(f"Coordinate System: {proj.crs().authid()} | Export DPI: {dpi} | Generated by AutoGIS Studio v1.1.0")
    footer.setFont(QFont("Arial", 8))
    footer.attemptMove(QgsLayoutPoint(10, 196, QgsUnitTypes.LayoutMillimeters))
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
        "layout_mode": "dual_panel_comparison" if len(thematic_rasters) >= 2 else "single_panel",
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


def _resolve_study_bbox_wgs84(iface, explicit_bbox: Any = None) -> list[float]:
    if isinstance(explicit_bbox, (list, tuple)) and len(explicit_bbox) == 4:
        try:
            xmin, ymin, xmax, ymax = [float(x) for x in explicit_bbox]
            if xmin < xmax and ymin < ymax:
                return [xmin, ymin, xmax, ymax]
        except Exception as err:
            _ = err

    proj = QgsProject.instance()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    for lyr in proj.mapLayers().values():
        if isinstance(lyr, QgsVectorLayer) and lyr.isValid() and lyr.featureCount() > 0:
            ext = lyr.extent()
            if not ext.isEmpty():
                if lyr.crs() != wgs84:
                    try:
                        xform = QgsCoordinateTransform(lyr.crs(), wgs84, proj)
                        ext = xform.transformBoundingBox(ext)
                    except Exception as err:
                        _ = err
                if -180.0 <= ext.xMinimum() < ext.xMaximum() <= 180.0 and -90.0 <= ext.yMinimum() < ext.yMaximum() <= 90.0:
                    return [ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()]

    if iface and iface.mapCanvas():
        ext = iface.mapCanvas().extent()
        canvas_crs = iface.mapCanvas().mapSettings().destinationCrs()
        if not ext.isEmpty():
            if canvas_crs != wgs84:
                try:
                    xform = QgsCoordinateTransform(canvas_crs, wgs84, proj)
                    ext = xform.transformBoundingBox(ext)
                except Exception as err:
                    _ = err
            if -180.0 <= ext.xMinimum() < ext.xMaximum() <= 180.0 and -90.0 <= ext.yMinimum() < ext.yMaximum() <= 90.0:
                return [ext.xMinimum(), ext.yMinimum(), ext.xMaximum(), ext.yMaximum()]

    return [76.5, 30.8, 78.5, 32.8]


def _style_sentinel2_lulc_raster(lyr: QgsRasterLayer) -> None:
    prov = lyr.dataProvider()
    if prov is None:
        return
    classes = [
        (1.0, "#1d4ed8", "1 - Water Bodies"),
        (2.0, "#15803d", "2 - Trees / Forest"),
        (4.0, "#0d9488", "4 - Flooded Vegetation"),
        (5.0, "#eab308", "5 - Crops / Agriculture"),
        (7.0, "#dc2626", "7 - Built / Urban Area"),
        (8.0, "#a8a29e", "8 - Bare Ground / Rock"),
        (9.0, "#e0f2fe", "9 - Snow / Glacier Ice"),
        (10.0, "#cbd5e1", "10 - Clouds"),
        (11.0, "#84cc16", "11 - Rangeland / Scrub"),
    ]
    shader = QgsRasterShader()
    ramp = QgsColorRampShader(1.0, 11.0)
    ramp.setColorRampType(QgsColorRampShader.Exact)
    items = [
        QgsColorRampShader.ColorRampItem(val, QColor(col), label)
        for val, col, label in classes
    ]
    ramp.setColorRampItemList(items)
    shader.setRasterShaderFunction(ramp)
    renderer = QgsSingleBandPseudoColorRenderer(prov, 1, shader)
    renderer.setOpacity(0.85)
    lyr.setRenderer(renderer)


def tool_load_india_national_gis(iface, args: dict[str, Any], run_on_main=None) -> dict[str, Any]:
    """Load authoritative India & Global GIS layers (10m Land Cover GeoTIFF, Elevation Hillshade, Hydro Overlay, World Imagery)."""
    service_key = str(args.get("service") or "esa_worldcover_10m").strip().lower()
    entry = INDIA_AND_GLOBAL_SERVICES.get(service_key)
    if entry is None:
        return {
            "error": f"Unknown service '{service_key}'. Available: {', '.join(INDIA_AND_GLOBAL_SERVICES.keys())}"
        }

    if entry.get("kind") == "lulc_geotiff":
        if callable(run_on_main):
            bbox = run_on_main(lambda: _resolve_study_bbox_wgs84(iface, args.get("bbox")))
        else:
            bbox = _resolve_study_bbox_wgs84(iface, args.get("bbox"))

        xmin, ymin, xmax, ymax = bbox
        # Clamp huge extents so the 10m LULC GeoTIFF remains crisp over the study region
        if (xmax - xmin) > 6.0 or (ymax - ymin) > 6.0:
            cx = (xmin + xmax) / 2.0
            cy = (ymin + ymax) / 2.0
            xmin, xmax = cx - 1.5, cx + 1.5
            ymin, ymax = cy - 1.5, cy + 1.5

        params = urllib.parse.urlencode({
            "bbox": f"{xmin:.5f},{ymin:.5f},{xmax:.5f},{ymax:.5f}",
            "bboxSR": "4326",
            "size": "1200,1200",
            "imageSR": "4326",
            "format": "tiff",
            "f": "image",
        })
        export_url = f"{entry['uri']}?{params}"
        parsed = urllib.parse.urlparse(export_url)
        out_path = os.path.join(data_dir(), f"{service_key}_{int(time.time())}.tif")
        downloaded_ok = False
        if parsed.scheme in ("http", "https"):
            try:
                req = urllib.request.Request(export_url, headers={"User-Agent": "AutoGIS-QGIS-Plugin/1.1"})
                with urllib.request.urlopen(req, timeout=25) as resp:  # nosec B310
                    raw = resp.read()
                if len(raw) > 512 and raw[:4] in (b"II*\x00", b"MM\x00*"):
                    with open(out_path, "wb") as fh:
                        fh.write(raw)
                    downloaded_ok = True
            except Exception as err:
                log_warn(f"10m LULC GeoTIFF download warning: {err}")

        def _add_lulc() -> dict[str, Any]:
            if downloaded_ok and os.path.exists(out_path):
                lyr = QgsRasterLayer(out_path, entry["title"], "gdal")
                if lyr.isValid():
                    _style_sentinel2_lulc_raster(lyr)
                    QgsProject.instance().addMapLayer(lyr)
                    if iface and iface.mapCanvas():
                        iface.mapCanvas().refresh()
                    return {
                        "status": "loaded",
                        "service": service_key,
                        "layer": lyr.name(),
                        "path": out_path,
                        "bbox": [round(xmin, 4), round(ymin, 4), round(xmax, 4), round(ymax, 4)],
                        "classes": {
                            "1": "Water Bodies",
                            "2": "Trees / Forest",
                            "4": "Flooded Vegetation",
                            "5": "Crops / Agriculture",
                            "7": "Built / Urban Area",
                            "8": "Bare Ground / Rock",
                            "9": "Snow / Glacier Ice",
                            "11": "Rangeland / Scrub",
                        },
                    }
            # Fallback to AWS S3 ESA WorldCover 10m COG via /vsicurl/
            lat_tile = int(math.floor(((ymin + ymax) / 2.0) / 3.0) * 3)
            lon_tile = int(math.floor(((xmin + xmax) / 2.0) / 3.0) * 3)
            lat_prefix = f"N{abs(lat_tile):02d}" if lat_tile >= 0 else f"S{abs(lat_tile):02d}"
            lon_prefix = f"E{abs(lon_tile):03d}" if lon_tile >= 0 else f"W{abs(lon_tile):03d}"
            cog_uri = (
                f"/vsicurl/https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                f"ESA_WorldCover_10m_2021_v200_{lat_prefix}{lon_prefix}_Map.tif"
            )
            cog_lyr = QgsRasterLayer(cog_uri, entry["title"], "gdal")
            if cog_lyr.isValid():
                QgsProject.instance().addMapLayer(cog_lyr)
                if iface and iface.mapCanvas():
                    iface.mapCanvas().refresh()
                return {
                    "status": "loaded",
                    "service": service_key,
                    "layer": cog_lyr.name(),
                    "source": "esa_worldcover_s3_cog",
                }
            return {"error": f"Service layer '{entry['title']}' failed to load."}

        if callable(run_on_main):
            return run_on_main(_add_lulc)
        return _add_lulc()

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
