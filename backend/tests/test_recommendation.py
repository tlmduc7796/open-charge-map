from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app.domain.models import PortRuntimeStatus
from backend.app.domain.phase7_models import RecommendationItem
from backend.app.domain.recommendation import RecommendationService
from backend.app.main import app, persist_occupancy_forecasts


def _rank_item(
    station_id: str,
    total_time_min: float,
    minimum_soc: float,
    wait_probability: float | None,
):
    return SimpleNamespace(
        station_id=station_id,
        total_time_min=total_time_min,
        minimum_soc=minimum_soc,
        wait_probability=wait_probability,
    )


def test_total_time_rank_uses_only_documented_tie_breaks_within_tolerance() -> None:
    items = [
        _rank_item("STATION_C", 10.20, 0.99, 0.1),
        _rank_item("STATION_B", 10.05, 0.8, 0.2),
        _rank_item("STATION_A", 10.00, 0.8, 0.2),
        _rank_item("STATION_SAFER", 10.09, 0.9, 0.8),
    ]
    ordered = RecommendationService._rank_by_total_time(items)

    assert [item.station_id for item in ordered] == [
        "STATION_SAFER",
        "STATION_A",
        "STATION_B",
        "STATION_C",
    ]


def test_total_time_tolerance_groups_are_anchored_to_fastest_candidate() -> None:
    items = [
        _rank_item("FAST", 10.00, 0.5, 0.1),
        _rank_item("NEAR_TIE", 10.09, 0.6, 0.1),
        _rank_item("OUTSIDE_GROUP", 10.18, 1.0, 0.0),
    ]

    ordered = RecommendationService._rank_by_total_time(items)

    # The 0.1-minute tolerance is measured from each group's fastest candidate;
    # it must not chain through adjacent candidates and reorder a wider range.
    assert [item.station_id for item in ordered] == [
        "NEAR_TIE",
        "FAST",
        "OUTSIDE_GROUP",
    ]


def test_recommendation_still_finds_a_station_when_direct_trip_needs_no_charge() -> None:
    service = app.state.recommendation_service
    base_scenario = app.state.domain_data.demo_scenarios.get("SCN_LOW_SOC")
    scenario = base_scenario.model_copy(update={"initial_soc": 1.0})
    vehicle = app.state.domain_data.vehicles.get(scenario.vehicle_id)
    direct_route = next(
        route
        for route_id in scenario.route_ids
        if (route := service._routing.cached_route(route_id)) is not None
        and not route.waypoints
    )
    direct_destination_soc = 1.0 - (
        direct_route.distance_m / 1000 * vehicle.consumption_wh_km / 1000
    ) / vehicle.calculation_battery_kwh
    assert direct_destination_soc >= vehicle.reserve_soc

    result = service.recommend_scenario(scenario)

    assert result.outcome == "charging_stops"
    assert result.recommendations


