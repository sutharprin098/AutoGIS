from __future__ import annotations

import json
from unittest.mock import MagicMock
from core.agent_engine import repair_and_parse_json, CORE_TOOL_NAMES, GEE_STAC_RASTER_TOOL_NAMES, INDIA_LIVE_TOOL_NAMES
from core.checkpoint_manager import ProjectCheckpointManager


def test_repair_and_parse_json_variants():
    # 1. Standard json
    assert repair_and_parse_json('{"place": "Jaipur", "buffer": 500}') == {"place": "Jaipur", "buffer": 500}

    # 2. Markdown fence wrapped
    raw_fence = '```json\n{"code": "print(123)", "layer": "test"}\n```'
    assert repair_and_parse_json(raw_fence) == {"code": "print(123)", "layer": "test"}

    # 3. Trailing commas
    raw_trailing = '{"items": [1, 2, ], "active": true, }'
    assert repair_and_parse_json(raw_trailing) == {"items": [1, 2], "active": True}

    # 4. Single-quoted python dict string
    raw_single = "{'domain': 'hydrology', 'value': 42}"
    assert repair_and_parse_json(raw_single) == {"domain": "hydrology", "value": 42}

    # 5. Empty / null
    assert repair_and_parse_json("") == {}
    assert repair_and_parse_json("{}") == {}


def test_checkpoint_manager_lifecycle():
    fake_iface = MagicMock()
    mgr = ProjectCheckpointManager(iface=fake_iface)
    mgr.clear()

    assert not mgr.can_undo()

    # Create checkpoint
    chk = mgr.create_checkpoint("Initial state")
    assert chk.description == "Initial state"
    assert mgr.can_undo()
    assert mgr.get_last_checkpoint_description() == "Initial state"

    # Rollback
    res = mgr.rollback()
    assert res["status"] == "success"
    assert not mgr.can_undo()


def test_dynamic_tool_pruning():
    from core.agent_engine import AutoGISEngine
    from core.config import AutoGISConfig

    engine = AutoGISEngine(iface=MagicMock(), config=AutoGISConfig())

    # General query: should return Core + Acquisition (~28 tools, not 69)
    tools_general = engine._build_tools_schema("Buffer my boundary by 500m")
    tool_names_general = {t["function"]["name"] for t in tools_general}
    assert "spatial_buffer" in tool_names_general
    assert "fetch_place_boundary" in tool_names_general
    assert "gee_compute_index" not in tool_names_general
    assert "gas_registry_search" not in tool_names_general
    assert len(tools_general) < 32

    # GEE / Satellite query: should include GEE tools
    tools_gee = engine._build_tools_schema("Compute NDVI for Rabi season using Sentinel-2 GEE")
    tool_names_gee = {t["function"]["name"] for t in tools_gee}
    assert "gee_compute_index" in tool_names_gee
    assert "gee_download_dem" in tool_names_gee

    # India query: should include India live GIS tools
    tools_india = engine._build_tools_schema("Show air quality AQI and railways across India")
    tool_names_india = {t["function"]["name"] for t in tools_india}
    assert "fetch_air_quality_heatmap" in tool_names_india
    assert "load_india_rail_and_metro" in tool_names_india

