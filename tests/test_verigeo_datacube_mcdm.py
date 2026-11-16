"""Unit and Integration Tests for AutoGIS + VeriGeo + 100+ Layer Datacube & MCDM Engine."""

from __future__ import annotations

import numpy as np
import pytest

from core.verigeo_bridge import VeriGeoBridge
from core.datacube_engine import StreamingDatacube, LayerDescriptor, DatacubeGridSpec
from core.autonomous_mcdm import AutonomousMCDMEngine, Criterion
from core.advanced_gis_tools import (
    tool_verigeo_verify_workflow,
    tool_verigeo_maup_and_physics_guard,
    tool_datacube_manage_100_layers,
    tool_autonomous_mcdm_100plus,
)


# =============================================================================
# 1. VeriGeo Bridge Tests
# =============================================================================
def test_verigeo_maup_and_ecological_fallacy():
    bridge = VeriGeoBridge()
    # High variance sub-units
    res = bridge.check_maup_risk(
        values_zone_a=[10.0, 20.0, 30.0, 40.0],
        values_zone_b=[15.0, 25.0, 35.0, 45.0],
        sub_unit_ratios=[0.1, 0.9, 0.2, 0.8],
    )
    assert res["maup_risk_level"] in ("HIGH", "CRITICAL")
    assert "aggregated_pearson_r" in res


def test_verigeo_spatial_autocorrelation_moran_i():
    bridge = VeriGeoBridge()
    # Distinct clustered values
    vals = [10.0, 11.0, 12.0, 10.5, 90.0, 92.0, 91.0, 93.0]
    coords = [
        (0.0, 0.0), (0.1, 0.0), (0.0, 0.1), (0.1, 0.1),
        (10.0, 10.0), (10.1, 10.0), (10.0, 10.1), (10.1, 10.1),
    ]
    res = bridge.compute_spatial_autocorrelation(vals, coords, k_neighbors=3)
    assert "moran_i" in res
    assert res["moran_i"] > 0.3
    assert res["violates_iid"] is True


def test_verigeo_physics_conservation_laws():
    bridge = VeriGeoBridge()

    # Hydrology violation: Runoff + ET > Precip
    bad_hydro = bridge.verify_physical_conservation(
        domain="hydrology",
        metrics={"precipitation_mm": 100.0, "runoff_mm": 80.0, "evapotranspiration_mm": 50.0},
    )
    assert bad_hydro["passed"] is False
    assert len(bad_hydro["violations"]) > 0

    # Carbon NPP violation
    bad_carbon = bridge.verify_physical_conservation(
        domain="carbon_biomass",
        metrics={"npp_g_c_m2_yr": 4500.0},
    )
    assert bad_carbon["passed"] is False

    # Solar radiation violation
    bad_solar = bridge.verify_physical_conservation(
        domain="solar_energy",
        metrics={"surface_ghi_w_m2": 1500.0},
    )
    assert bad_solar["passed"] is False


def test_verigeo_empty_result_diagnosis():
    bridge = VeriGeoBridge()
    diag = bridge.diagnose_empty_intersection(
        layer_a_meta={"crs": "EPSG:4326", "extent": [70.0, 20.0, 75.0, 25.0]},
        layer_b_meta={"crs": "EPSG:32643", "extent": [200000, 2800000, 300000, 2900000]},
    )
    assert diag["auto_retry_recommended"] is True
    assert any("CRS Mismatch" in r for r in diag["root_causes"])


# =============================================================================
# 2. 100+ Layer Datacube Tests
# =============================================================================
def test_datacube_batch_100_layers():
    cube = StreamingDatacube()
    layers = []
    for i in range(105):
        layers.append({
            "id": f"l_{i}",
            "name": f"Criterion_{i}",
            "type": "raster" if i < 90 else "vector",
            "crs": "EPSG:32643",
            "resolution": 30.0,
            "bounds": (200000.0, 2800000.0, 300000.0, 2900000.0),
            "is_exclusion": (i % 20 == 0),
        })

    count = cube.register_batch_layers(layers)
    assert count == 105
    summary = cube.get_summary()
    assert summary["total_layers"] == 105
    assert summary["raster_count"] == 90
    assert summary["vector_count"] == 15

    # Test chunked streaming execution without memory blowup
    res = cube.execute_streaming_pipeline(lambda chunk: np.ones((512, 512), dtype=np.float32))
    assert res["status"] == "COMPLETED"
    assert res["tiles_processed"] > 0
    assert res["ram_efficiency_pct"] > 90.0


# =============================================================================
# 3. Autonomous 100+ Criteria MCDM Tests
# =============================================================================
def test_ahp_consistency():
    engine = AutonomousMCDMEngine()
    # Perfectly consistent 3x3 matrix
    consistent_matrix = np.array([
        [1.0, 2.0, 4.0],
        [0.5, 1.0, 2.0],
        [0.25, 0.5, 1.0],
    ])
    weights, cr, is_consistent = engine.solve_ahp_matrix(consistent_matrix)
    assert is_consistent is True
    assert cr < 0.10
    assert pytest.approx(float(np.sum(weights)), 0.001) == 1.0


def test_shannon_entropy_weights():
    engine = AutonomousMCDMEngine()
    data = np.array([
        [10.0, 50.0, 100.0],
        [12.0, 52.0, 20.0],
        [15.0, 51.0, 500.0],
        [18.0, 49.0, 5.0],
    ])
    weights = engine.compute_shannon_entropy_weights(data)
    assert len(weights) == 3
    assert pytest.approx(float(np.sum(weights)), 0.001) == 1.0
    # Column 1 has very low variance (near 50), Column 2 has huge variance (5 to 500)
    # Column 2 should receive highest weight
    assert weights[2] > weights[1]


def test_100_criteria_mcdm_pipeline():
    engine = AutonomousMCDMEngine()
    result = engine.execute_100_criteria_mcdm(
        simulated_samples=500,
        alpha_hybrid=0.5,
        num_monte_carlo_runs=10,
    )
    assert result["status"] == "SUCCESS"
    assert result["total_criteria_processed"] >= 100
    assert "suitability_statistics" in result
    assert "monte_carlo_sensitivity" in result
    assert result["suitability_statistics"]["mean_score"] > 0.0


# =============================================================================
# 4. End-to-End Tool Handlers Tests
# =============================================================================
def test_all_tools_execution():
    res_v = tool_verigeo_verify_workflow({"layer_name": "solar_criteria", "repair_slivers": True})
    assert res_v["status"] == "ok"
    assert res_v["verigeo_active"] is True

    res_p = tool_verigeo_maup_and_physics_guard({"domain": "hydrology"})
    assert res_p["status"] == "ok"
    assert res_p["physics_conservation_check"]["status"] == "PASSED"

    res_c = tool_datacube_manage_100_layers({"action": "register_synthetic_100"})
    assert res_c["status"] == "ok"
    assert res_c["layers_registered"] == 100

    res_m = tool_autonomous_mcdm_100plus({"ahp_entropy_alpha": 0.6, "simulated_samples": 200})
    assert res_m["status"] == "ok"
    assert res_m["mcdm_result"]["total_criteria_processed"] >= 100