def test_release_recommendation_reads_candidate_statuses_in_one_batch(monkeypatch) -> None:
    service = app.state.recommendation_service
    scenario = app.state.domain_data.demo_scenarios.get("SCN_LOW_SOC")
    vehicle = app.state.domain_data.vehicles.get(scenario.vehicle_id).model_copy(
        update={"is_synthetic": False, "synthetic_fields": ()}
    )

    class RuntimeSpy:
        def __init__(self) -> None:
            self.requested_ids = None

        def refresh(self) -> None:
            raise AssertionError("release recommendation must not scan all statuses")

        def get_many(self, station_ids: tuple[str, ...]):
            self.requested_ids = station_ids
            return ()

        def get(self, _station_id: str):
            raise AssertionError("release recommendation must not query statuses one by one")

        def active_event_ids(self) -> tuple[str, ...]:
            return ()

    candidate = app.state.domain_data.stations.get("ST_VF_LA_VELA")

    class OneStationCandidate:
        def candidates(self, *_args, **_kwargs):
            assert _kwargs["include_synthetic"] is False
            assert _kwargs["limit"] == 2
            return (candidate, candidate)

    class VehicleReader:
        def get(self, _vehicle_id: str):
            return vehicle

    class IncidentReader:
        def active_ranking_impacts(self, station_ids: tuple[str, ...]):
            assert station_ids == (candidate.station_id,)
            return ({"station_id": candidate.station_id, "incident_type": "safety_concern"},)

    runtime = RuntimeSpy()
    monkeypatch.setattr(service, "_runtime", runtime)
    monkeypatch.setattr(service, "_allow_synthetic_data", False)
    monkeypatch.setattr(service, "_max_candidates", 1)
    monkeypatch.setattr(service, "_stations", OneStationCandidate())
    monkeypatch.setattr(service, "_vehicles", VehicleReader())
    monkeypatch.setattr(service, "_incident_impacts", IncidentReader())

    result = service.recommend_scenario(scenario)

    assert result.outcome == "no_reachable_station"
    assert runtime.requested_ids == (candidate.station_id,)
    assert result.flags == ("RECOMMENDATION_CANDIDATE_LIMIT_REACHED",)
    assert result.excluded_candidates[0].station_id == candidate.station_id
    assert result.excluded_candidates[0].reason_codes == ("ACTIVE_SAFETY_INCIDENT",)


def test_release_recommendation_rejects_vehicle_with_synthetic_fields(monkeypatch) -> None:
    service = app.state.recommendation_service
    scenario = app.state.domain_data.demo_scenarios.get("SCN_LOW_SOC")
    vehicle = app.state.domain_data.vehicles.get(scenario.vehicle_id).model_copy(
        update={"is_synthetic": False, "synthetic_fields": ("max_dc_power_kw",)}
    )

    class VehicleReader:
        def get(self, _vehicle_id: str):
            return vehicle

    monkeypatch.setattr(service, "_allow_synthetic_data", False)
    monkeypatch.setattr(service, "_vehicles", VehicleReader())

    with pytest.raises(ValueError, match="synthetic vehicle profiles"):
        service.recommend_scenario(scenario)


def test_release_recommendation_excludes_when_only_incompatible_ports_are_online(
    monkeypatch,
) -> None:
    service = app.state.recommendation_service
    scenario = app.state.domain_data.demo_scenarios.get("SCN_LOW_SOC")
    station = app.state.domain_data.stations.get("ST_VF_LANDMARK_81")
    vehicle = app.state.domain_data.vehicles.get("EV_VF5_PLUS").model_copy(
        update={
            "ac_connectors": (),
            "dc_connectors": ("CCS2",),
            "is_synthetic": False,
            "synthetic_fields": (),
        }
    )
    ccs_ports = sum(
        connector.count
        for connector in station.properties.connectors
        if connector.type == "CCS2"
    )
    type2_ports = sum(
        connector.count
        for connector in station.properties.connectors
        if connector.type == "Type2"
    )
    base_status = app.state.domain_data.station_statuses.get(station.station_id)
    status = base_status.model_copy(
        update={
            "operational_ports": type2_ports,
            "occupied_ports": 0,
            "available_ports": type2_ports,
            "offline_ports": ccs_ports,
            "unknown_ports": 0,
            "occupancy_ratio": 0,
            "queue_length": 0,
            "avg_session_duration_min": 30,
            "data_source": "station_api",
            "is_stale": False,
            "port_runtime_statuses": tuple(
                PortRuntimeStatus(
                    connector_types=(connector.type,),
                    state=(
                        "out_of_service" if connector.type == "CCS2" else "available"
                    ),
                )
                for connector in station.properties.connectors
                for _ in range(connector.count)
            ),
        }
    )

    class RuntimeReader:
        def refresh(self) -> None:
            raise AssertionError("release recommendation must not refresh all statuses")

        def get_many(self, _station_ids: tuple[str, ...]):
            return (status,)

        def active_event_ids(self) -> tuple[str, ...]:
            return ()

    class CandidateReader:
        def candidates(self, *_args, **_kwargs):
            return (station,)

    class VehicleReader:
        def get(self, _vehicle_id: str):
            return vehicle

    monkeypatch.setattr(service, "_runtime", RuntimeReader())
    monkeypatch.setattr(service, "_allow_synthetic_data", False)
    monkeypatch.setattr(service, "_stations", CandidateReader())
    monkeypatch.setattr(service, "_vehicles", VehicleReader())
    monkeypatch.setattr(service, "_incident_impacts", None)

    result = service.recommend_scenario(scenario)

    assert result.outcome == "no_reachable_station"
    exclusions = {item.station_id: item.reason_codes for item in result.excluded_candidates}
    assert exclusions[station.station_id] == ("NO_COMPATIBLE_PORT_AVAILABLE",)

