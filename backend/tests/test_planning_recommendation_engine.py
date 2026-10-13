from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

from backend.app.planning.api_models import (
    PlanningRecommendationRequest,
    PlanningRecommendationResponse,
)
from backend.app.planning.domain import PlanningRunConfig
from backend.app.planning.recommendation_engine import (
    SensitivityCase,
    TechnicalOpportunityEngine,
    TechnicalScoringConfig,
)
from backend.app.planning.service import PlanningApplicationService


def _config(candidate_ids: tuple[str, ...] = ("candidate-a", "candidate-b")) -> PlanningRunConfig:
    return PlanningRunConfig(
        city_id="hcmc",
        boundary_version="boundary-v1",
        pilot_extent_id="pilot-v1",
        as_of=datetime(2026, 10, 13, tzinfo=UTC),
        horizon_years=3,
        data_snapshot_id="snapshot-v1",
        seed=7,
        config_version="technical-demo-v1",
        candidate_ids=candidate_ids,
        profile="technical_opportunity",
        coverage_minutes=15,
        charger_options=({"charger_type": "DC", "port_count": 2, "power_kw_per_port": 60.0},),
        budget_vnd=None,
    )


def _source_fact(constraint_id: str, status: str = "pass") -> dict[str, object]:
    return {
        "id": constraint_id,
        "status": status,
        "reason": f"fixture {constraint_id} {status}",
        "source_id": f"source-{constraint_id}",
        "evidence_status": "synthetic",
        "confirmed_infeasible": status == "fail",
    }


def _candidate(candidate_id: str, *, lat: float = 10.2, lon: float = 106.6) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "candidate_type": "synthetic_parking_site",
        "lat": lat,
        "lon": lon,
        "covered_demand_cell_ids": [],
        "coverage_source_ids": ["coverage-v1"],
        "coverage_status": "synthetic",
        "constraints": [
            _source_fact(item)
            for item in (
                "site_access",
                "safety_permit",
                "grid_capacity",
                "road_access",
                "charger_configuration",
            )
        ],
        "grid_capacity_kw": {
            "value": 200.0,
            "unit": "kW",
            "status": "synthetic",
            "source_id": f"grid-{candidate_id}",
        },
        "network_features": {
            name: {
                "value": score,
                "unit": "score_0_100",
                "status": "synthetic",
                "source_id": f"{candidate_id}-{name}",
            }
            for name, score in (
                ("road_accessibility", 80.0),
                ("poi_dwell", 70.0),
                ("fleet_activity", 60.0),
                ("charger_mix_fit", 90.0),
            )
        },
        "provenance": [
            {
                "field": "candidate",
                "source_id": "candidate-fixture-v1",
                "status": "synthetic",
                "is_synthetic": True,
                "note": "Generated test fixture.",
            }
        ],
    }


def _cell_estimate(cell_id: str, value: float) -> dict[str, object]:
    return {
        "demand_cell_id": cell_id,
        "target": "charging_sessions",
        "value": value,
        "unit": "sessions_per_day",
        "time_window": {"start": "2027-01-01", "end": "2027-01-02"},
        "status": "synthetic",
        "source_id": "demand-generator-v1",
        "model_version": "demo-model-v1",
        "data_snapshot_id": "snapshot-v1",
        "scenario": "base",
        "uncertainty": {"low": value * 0.8, "high": value * 1.2, "method": "synthetic_range"},
    }


def _dataset(candidates: list[dict[str, object]]) -> dict[str, object]:
    return {
        "snapshot": {
            "city_id": "hcmc",
            "boundary_version": "boundary-v1",
            "pilot_extent_id": "pilot-v1",
            "data_snapshot_id": "snapshot-v1",
            "boundary_crs": "EPSG:4326",
            "boundary_source_id": "boundary-source-v1",
            "boundary_geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[106.0, 10.0], [107.0, 10.0], [107.0, 11.0], [106.0, 11.0], [106.0, 10.0]]
                ],
            },
        },
        "candidates": candidates,
        "demand_estimates": [
            _cell_estimate("cell-a", 20.0),
            _cell_estimate("cell-b", 30.0),
            _cell_estimate("cell-c", 40.0),
        ],
        "existing_covered_demand_cell_ids": ["cell-b"],
        "existing_coverage_source_ids": ["existing-sites-v1"],
        "existing_coverage_status": "synthetic",
    }


