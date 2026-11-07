from __future__ import annotations

import json
import os
import tempfile
import pytest

from core.gis_tools import build_autogis_tools
from core.extended_gis_tools import (
    tool_analyze_map_vision,
    tool_classify_crops_sentinel1_sar,
    tool_create_map_graticule,
    tool_export_temporal_animation,
    tool_fetch_air_quality_heatmap,
    tool_fetch_imd_weather_data,
    tool_generate_spatial_report,
    tool_georeference_helper,
    tool_load_india_census_data,
    tool_load_india_rail_and_metro,
    tool_manage_agent_memory,
    tool_visualize_3d_terrain,
)


def test_all_extended_tools_registered():
    tools = build_autogis_tools()
    expected_new_tools = [
        "export_temporal_animation",
        "visualize_3d_terrain",
        "create_map_graticule",
        "georeference_helper",
        "manage_agent_memory",
        "generate_spatial_report",
        "analyze_map_vision",
        "load_india_rail_and_metro",
        "fetch_imd_weather_data",
        "load_india_census_data",
        "fetch_air_quality_heatmap",
        "classify_crops_sentinel1_sar",
    ]
    for name in expected_new_tools:
        assert name in tools, f"Missing tool in registry: {name}"
        assert callable(tools[name].handler)


def test_export_temporal_animation(tmp_path):
    res = tool_export_temporal_animation(
        None,
        {
            "total_steps": 4,
            "duration_ms": 300,
            "output_path": str(tmp_path / "test_anim.gif"),
            "title_prefix": "NDVI Monthly",
        },
    )
    assert res["status"] == "exported"
    assert res["frame_count"] == 4
    assert os.path.exists(res["html_player_path"])
    with open(res["html_player_path"], "r", encoding="utf-8") as f:
        content = f.read()
    assert "NDVI Monthly" in content
    assert "AutoGIS" in content or "Time Series" in content


def test_visualize_3d_terrain():
    res = tool_visualize_3d_terrain(
        None,
        {
            "vertical_scale": 2.0,
            "dem_layer": "SRTM_DEM",
        },
    )
    assert res["status"] == "ready"
    assert res["vertical_scale"] == 2.0
    assert os.path.exists(res["interactive_3d_html"])
    with open(res["interactive_3d_html"], "r", encoding="utf-8") as f:
        content = f.read()
    assert "three.js" in content
    assert "AutoGIS 3D Terrain Studio" in content