def test_normal_recommendation_is_explainable_and_excludes_private_station() -> None:
    app.state.runtime_state.reset()
    app.state.planned_arrival_store.reset()

    result = app.state.recommendation_service.recommend("SCN_LOW_SOC")

    assert result.ranking_policy_version == "total_expected_time_v1"
    assert result.scoring_method == "fixed_threshold_weighted_sum"
    assert len(result.recommendations) > 1
    assert [item.rank for item in result.recommendations] == list(
        range(1, len(result.recommendations) + 1)
    )
    assert all(
        left.total_time_min <= right.total_time_min + 0.1
        for left, right in zip(
            result.recommendations,
            result.recommendations[1:],
            strict=False,
        )
    )
    assert all(
        abs(
            item.total_time_min
            - item.drive_to_station_min
            - item.estimated_wait_min
            - item.estimated_charge_min
            - item.drive_station_to_destination_min
        )
        <= 0.01
        for item in result.recommendations
    )
    assert all(0 <= item.final_score <= 1 for item in result.recommendations)
    assert all(item.wait_p90_min is not None for item in result.recommendations)
    assert all(
        item.wait_expected_min == item.estimated_wait_min
        and item.charge_min == item.estimated_charge_min
        and item.soc_after_charge is not None
        and item.predicted_free_ports is not None
        for item in result.recommendations
    )
    assert any(
        "LEG_METRICS_APPROXIMATED" in item.flags
        for item in result.recommendations
    )
    assert all(item.prediction_source == "persistence" for item in result.recommendations)
    assert "cost" not in result.model_dump_json().lower()
    exclusions = {
        item.station_id: item.reason_codes for item in result.excluded_candidates
    }
    assert exclusions["ST_EVO_AUDI_HCM"] == ("NON_PUBLIC_ACCESS",)


def test_recommendation_contract_rejects_inconsistent_total_time() -> None:
    app.state.runtime_state.reset()
    app.state.planned_arrival_store.reset()
    item = app.state.recommendation_service.recommend("SCN_LOW_SOC").recommendations[0]
    legacy_payload = item.model_dump()
    legacy_payload.pop("wait_expected_min")
    legacy_payload.pop("charge_min")
    assert RecommendationItem.model_validate(legacy_payload).total_time_min == item.total_time_min

    invalid_payload = item.model_dump()
    invalid_payload["total_time_min"] += 1

    with pytest.raises(ValidationError, match="total_time_min must equal"):
        RecommendationItem.model_validate(invalid_payload)


def test_recommendation_result_rejects_naive_generated_at() -> None:
    app.state.runtime_state.reset()
    app.state.planned_arrival_store.reset()
    result = app.state.recommendation_service.recommend("SCN_LOW_SOC")
    payload = result.model_dump()
    payload["generated_at"] = "2026-09-25T18:00:00"

    with pytest.raises(ValidationError, match="generated_at requires timezone"):
        type(result).model_validate(payload)