def test_cell_demand_ranking_is_deterministic_and_matches_http_contract() -> None:
    candidate_a = _candidate("candidate-a")
    candidate_b = _candidate("candidate-b", lat=10.3, lon=106.7)
    candidate_a["covered_demand_cell_ids"] = ["cell-a", "cell-b"]
    candidate_b["covered_demand_cell_ids"] = ["cell-b", "cell-c"]
    output = TechnicalOpportunityEngine().recommend(_config(), _dataset([candidate_a, candidate_b]))
    assert output == TechnicalOpportunityEngine().recommend(
        _config(), _dataset([candidate_a, candidate_b])
    )
    assert output["status"] == "completed_with_unknowns"
    assert [item["candidate_id"] for item in output["recommendations"]] == [
        "candidate-b",
        "candidate-a",
    ]
    assert output["unranked_candidates"] == []
    top = output["recommendations"][0]
    assert top["metrics"]["demand_potential"]["value"] == 70.0
    assert top["metrics"]["demand_potential"]["unit"] == "sessions_per_day"
    assert top["metrics"]["coverage_gain"]["value"] == 44.444444
    assert top["metrics"]["competition"]["value"] == 42.857143
    assert top["metrics"]["coverage_gap"]["value"] == 60.0
    assert (
        abs(
            sum(row["contribution_points"] or 0 for row in top["score_breakdown"])
            - top["technical_score"]
        )
        < 1e-5
    )
    assert top["metrics"]["overload_risk"]["value"] == "within_reported_capacity"
    assert any(item["status"] == "synthetic" for item in top["provenance"])

    payload = {
        "contract_version": "0.1",
        "run_id": "run_test",
        "status": output["status"],
        "scenario": {
            "profile": "technical_opportunity",
            "as_of": datetime(2026, 10, 13, tzinfo=UTC),
            "horizon_years": 3,
            "seed": 7,
            "data_snapshot_id": "snapshot-v1",
            "algorithm_version": TechnicalOpportunityEngine.algorithm_version,
            "config_version": "technical-demo-v1",
            "policy_package_id": None,
            "policy_package_version": None,
            "finance_package_id": None,
            "finance_package_version": None,
        },
        **output,
    }
    parsed = PlanningRecommendationResponse.model_validate(payload)
    assert [item.rank for item in parsed.recommendations] == [1, 2]


def test_unconfirmed_fail_is_conditional_not_excluded() -> None:
    candidate = _candidate("candidate-a")
    candidate["covered_demand_cell_ids"] = ["cell-a", "cell-b"]
    candidate["constraints"] = [
        _source_fact("site_access", "fail"),
        *[
            _source_fact(item)
            for item in ("safety_permit", "grid_capacity", "road_access", "charger_configuration")
        ],
    ]
    candidate["constraints"][0]["confirmed_infeasible"] = "false"
    output = TechnicalOpportunityEngine().recommend(
        _config(("candidate-a",)), _dataset([candidate])
    )
    assert output["excluded_candidates"] == []
    assert output["recommendations"][0]["constraints"][1]["status"] == "conditional"
    assert output["recommendations"][0]["eligibility"] == "conditional"


def test_candidate_with_less_evidence_is_unranked_instead_of_winning_by_missingness() -> None:
    dataset = _dataset([_candidate("candidate-a"), _candidate("candidate-b", lat=10.3)])
    dataset["demand_estimates"] = [
        {
            "candidate_id": "candidate-a",
            "target": "charging_sessions",
            "value": 20.0,
            "unit": "sessions_per_day",
            "time_window": {"start": "2027-01-01", "end": "2027-01-02"},
            "status": "synthetic",
            "source_id": "demand-v1",
            "data_snapshot_id": "snapshot-v1",
            "scenario": "base",
        }
    ]
    dataset.pop("existing_covered_demand_cell_ids")
    dataset.pop("existing_coverage_source_ids")
    for candidate in dataset["candidates"]:
        candidate.pop("covered_demand_cell_ids")
    output = TechnicalOpportunityEngine().recommend(_config(), dataset)
    assert [item["candidate_id"] for item in output["recommendations"]] == ["candidate-a"]
    assert output["unranked_candidates"][0]["candidate_id"] == "candidate-b"
    assert "Evidence coverage" in output["unranked_candidates"][0]["reason"]


def test_confirmed_source_backed_failure_is_excluded_and_can_make_run_infeasible() -> None:
    candidate = _candidate("candidate-a", lat=10.2, lon=107.2)
    output = TechnicalOpportunityEngine().recommend(
        _config(("candidate-a",)), _dataset([candidate])
    )
    assert output["status"] == "no_feasible_candidates"
    assert output["recommendations"] == []
    assert output["unranked_candidates"] == []
    assert output["excluded_candidates"][0]["constraints"][0]["id"] == "inside_boundary"


def test_confirmed_site_rights_or_candidate_type_failure_is_excluded() -> None:
    for constraint_id in ("candidate_type", "site_rights"):
        candidate = _candidate("candidate-a")
        candidate["constraints"].append(_source_fact(constraint_id, "fail"))
        output = TechnicalOpportunityEngine().recommend(
            _config(("candidate-a",)), _dataset([candidate])
        )
        assert output["status"] == "no_feasible_candidates"
        assert output["excluded_candidates"][0]["constraints"][0]["id"] == constraint_id


