from __future__ import annotations

import os
from unittest.mock import MagicMock
from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

from core.geosam_engine import run_geosam_segmentation
from core.georag_engine import execute_georag_query
from core.webgis_exporter import export_project_to_interactive_webgis
from core.change_detection import run_spatial_change_detection
from core.lidar_3d_engine import run_drone_lidar_lod2_pipeline
from core.swarm_gas_engine import run_gas_multi_agent_swarm
from core.agent_engine import AutoGISEngine
from core.config import AutoGISConfig


def test_geosam_feature_extraction():
    iface = MagicMock()
    # Mock raster layer
    rlyr = QgsRasterLayer("test.tif", "Sentinel_RGB")
    QgsProject.instance().addMapLayer(rlyr)

    res = run_geosam_segmentation(iface, raster_layer_name_or_path="Sentinel_RGB", prompt="trees")
    assert res["status"] == "success"
    assert res["features_extracted"] > 0
    assert "output_layer" in res


def test_geosam_tiled_windowing_and_building_detection():
    iface = MagicMock()
    rlyr = QgsRasterLayer("google_sat.tif", "Google Satellite")
    rlyr.crs = lambda: type("CRS", (), {"authid": lambda *a: "EPSG:3857", "isValid": lambda *a: True, "isGeographic": lambda *a: False})()
    rlyr.rasterUnitsPerPixelX = lambda: 0.5
    rlyr.rasterUnitsPerPixelY = lambda: 0.5
    QgsProject.instance().addMapLayer(rlyr)

    # Test tiled processing with custom tile size and overlap
    res = run_geosam_segmentation(
        iface,
        raster_layer_name_or_path="Google Satellite",
        prompt="buildings",
        tile_size=256,
        overlap_px=32,
        max_tiles=9,
    )
    assert res["status"] == "success"
    assert res["tiles_processed"] >= 1
    assert res["tile_resolution"] == "256x256px"
    assert res["features_extracted"] > 0
    assert "Building" in res["class_label"]
    assert "output_layer" in res


def test_geosam_coarse_resolution_building_notice():
    iface = MagicMock()
    rlyr = QgsRasterLayer("sentinel2_10m.tif", "Sentinel2_B04")
    rlyr.rasterUnitsPerPixelX = lambda: 10.0
    rlyr.rasterUnitsPerPixelY = lambda: 10.0
    QgsProject.instance().addMapLayer(rlyr)

    res = run_geosam_segmentation(iface, raster_layer_name_or_path="Sentinel2_B04", prompt="buildings")
    assert res["status"] == "success"
    assert "resolution_notice" in res
    assert "Sentinel-2" in res["resolution_notice"]
    assert res["class_label"] == "Built-up Urban Cluster"


def test_georag_natural_language_query():
    iface = MagicMock()
    vlyr = QgsVectorLayer("Polygon?crs=EPSG:4326", "Parcels", "memory")
    QgsProject.instance().addMapLayer(vlyr)

    res = execute_georag_query(iface, query_text="parcels where area > 1000", target_layer_or_database="Parcels")
    assert res["status"] == "success"
    assert "translated_expression" in res
    assert "$area > 1000" in res["translated_expression"]


def test_webgis_interactive_export(tmp_path):
    iface = MagicMock()
    vlyr = QgsVectorLayer("Polygon?crs=EPSG:4326", "Buildings", "memory")
    QgsProject.instance().addMapLayer(vlyr)

    out_html = str(tmp_path / "webgis_map.html")
    res = export_project_to_interactive_webgis(iface, output_html_path=out_html, title="City 3D WebGIS")
    assert res["status"] == "success"
    assert os.path.exists(out_html)

    with open(out_html, "r", encoding="utf-8") as f:
        content = f.read()
    assert "maplibregl" in content
    assert "City 3D WebGIS" in content


def test_spatial_change_detection():
    iface = MagicMock()
    rlyr = QgsRasterLayer("ndvi.tif", "Sentinel2_NDVI")
    QgsProject.instance().addMapLayer(rlyr)

    res = run_spatial_change_detection(iface, baseline_layer_or_path="Sentinel2_NDVI", target_layer_or_path="Sentinel2_NDVI")
    assert res["status"] == "success"
    assert res["hotspots_detected"] > 0
    assert res["total_vegetation_loss_ha"] > 0


def test_drone_lidar_lod2_city_builder():
    iface = MagicMock()
    res = run_drone_lidar_lod2_pipeline(iface, target_mode="lod2_buildings")
    assert res["status"] == "success"
    assert res["buildings_generated"] > 0
    assert res["average_height_meters"] > 0
    assert res["3d_ready"] is True


def test_swarm_gas_multi_agent():
    iface = MagicMock()
    res = run_gas_multi_agent_swarm(
        iface,
        goal="Develop regional solar farm suitability index and publication map",
        target_region="Jaipur, Rajasthan",
    )
    assert res["status"] == "success"
    assert res["consensus_achieved"] is True
    assert len(res["swarm_trace"]) == 4
    assert res["total_artifacts_produced"] == 7


def test_dynamic_intent_routing_v108():
    engine = AutoGISEngine(iface=MagicMock(), config=AutoGISConfig())

    # SAM prompt
    tools_sam = engine._build_tools_schema("Segment buildings using GeoSAM 2")
    assert "geosam_segment_features" in {t["function"]["name"] for t in tools_sam}

    # GeoRAG prompt
    tools_rag = engine._build_tools_schema("Execute spatial query with GeoRAG on active database")
    assert "georag_spatial_query" in {t["function"]["name"] for t in tools_rag}

    # WebGIS prompt
    tools_web = engine._build_tools_schema("Export 3D webgis maplibre app for browser")
    assert "export_interactive_webgis" in {t["function"]["name"] for t in tools_web}

    # Change Detection prompt
    tools_cd = engine._build_tools_schema("Detect deforestation and forest loss over time")
    assert "detect_raster_change" in {t["function"]["name"] for t in tools_cd}

    # LiDAR prompt
    tools_lidar = engine._build_tools_schema("Build LoD-2 3D buildings from drone LiDAR nDSM")
    assert "drone_lidar_lod2_builder" in {t["function"]["name"] for t in tools_lidar}

    # Swarm prompt
    tools_swarm = engine._build_tools_schema("Deploy GAS 2.0 multi-agent swarm team")
    assert "gas_multi_agent_swarm" in {t["function"]["name"] for t in tools_swarm}
