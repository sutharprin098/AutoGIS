"""End-to-end tests for Geospatial Agentic Services (GAS 1.0.0) in AutoGIS."""

from __future__ import annotations

import base64
import json
import os
import urllib.request
from pathlib import Path

from core.config import AutoGISConfig
from core.gas_tools import (
    BUILTIN_GAS_AGENTS,
    DEFAULT_GAS_SERVER_URL,
    GasClient,
    tool_gas_describe_agent,
    tool_gas_discover_agents,
    tool_gas_execute_task,
    tool_gas_manage_task,
    tool_gas_registry_search,
)
from core.gis_tools import build_autogis_tools
from core.mcp_bridge import AUTOGIS_GAS_AGENT_ID, AutoGISMCPBridge


def test_gas_tools_registered_in_autogis():
    tools = build_autogis_tools()
    expected = [
        "gas_discover_agents",
        "gas_describe_agent",
        "gas_execute_task",
        "gas_manage_task",
        "gas_registry_search",
    ]
    for name in expected:
        assert name in tools, f"Missing GAS tool in AutoGIS registry: {name}"
        assert callable(tools[name].handler)


def test_gas_config_defaults_and_persistence():
    cfg = AutoGISConfig()
    assert cfg.gas_server_url == "https://www.geospatial-agentic-services.online"
    assert cfg.gas_registry_url == "https://www.geospatial-agentic-services.online/registry"
    cfg.gas_server_url = "http://127.0.0.1:4042/"
    assert cfg.gas_server_url == "http://127.0.0.1:4042"
    cfg.gibd_api_key = "test-gibd-key"
    assert cfg.gibd_api_key == "test-gibd-key"
    # Restore defaults
    cfg.gas_server_url = DEFAULT_GAS_SERVER_URL
    cfg.gibd_api_key = ""


def test_gas_client_request_builder_and_file_encoding(tmp_path):
    client = GasClient("http://127.0.0.1:4042", default_credentials={"GIBD_API_KEY": "k1"}, load_capabilities=False)

    sample_geojson = tmp_path / "points.geojson"
    sample_geojson.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "properties": {"id": 1}, "geometry": {"type": "Point", "coordinates": [77.2, 28.6]}}],
        }),
        encoding="utf-8",
    )
    encoded = client.encode_dataset_file(sample_geojson)
    assert encoded["filename"] == "points.geojson"
    assert encoded["encoding"] == "base64"
    assert encoded["mime_type"] == "application/geo+json"
    decoded = json.loads(base64.b64decode(encoded["data"]).decode("utf-8"))
    assert decoded["type"] == "FeatureCollection"

    req_body = client.build_execute_task_request(
        "Buffer these points by 500m",
        mode="sync",
        input_datasets=[encoded],
        artifact_delivery="Encoded",
        parameters={"distance_m": 500},
        model="gpt-4o-mini",
    )
    assert req_body["task"] == {"instructions": "Buffer these points by 500m", "mode": "sync"}
    assert req_body["outputs"] == {"artifact_delivery": "Encoded"}
    assert req_body["inputs"]["input_datasets"][0]["filename"] == "points.geojson"
    assert req_body["parameters"]["distance_m"] == 500
    assert req_body["parameters"]["model"] == "gpt-4o-mini"
    assert req_body["credentials"]["GIBD_API_KEY"] == "k1"