def test_recommendation_preserves_the_model_version_used_for_forecast(monkeypatch) -> None:
    service = app.state.recommendation_service
    delegate = service._forecasting

    class VersionedForecast:
        def forecast_occupancy(self, *args, **kwargs):
            result = delegate.forecast_occupancy(*args, **kwargs)
            return result.model_copy(
                update={
                    "prediction_source": "model",
                    "model_version": "occupancy-test-v2",
                }
            )

    monkeypatch.setattr(service, "_forecasting", VersionedForecast())

    result = service.recommend("SCN_LOW_SOC")

    assert result.recommendations
    assert {item.model_version for item in result.recommendations} == {
        "occupancy-test-v2"
    }


def test_recommendation_persists_occupancy_forecasts_as_one_batch(monkeypatch) -> None:
    service = app.state.recommendation_service
    batches = []
    monkeypatch.setattr(service, "_prediction_writer", batches.append)

    service.recommend("SCN_LOW_SOC")

    assert len(batches) == 1
    assert batches[0]
    assert all(forecast.station_id for forecast in batches[0])


def test_prediction_history_persistence_failure_does_not_abort_recommendation(
    monkeypatch,
) -> None:
    service = app.state.recommendation_service

    class FailingPredictionRepository:
        def save_occupancy_forecasts(self, _forecasts) -> int:
            raise RuntimeError("prediction history storage unavailable")

    monkeypatch.setattr(app.state, "prediction_repository", FailingPredictionRepository())
    monkeypatch.setattr(service, "_prediction_writer", persist_occupancy_forecasts)

    result = service.recommend("SCN_LOW_SOC")

    assert result.recommendations


def test_incompatible_and_unreachable_candidates_are_filtered() -> None:
    service = app.state.recommendation_service
    base = app.state.domain_data.demo_scenarios.get("SCN_LOW_SOC")

    incompatible = base.model_copy(
        update={"scenario_id": "TEST_GBT", "vehicle_id": "EV_GBT_CITY_DEMO"}
    )
    incompatible_result = service.recommend_scenario(incompatible)
    assert incompatible_result.recommendations == ()
    incompatible_reasons = {
        reason
        for exclusion in incompatible_result.excluded_candidates
        for reason in exclusion.reason_codes
    }
    assert "NO_COMPATIBLE_CONNECTOR" in incompatible_reasons

    unreachable = app.state.domain_data.demo_scenarios.get("SCN_NORMAL").model_copy(
        update={"scenario_id": "TEST_LOW_SOC", "initial_soc": 0.10}
    )
    unreachable_result = service.recommend_scenario(unreachable)
    assert unreachable_result.recommendations == ()
    assert unreachable_result.fallback_candidate is not None
    assert unreachable_result.fallback_candidate.is_reachable is False
    assert unreachable_result.fallback_candidate.straight_line_distance_m > 0
    assert unreachable_result.fallback_candidate.reason_codes
    unreachable_reasons = {
        reason
        for exclusion in unreachable_result.excluded_candidates
        for reason in exclusion.reason_codes
    }
    assert "INSUFFICIENT_SOC_RESERVE" in unreachable_reasons


def test_port_outage_event_changes_recommendation() -> None:
    app.state.runtime_state.reset()
    app.state.planned_arrival_store.reset()
    service = app.state.recommendation_service

    scenario = app.state.domain_data.demo_scenarios.get(
        "SCN_PORT_OUTAGE_REROUTE"
    ).model_copy(update={"scenario_id": "TEST_PORT_OUTAGE", "initial_soc": 0.14})
    before = service.recommend_scenario(scenario)
    after = service.recommend_scenario(
        scenario, apply_scenario_events=True
    )

    assert before.recommendations[0].station_id == "ST_VF_LA_VELA"
    assert after.recommendations[0].station_id != "ST_VF_LA_VELA"
    exclusions = {
        item.station_id: item.reason_codes for item in after.excluded_candidates
    }
    assert exclusions["ST_VF_LA_VELA"] == ("STATION_OFFLINE",)