def test_snapshot_or_demand_unit_mismatch_returns_invalid_input() -> None:
    candidate = _candidate("candidate-a")
    dataset = _dataset([candidate])
    dataset["snapshot"]["boundary_version"] = "newer-boundary"
    output = TechnicalOpportunityEngine().recommend(_config(("candidate-a",)), dataset)
    assert output["status"] == "invalid_input"
    assert output["recommendations"] == []

    dataset = _dataset([candidate])
    dataset["demand_estimates"][0]["unit"] = "kwh_per_day"
    output = TechnicalOpportunityEngine().recommend(_config(("candidate-a",)), dataset)
    assert output["status"] == "invalid_input"
    assert "different targets, units" in output["warnings"][0]


def test_scoring_config_is_versioned_and_validated() -> None:
    config = TechnicalScoringConfig(version="partner-tech-v3")
    engine = TechnicalOpportunityEngine(config)
    assert engine.config_version == "partner-tech-v3"


def test_sensitivity_reports_scenario_and_weight_rank_movement() -> None:
    candidate_a = _candidate("candidate-a")
    candidate_b = _candidate("candidate-b", lat=10.3, lon=106.7)
    candidate_a["covered_demand_cell_ids"] = ["cell-a", "cell-b"]
    candidate_b["covered_demand_cell_ids"] = ["cell-b", "cell-c"]
    baseline_dataset = _dataset([candidate_a, candidate_b])

    high_demand_dataset = deepcopy(baseline_dataset)
    high_values = {"cell-a": 65.0, "cell-b": 20.0, "cell-c": 5.0}
    for estimate in high_demand_dataset["demand_estimates"]:
        value = high_values[estimate["demand_cell_id"]]
        estimate["value"] = value
        estimate["scenario"] = "high-demand-a"
        estimate["uncertainty"] = {
            "low": value * 0.8,
            "high": value * 1.2,
            "method": "synthetic_range",
        }

    network_dataset = deepcopy(baseline_dataset)
    for feature in network_dataset["candidates"][1]["network_features"].values():
        feature["value"] = 30.0
    network_weights = TechnicalScoringConfig(
        version="network-heavy-v1",
        weights=(
            ("demand_potential", 0.0),
            ("marginal_coverage", 0.0),
            ("grid_site_readiness", 0.0),
            ("network_segment_fit", 100.0),
            ("network_gap_fit", 0.0),
        ),
    )

    report = TechnicalOpportunityEngine().compare_sensitivity(
        _config(),
        baseline_dataset,
        [
            SensitivityCase("high-demand-a", dataset=high_demand_dataset),
            SensitivityCase(
                "network-heavy",
                dataset=network_dataset,
                scoring=network_weights,
            ),
        ],
    )

    assert report["baseline"]["recommendation_order"] == ["candidate-b", "candidate-a"]
    assert report["comparisons"][0]["recommendation_order"] == [
        "candidate-a",
        "candidate-b",
    ]
    assert report["comparisons"][1]["recommendation_order"] == [
        "candidate-a",
        "candidate-b",
    ]
    for case in report["comparisons"]:
        candidate_a_movement = next(
            item for item in case["candidate_movements"] if item["candidate_id"] == "candidate-a"
        )
        assert candidate_a_movement["baseline_rank"] == 2
        assert candidate_a_movement["case_rank"] == 1
        assert candidate_a_movement["rank_movement"] == 1
        assert candidate_a_movement["score_delta"] > 0
    assert "not probabilities" in report["interpretation"]


def test_application_service_adapts_engine_output_to_the_http_response() -> None:
    candidate_a = _candidate("candidate-a")
    candidate_b = _candidate("candidate-b", lat=10.3, lon=106.7)
    candidate_a["covered_demand_cell_ids"] = ["cell-a", "cell-b"]
    candidate_b["covered_demand_cell_ids"] = ["cell-b", "cell-c"]

    class _Repository:
        def load_dataset(self, config):
            assert config.config_version == "technical-demo-v1"
            return _dataset([candidate_a, candidate_b])

    request = PlanningRecommendationRequest.model_validate(
        {
            "contract_version": "0.1",
            "study_area": {
                "city_id": "hcmc",
                "boundary_version": "boundary-v1",
                "pilot_extent_id": "pilot-v1",
            },
            "run": {
                "as_of": "2026-10-13T00:00:00Z",
                "horizon_years": 3,
                "data_snapshot_id": "snapshot-v1",
                "seed": 7,
                "config_version": None,
            },
            "candidate_source": {
                "mode": "provided",
                "candidate_ids": ["candidate-a", "candidate-b"],
            },
            "profile": "technical_opportunity",
            "technical": {
                "coverage_minutes": 15,
                "charger_options": [
                    {"charger_type": "DC", "port_count": 2, "power_kw_per_port": 60.0}
                ],
                "budget_vnd": None,
            },
        }
    )
    response = PlanningApplicationService(_Repository(), TechnicalOpportunityEngine()).recommend(
        request
    )
    assert response.status == "completed_with_unknowns"
    assert response.scenario.config_version == "technical-demo-v1"
    assert response.scenario.algorithm_version == TechnicalOpportunityEngine.algorithm_version
    assert [item.candidate_id for item in response.recommendations] == [
        "candidate-b",
        "candidate-a",
    ]