def test_local_autogis_gas_server_and_client_end_to_end(tmp_path):
    """Spin up AutoGISMCPBridge as a local GAS 1.0.0 server and run full end-to-end client & tool workflows against it."""
    sample_out_geojson = tmp_path / "gas_generated_buffer.geojson"
    sample_out_geojson.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Buffered_Zone", "radius_m": 250},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[77.1, 28.5], [77.2, 28.5], [77.2, 28.6], [77.1, 28.6], [77.1, 28.5]]],
                    },
                }
            ],
        }),
        encoding="utf-8",
    )

    class _DummySpec:
        def __init__(self, name: str, fn):
            self.name = name
            self.description = f"Tool {name}"
            self.risk = "write"
            self.parameters = {"type": "object", "properties": {}}
            self.handler = fn

    class _DummyEngine:
        ASYNC_NETWORK_TOOLS = frozenset()

        def __init__(self):
            self._iface = None
            self.tools = {
                "get_project_overview": _DummySpec(
                    "get_project_overview",
                    lambda iface, args: {"crs": "EPSG:4326", "layer_count": 2},
                ),
                "spatial_buffer": _DummySpec(
                    "spatial_buffer",
                    lambda iface, args: {
                        "status": "buffered",
                        "distance": args.get("distance", 250),
                        "file_path": str(sample_out_geojson),
                    },
                ),
            }

        def run_on_main_thread(self, fn, timeout=10.0):
            return fn()

    engine = _DummyEngine()
    bridge = AutoGISMCPBridge(engine, port=0)
    assert bridge.start() is True

    try:
        # 1. Test GetCapabilities via tool_gas_discover_agents
        disc = tool_gas_discover_agents(None, {"server_url": bridge.url, "include_descriptions": True})
        assert disc["status"] == "ok"
        assert disc["source"] == "live_gas_server"
        assert disc["gas_version"] == "1.0.0"
        assert any(a["agent_id"] == AUTOGIS_GAS_AGENT_ID for a in disc["agents"])

        # 2. Test DescribeAgent & GetAgentStatus via tool_gas_describe_agent
        desc = tool_gas_describe_agent(
            None,
            {"agent_id": AUTOGIS_GAS_AGENT_ID, "server_url": bridge.url, "include_status": True},
        )
        assert desc["status"] == "ok"
        assert desc["describe_agent"]["profile"]["agent_id"] == AUTOGIS_GAS_AGENT_ID
        assert desc["describe_agent"]["conformance"]["gas_version"] == "1.0.0"
        assert desc["agent_status"]["status"] == "available"

        # 3. Test ExecuteTask (sync mode) with input_datasets + artifact download & auto-load into QGIS
        in_file = tmp_path / "input_sites.geojson"
        in_file.write_text(
            json.dumps({"type": "FeatureCollection", "features": []}),
            encoding="utf-8",
        )
        exec_sync = tool_gas_execute_task(
            None,
            {
                "agent_id": AUTOGIS_GAS_AGENT_ID,
                "server_url": bridge.url,
                "instructions": "Run spatial_buffer on input sites",
                "mode": "sync",
                "input_datasets": [str(in_file)],
                "parameters": {"tool": "spatial_buffer", "distance": 250},
                "auto_load_to_qgis": True,
            },
        )
        assert exec_sync["status"] == "successful"
        task_id = exec_sync["task_id"]
        assert task_id and task_id.startswith("task_")
        assert exec_sync["artifacts_count"] == 1
        art = exec_sync["artifacts"][0]
        assert os.path.isfile(art["local_path"])
        assert art["qgis_layer"]["layer_type"] == "vector"

        # 4. Test ExecuteTask (stream mode — NDJSON events)
        exec_stream = tool_gas_execute_task(
            None,
            {
                "agent_id": AUTOGIS_GAS_AGENT_ID,
                "server_url": bridge.url,
                "instructions": "spatial_buffer",
                "mode": "stream",
                "artifact_delivery": "Encoded",
                "parameters": {"tool": "spatial_buffer", "distance": 500},
                "auto_load_to_qgis": True,
            },
        )
        assert exec_stream["status"] == "successful"
        assert exec_stream["raw_response"].get("stream_events_count", 0) >= 2
        assert exec_stream["artifacts_count"] == 1

        # 5. Test GetTaskStatus, GetTaskResult, wait, and CancelTask via tool_gas_manage_task
        st_res = tool_gas_manage_task(
            None,
            {"action": "status", "agent_id": AUTOGIS_GAS_AGENT_ID, "task_id": task_id, "server_url": bridge.url},
        )
        assert st_res["status"] == "ok"
        assert st_res["task_status"]["task"]["status"] == "successful"

        res_fetch = tool_gas_manage_task(
            None,
            {"action": "result", "agent_id": AUTOGIS_GAS_AGENT_ID, "task_id": task_id, "server_url": bridge.url},
        )
        assert res_fetch["status"] == "ok"
        assert res_fetch["artifacts_count"] == 1

        cancel_res = tool_gas_manage_task(
            None,
            {"action": "cancel", "agent_id": AUTOGIS_GAS_AGENT_ID, "task_id": task_id, "server_url": bridge.url},
        )
        assert cancel_res["status"] == "ok"
        assert cancel_res["result"]["task"]["status"] == "canceled"
    finally:
        bridge.stop()


def test_live_public_gas_server_and_registry_discovery():
    """Verify live discovery against https://www.geospatial-agentic-services.online (with graceful fallback if offline)."""
    disc = tool_gas_discover_agents(None, {"keyword": "vector"})
    assert disc["status"] == "ok"
    assert disc["count"] >= 1
    assert any("vector" in a["agent_id"] for a in disc["agents"])

    desc = tool_gas_describe_agent(None, {"agent_id": "vector_analysis_agent", "include_status": True})
    assert desc["status"] == "ok"
    assert desc["describe_agent"]["profile"]["agent_id"] == "vector_analysis_agent"

    reg = tool_gas_registry_search(None, {"action": "list_agents", "keyword": "earthquake"})
    assert reg["status"] == "ok"
    assert reg["count"] >= 1
    assert any("earthquake" in a["agent_id"] for a in reg["agents"])
    assert len(BUILTIN_GAS_AGENTS) == 16