def test_create_map_graticule():
    res = tool_create_map_graticule(
        None,
        {
            "bbox": [77.0, 28.0, 77.5, 28.5],
            "interval_deg": 0.1,
            "layer_name": "Delhi_Graticule",
        },
    )
    assert res["status"] == "created"
    assert res["features_count"] > 0
    assert res["interval_deg"] == 0.1
    assert os.path.exists(res["file_path"])
    with open(res["file_path"], "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == res["features_count"]
    # Check degree label formatting
    labels = [f["properties"]["label"] for f in data["features"]]
    assert any("°" in lbl for lbl in labels)


def test_georeference_helper(tmp_path):
    # Create a small dummy image
    img_file = tmp_path / "scanned_map.png"
    img_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x02\x08\x02\x00\x00\x00\xfd\xd4\x9as\x00\x00\x00\tIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82")

    res = tool_georeference_helper(
        None,
        {
            "image_path": str(img_file),
            "bounding_box": [72.8, 18.9, 72.9, 19.0],
            "target_crs": "EPSG:4326",
        },
    )
    assert res["status"] == "georeferenced"
    assert res["target_crs"] == "EPSG:4326"


def test_manage_agent_memory():
    # Save memory
    save_res = tool_manage_agent_memory(
        None,
        {
            "action": "save",
            "key": "study_area_focus",
            "value": "Bengaluru Urban Growth 2020-2026",
        },
    )
    assert save_res["status"] == "saved"
    assert save_res["key"] == "study_area_focus"

    # Query memory
    query_res = tool_manage_agent_memory(
        None,
        {
            "action": "query",
            "query": "Bengaluru",
        },
    )
    assert query_res["status"] == "ok"
    assert "study_area_focus" in query_res["matches"]

    # List memory
    list_res = tool_manage_agent_memory(None, {"action": "list"})
    assert list_res["status"] == "ok"
    assert list_res["total_memories"] >= 1

    # Clear specific memory
    clear_res = tool_manage_agent_memory(None, {"action": "clear", "key": "study_area_focus"})
    assert clear_res["status"] == "cleared_key"


def test_generate_spatial_report():
    res = tool_generate_spatial_report(
        None,
        {
            "report_title": "National Highway Expansion Spatial Audit",
            "summary": "Multi-criteria spatial buffer and overlay analysis across eco-sensitive corridors.",
            "findings": ["3 wildlife corridors intersect proposed route.", "Soil runoff risk high in sector 4."],
            "recommendations": ["Construct elevated eco-ducts at Ch. 42-48 km."],
            "include_map_canvas": False,
        },
    )
    assert res["status"] == "generated"
    assert os.path.exists(res["html_report"])
    with open(res["html_report"], "r", encoding="utf-8") as f:
        html_text = f.read()
    assert "National Highway Expansion Spatial Audit" in html_text
    assert "wildlife corridors" in html_text
    assert "elevated eco-ducts" in html_text


def test_analyze_map_vision():
    res = tool_analyze_map_vision(
        None,
        {
            "prompt": "Evaluate satellite resolution and water coverage.",
        },
    )
    assert "status" in res
    assert "analysis" in res
    assert len(res["analysis"]) > 20


def test_load_india_rail_and_metro():
    res = tool_load_india_rail_and_metro(
        None,
        {
            "network_type": "all",
            "city_or_region": "Delhi",
            "bbox": [77.1, 28.5, 77.3, 28.7],
        },
    )
    assert res["status"] == "loaded"
    assert res["city_or_region"] == "Delhi"
    assert os.path.exists(res["file_path"])


def test_fetch_imd_weather_data():
    res = tool_fetch_imd_weather_data(
        None,
        {
            "parameter": "rainfall_precipitation",
            "region": "India",
            "bbox": [72.0, 18.0, 78.0, 24.0],
        },
    )
    assert res["status"] == "loaded"
    assert res["grid_points"] > 0
    assert "mean_temp_c" in res
    assert os.path.exists(res["file_path"])


def test_load_india_census_data():
    res = tool_load_india_census_data(
        None,
        {
            "indicator": "literacy",
            "filter_state": "Maharashtra",
        },
    )
    assert res["status"] == "loaded"
    assert res["states_count"] == 1
    assert os.path.exists(res["file_path"])
    with open(res["file_path"], "r", encoding="utf-8") as f:
        data = json.load(f)
    feat = data["features"][0]
    assert feat["properties"]["state"] == "Maharashtra"
    assert feat["properties"]["literacy_pct"] > 80.0


def test_fetch_air_quality_heatmap():
    res = tool_fetch_air_quality_heatmap(
        None,
        {
            "pollutant": "pm25",
            "city_or_bbox": "Delhi",
        },
    )
    assert res["status"] == "loaded"
    assert res["stations_count"] >= 10
    assert os.path.exists(res["file_path"])
    with open(res["file_path"], "r", encoding="utf-8") as f:
        data = json.load(f)
    first_st = data["features"][0]["properties"]
    assert "aqi" in first_st
    assert "category" in first_st
    assert "color" in first_st
    assert first_st["color"].startswith("#")


def test_classify_crops_sentinel1_sar():
    res = tool_classify_crops_sentinel1_sar(
        None,
        {
            "architecture": "tcn_attention",
            "crop_season": "Kharif 2024",
            "bbox": [77.2, 28.4, 77.5, 28.7],
        },
    )
    assert res["status"] == "classified"
    assert "MDPI Remote Sensing 17(12), 2095" in res["methodology"]
    assert res["total_cropland_ha"] > 0
    assert len(res["crops_identified"]) > 0
    assert os.path.exists(res["geojson_layer"])
    assert os.path.exists(res["interactive_report_html"])
    with open(res["interactive_report_html"], "r", encoding="utf-8") as f:
        html_content = f.read()
    assert "MDPI REMOTE SENSING" in html_content
    assert "Radar Vegetation Index" in html_content
    assert "Chart" in html_content

