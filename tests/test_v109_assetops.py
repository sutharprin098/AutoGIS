from __future__ import annotations

from unittest.mock import MagicMock
from qgis.core import QgsProject

from core.spatial_assetops import (
    run_assetops_iot_telemetry,
    run_assetops_fmsr_diagnostics,
    run_assetops_tsfm_forecast,
    run_assetops_work_order_dispatch,
    run_geo_assetops_benchmark_eval,
)
from core.swarm_gas_engine import run_gas_multi_agent_swarm
from core.gis_tools import build_autogis_tools
from core.agent_engine import AutoGISEngine
from core.config import AutoGISConfig


def test_total_tools_count_v109():
    tools = build_autogis_tools()
    assert len(tools) >= 82
    assert "assetops_iot_telemetry" in tools
    assert "assetops_fmsr_diagnostics" in tools
    assert "assetops_tsfm_forecast" in tools
    assert "assetops_work_order_dispatch" in tools
    assert "geo_assetops_benchmark_eval" in tools


def test_assetops_iot_telemetry_agent():
    iface = MagicMock()
    res = run_assetops_iot_telemetry(
        iface,
        asset_domain="power_grid",
        sensor_count=16,
        anomaly_injection_rate=0.25,
    )
    assert res["status"] == "success"
    assert res["agent"] == "AssetOpsBench_IoT_Telemetry_Agent"
    assert res["total_sensors_monitored"] == 16
    assert res["critical_anomalies_detected"] >= 2
    assert len(res["critical_asset_telemetry"]) == res["critical_anomalies_detected"]
    assert "output_layer" in res


def test_assetops_fmsr_diagnostics_agent():
    iface = MagicMock()
    res = run_assetops_fmsr_diagnostics(
        iface,
        telemetry_layer_or_domain="water_pipeline",
        environmental_context="Steep hydraulic gradient and monsoon flood plain",
        include_iso_compliance=True,
    )
    assert res["status"] == "success"
    assert res["agent"] == "AssetOpsBench_FMSR_Reasoning_Agent"
    assert res["asset_domain"] == "water_pipeline"
    assert res["total_failure_modes_diagnosed"] == 4
    assert res["highest_rpn_score"] >= 200
    first_diag = res["fmsr_diagnostics"][0]
    assert "FMSR-WTR" in first_diag["failure_code"]
    assert "ISO" in first_diag["iso_standard"]


def test_assetops_tsfm_forecast_agent():
    iface = MagicMock()
    res = run_assetops_tsfm_forecast(
        iface,
        asset_domain="telecom_tower",
        forecast_horizon_days=45,
        model_backbone="IBM-Granite-TSFM-TinyTimeMixer",
    )
    assert res["status"] == "success"
    assert res["agent"] == "AssetOpsBench_TSFM_Forecasting_Agent"
    assert res["forecast_horizon_days"] == 45
    assert res["zones_evaluated"] == 6
    assert res["imminent_risk_assets_count"] >= 2
    assert res["min_remaining_useful_life_days"] > 0


def test_assetops_work_order_dispatch_agent():
    iface = MagicMock()
    res = run_assetops_work_order_dispatch(
        iface,
        asset_domain="renewable_solar",
        max_crews=2,
        sla_priority="P1_EMERGENCY",
    )
    assert res["status"] == "success"
    assert res["agent"] == "AssetOpsBench_WorkOrder_Dispatch_Agent"
    assert res["work_orders_dispatched"] == 4
    assert res["total_dispatch_distance_km"] > 0
    assert res["work_orders"][0]["work_order_id"].startswith("WO-MAXIMO-")


def test_geo_assetops_benchmark_evaluation_end_to_end():
    iface = MagicMock()
    res = run_geo_assetops_benchmark_eval(
        iface,
        suite_domain="all",
        orchestration_mode="AgentHive_CodeReAct",
        execute_live_pipeline=True,
    )
    assert res["status"] == "success"
    assert res["benchmark_framework"] == "IBM-AssetOpsBench-GeoSpatial-v1.0.9"
    assert res["total_scenarios_executed"] >= 7
    metrics = res["benchmark_metrics"]
    assert metrics["task_completion_rate_pct"] == 100.0
    assert metrics["overall_geo_assetops_score"] >= 98.0
    artifacts = res["live_pipeline_artifacts"]
    assert artifacts["iot_telemetry_layer"]
    assert artifacts["fmsr_diagnostics_layer"]
    assert artifacts["tsfm_forecast_layer"]
    assert artifacts["work_order_dispatch_layer"]


def test_agenthive_swarm_with_assetops_agent():
    iface = MagicMock()
    res = run_gas_multi_agent_swarm(
        iface,
        goal="Inspect power grid transformer IoT telemetry, run FMSR failure diagnostics, and dispatch Maximo work orders",
        target_region="Dehradun Smart City",
        execution_strategy="agenthive",
    )
    assert res["status"] == "success"
    assert res["swarm_protocol"] == "GAS-2.0-AgentHive-MetaAgent"
    assert len(res["swarm_trace"]) == 5
    assert any("AssetOps" in step["agent"] for step in res["swarm_trace"])
    assert res["total_artifacts_produced"] == 10


def test_dynamic_intent_routing_v109_assetops():
    engine = AutoGISEngine(iface=MagicMock(), config=AutoGISConfig())

    tools_iot = {t["function"]["name"] for t in engine._build_tools_schema("Monitor IoT sensor telemetry and transformer anomaly")}
    assert "assetops_iot_telemetry" in tools_iot
    assert "assetops_fmsr_diagnostics" in tools_iot

    tools_tsfm = {t["function"]["name"] for t in engine._build_tools_schema("Run TSFM time series forecast and remaining useful life RUL")}
    assert "assetops_tsfm_forecast" in tools_tsfm

    tools_wo = {t["function"]["name"] for t in engine._build_tools_schema("Create Maximo maintenance work order and crew dispatch route")}
    assert "assetops_work_order_dispatch" in tools_wo

    tools_bench = {t["function"]["name"] for t in engine._build_tools_schema("Run AssetOpsBench industry 4.0 benchmark evaluation")}
    assert "geo_assetops_benchmark_eval" in tools_bench
