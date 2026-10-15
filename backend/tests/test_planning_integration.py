from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app

DEMO_CANDIDATE_IDS = [
    "cand-hcm_2025_26911-02",
    "cand-hcm_2025_26929-01",
    "cand-hcm_2025_27073-01",
]


def _planning_request(
    catalog: dict, *, coverage_minutes: int, demand_scenario: str = "base"
) -> dict:
    return {
        "contract_version": "0.1",
        "study_area": catalog["study_area"],
        "run": {
            "as_of": datetime(2026, 10, 13, tzinfo=UTC).isoformat(),
            "horizon_years": catalog["defaults"]["horizon_years"],
            "data_snapshot_id": catalog["snapshot"]["data_snapshot_id"],
            "seed": catalog["defaults"]["seed"],
            "config_version": catalog["defaults"]["config_version"],
            "demand_scenario": demand_scenario,
        },
        "candidate_source": {"mode": "provided", "candidate_ids": DEMO_CANDIDATE_IDS},
        "profile": "technical_opportunity",
        "technical": {
            "coverage_minutes": coverage_minutes,
            "charger_options": [catalog["defaults"]["charger_option"]],
            "budget_vnd": None,
        },
        "policy_package": None,
        "finance_package": None,
    }


def test_planning_demo_snapshot_uses_pinned_seed_and_separate_budget_scopes() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/planning/demo-snapshot")

    assert response.status_code == 200
    catalog = response.json()
    assert catalog["snapshot"]["data_snapshot_id"] == "hcmc-nine-wards-demo-v3"
    assert catalog["study_area"] == {
        "city_id": "VN-HCMC",
        "boundary_version": "ADMINISTRATIVE_2025",
        "pilot_extent_id": "hcmc-nine-wards-demo-v3",
    }
    assert len(catalog["candidates"]) == 18
    assert len(catalog["existing_sites"]) == 37
    assert len(catalog["demand_nodes"]) == 27
    node_wards = {node["unit_id"] for node in catalog["demand_nodes"]}
    assert all(site["unit_id"] in node_wards and site["unit_name"]
               for site in [*catalog["candidates"], *catalog["existing_sites"]])
    assert catalog["defaults"]["budget_vnd"] is None
    assert catalog["defaults"]["portfolio_budget_vnd"] == 10_000_000_000


def test_demo_recommendations_compare_sensitivity_and_keep_finance_unavailable() -> None:
    with TestClient(app) as client:
        catalog_response = client.get("/api/v1/planning/demo-snapshot")
        assert catalog_response.status_code == 200
        catalog = catalog_response.json()

        five_minute_response = client.post(
            "/api/v1/planning/recommendations",
            json=_planning_request(catalog, coverage_minutes=5),
        )
        repeated_five_minute_response = client.post(
            "/api/v1/planning/recommendations",
            json=_planning_request(catalog, coverage_minutes=5),
        )
        fifteen_minute_response = client.post(
            "/api/v1/planning/recommendations",
            json=_planning_request(catalog, coverage_minutes=15),
        )
        low_demand_response = client.post(
            "/api/v1/planning/recommendations",
            json=_planning_request(catalog, coverage_minutes=5, demand_scenario="low"),
        )

    assert five_minute_response.status_code == 200
    assert repeated_five_minute_response.status_code == 200
    assert fifteen_minute_response.status_code == 200
    assert low_demand_response.status_code == 200
    five_minute = five_minute_response.json()
    repeated_five_minute = repeated_five_minute_response.json()
    fifteen_minute = fifteen_minute_response.json()
    low_demand = low_demand_response.json()

    assert five_minute["status"] == "completed_with_unknowns"
    assert five_minute["scenario"]["data_snapshot_id"] == "hcmc-nine-wards-demo-v3"
    assert five_minute["scenario"]["seed"] == 20261013
    assert five_minute["scenario"]["algorithm_version"] == "m2b-technical-screen-0.2.0"
    assert five_minute["scenario"]["config_version"] == "technical-demo-v1"
    assert five_minute["warnings"]
    assert any("not HCMC operating evidence" in warning for warning in five_minute["warnings"])
    assert any("pilot 9 phường" in warning for warning in five_minute["warnings"])
    assert [item["rank"] for item in five_minute["recommendations"]] == [1, 2, 3]
    assert [item["candidate_id"] for item in five_minute["recommendations"]] == [
        "cand-hcm_2025_26911-02",
        "cand-hcm_2025_27073-01",
        "cand-hcm_2025_26929-01",
    ]
    assert "run_id" in five_minute and "run_id" in repeated_five_minute
    five_minute_without_run_id = {**five_minute, "run_id": None}
    repeated_without_run_id = {**repeated_five_minute, "run_id": None}
    assert five_minute_without_run_id == repeated_without_run_id
    for item in five_minute["recommendations"]:
        assert item["metrics"]["demand_potential"]["unit"] == "sessions_per_week"
        assert item["metrics"]["demand_potential"]["status"] == "synthetic"
        assert item["metrics"]["coverage_gain"]["unit"] == "percent_total_demand"
        assert {part["component_id"] for part in item["score_breakdown"]} >= {
            "demand_potential",
            "marginal_coverage",
        }
        constraints = {constraint["id"]: constraint["status"] for constraint in item["constraints"]}
        assert constraints["grid_capacity"] == "unknown"
        assert constraints["candidate_type"] == "conditional"
        assert any(source["is_synthetic"] for source in item["provenance"])
    assert [item["candidate_id"] for item in fifteen_minute["recommendations"]] == [
        "cand-hcm_2025_26929-01",
        "cand-hcm_2025_26911-02",
        "cand-hcm_2025_27073-01",
    ]
    five_minute_gains = {
        item["candidate_id"]: item["metrics"]["coverage_gain"]["value"]
        for item in five_minute["recommendations"]
    }
    fifteen_minute_gains = {
        item["candidate_id"]: item["metrics"]["coverage_gain"]["value"]
        for item in fifteen_minute["recommendations"]
    }
    assert five_minute_gains["cand-hcm_2025_26929-01"] == pytest.approx(5.5717, abs=0.001)
    assert all(value == 0 for value in fifteen_minute_gains.values())

    base_demand = five_minute["recommendations"][0]["metrics"]["demand_potential"]["value"]
    low_demand_value = low_demand["recommendations"][0]["metrics"]["demand_potential"]["value"]
    assert low_demand_value < base_demand
    assert five_minute["scenario"]["demand_scenario"] == "base"
    assert low_demand["scenario"]["demand_scenario"] == "low"
    assert "estimated_cost" in five_minute["recommendations"][0]["metrics"]
    assert five_minute["recommendations"][0]["metrics"]["estimated_cost"]["status"] == "synthetic"
    assert "roi" not in five_minute["recommendations"][0]["metrics"]
    assert all(
        constraint["status"] in {"conditional", "unknown", "not_applicable", "pass"}
        for item in five_minute["recommendations"]
        for constraint in item["constraints"]
    )


def test_demo_reports_no_feasible_candidates_for_explicit_tiny_budget_scenario() -> None:
    with TestClient(app) as client:
        catalog = client.get("/api/v1/planning/demo-snapshot").json()
        request = _planning_request(catalog, coverage_minutes=5)
        request["technical"]["budget_vnd"] = 1
        response = client.post("/api/v1/planning/recommendations", json=request)

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "no_feasible_candidates"
    assert result["recommendations"] == []
    assert len(result["excluded_candidates"]) == len(DEMO_CANDIDATE_IDS)
    assert all(
        constraint["id"] == "individual_budget" and constraint["status"] == "fail"
        for item in result["excluded_candidates"]
        for constraint in item["constraints"]
    )


def test_heatmap_weekly_values_match_the_pinned_demand_intervals() -> None:
    path = (Path(__file__).resolve().parents[2] / "data_platform" / "station_planning"
            / "demo_hcmc_v3" / "demand_intervals.csv")
    totals = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["demand_node_id"] or row["cell_id"], row["scenario_profile"])
            totals[key] = totals.get(key, 0.0) + float(row["expected_sessions"])
    with TestClient(app) as client:
        response = client.get("/api/v1/planning/demo-snapshot")
    assert response.status_code == 200
    nodes = response.json()["demand_nodes"]
    for node in nodes:
        values = node["weekly_expected_sessions"]
        assert set(values) == {"low", "base", "high"}
        assert 0 <= values["low"] < values["base"] < values["high"]
        for profile, value in values.items():
            assert value == pytest.approx(totals[(node["demand_node_id"], profile)], abs=1e-6)
    assert len(totals) == len(nodes) * 3


def test_load_simulation_uses_one_simultaneous_peak_from_the_fixture() -> None:
    path = (Path(__file__).resolve().parents[2] / "data_platform" / "station_planning"
            / "demo_hcmc_v3" / "demand_intervals.csv")
    by_interval = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            key = (row["scenario_profile"], row["interval_start"])
            by_interval.setdefault(key, {})[row["demand_node_id"]] = float(row["expected_sessions"])
    with TestClient(app) as client:
        catalog = client.get("/api/v1/planning/demo-snapshot").json()
    inputs = catalog["load_simulation"]
    assert inputs["nearby_drive_minutes"] == 2
    assert inputs["fixed_access_minutes"] == 2
    assert inputs["minimum_service_minutes"] == inputs["interval_minutes"] == 30
    assert inputs["energy_per_session_kwh"] == 26
    for profile, peak in inputs["peak_by_scenario"].items():
        selected = by_interval[(profile, peak["interval_start"])]
        assert len(selected) == 27
        assert peak["sessions_by_node"] == selected
        assert sum(selected.values()) == max(
            sum(values.values()) for (source, _), values in by_interval.items() if source == profile
        )
