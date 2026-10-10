import pytest
from app.domain.models import OccupancyForecastResult, StationProperties, StationStatus, Vehicle
from pydantic import ValidationError

from backend.app.domain.phase7_models import (
    DemoEvent,
    DemoEventEffects,
    PlannedArrivalCreateRequest,
    RouteLeg,
)


def vehicle_payload(**overrides: object) -> dict[str, object]:
    return {
        "vehicle_id": "test-ev",
        "make": "Test",
        "model": "EV",
        "battery_capacity_kwh": 80,
        "usable_battery_kwh": 76,
        "max_ac_power_kw": 11,
        "max_dc_power_kw": 150,
        "ac_connectors": ("Type2",),
        "dc_connectors": ("CCS2",),
        "consumption_wh_km": 180,
        "reserve_soc": 0.1,
        "default_target_soc": 0.8,
        "charging_efficiency": 0.9,
        "source": "reviewed specification",
        "is_synthetic": False,
        "synthetic_fields": (),
        **overrides,
    }


def test_vehicle_uses_usable_capacity_for_calculations() -> None:
    vehicle = Vehicle.model_validate(vehicle_payload())

    assert vehicle.calculation_battery_kwh == 76


def test_vehicle_with_synthetic_source_is_not_release_eligible() -> None:
    vehicle = Vehicle.model_validate(
        vehicle_payload(source="Synthetic catalog", is_synthetic=False)
    )

    assert not vehicle.is_release_eligible


def test_vehicle_rejects_usable_capacity_above_nominal_capacity() -> None:
    with pytest.raises(ValidationError, match="usable battery capacity cannot exceed"):
        Vehicle.model_validate(
            vehicle_payload(battery_capacity_kwh=70, usable_battery_kwh=76)
        )


def test_planned_arrival_request_rejects_naive_timestamps() -> None:
    payload = {
        "arrival_id": "ARR_NAIVE_TIMESTAMP",
        "station_id": "ST_TEST",
        "eta_at": "2026-10-09T09:00:00",
        "eta_window_start": "2026-10-09T08:55:00Z",
        "eta_window_end": "2026-10-09T09:05:00Z",
        "expected_energy_kwh": 20,
        "expected_charge_duration_min": 30,
        "arrival_probability": 0.8,
        "expires_at": "2026-10-09T09:15:00Z",
    }

    with pytest.raises(ValidationError, match="timestamps must include a timezone"):
        PlannedArrivalCreateRequest.model_validate(payload)


@pytest.mark.parametrize("station_id", ["ST/ONE", "..", "ST #1"])
def test_station_id_must_be_a_safe_url_path_segment(station_id: str) -> None:
    with pytest.raises(ValidationError):
        StationProperties.model_validate(
            {
                "station_id": station_id,
                "name": "Test station",
                "address": "1 Test Street",
                "total_ports": 1,
                "connectors": [
                    {
                        "type": "CCS2",
                        "current": "DC",
                        "max_power_kw": 50,
                        "count": 1,
                        "source": "operator_verified",
                    }
                ],
                "access": "public",
                "notes": [],
                "source_provider": "operator",
                "synthetic_fields": [],
            }
        )


@pytest.mark.parametrize("arrival_id", ["ARR/ONE", "..", "ARR #1"])
def test_planned_arrival_request_id_must_be_a_safe_path_segment(
    arrival_id: str,
) -> None:
    with pytest.raises(ValidationError):
        PlannedArrivalCreateRequest.model_validate(
            {
                "arrival_id": arrival_id,
                "station_id": "ST_TEST",
                "eta_at": "2026-10-09T09:00:00Z",
                "eta_window_start": "2026-10-09T08:55:00Z",
                "eta_window_end": "2026-10-09T09:05:00Z",
                "expected_energy_kwh": 20,
                "expected_charge_duration_min": 30,
                "arrival_probability": 0.8,
                "expires_at": "2026-10-09T09:15:00Z",
            }
        )


def test_planned_arrival_request_requires_eta_inside_its_window() -> None:
    payload = {
        "arrival_id": "ARR_ETA_WINDOW",
        "station_id": "ST_TEST",
        "eta_at": "2026-10-09T09:10:00Z",
        "eta_window_start": "2026-10-09T08:55:00Z",
        "eta_window_end": "2026-10-09T09:05:00Z",
        "expected_energy_kwh": 20,
        "expected_charge_duration_min": 30,
        "arrival_probability": 0.8,
        "expires_at": "2026-10-09T09:15:00Z",
    }

    with pytest.raises(ValidationError, match="eta_at must be inside its ETA window"):
        PlannedArrivalCreateRequest.model_validate(payload)


def test_planned_arrival_expiration_must_follow_eta_window() -> None:
    payload = {
        "arrival_id": "ARR_EXPIRY_WINDOW",
        "station_id": "ST_TEST",
        "eta_at": "2026-10-09T09:00:00Z",
        "eta_window_start": "2026-10-09T08:55:00Z",
        "eta_window_end": "2026-10-09T09:05:00Z",
        "expected_energy_kwh": 20,
        "expected_charge_duration_min": 30,
        "arrival_probability": 0.8,
        "expires_at": "2026-10-09T09:05:00Z",
    }

    with pytest.raises(ValidationError, match="expires_at must be after eta_window_end"):
        PlannedArrivalCreateRequest.model_validate(payload)


def test_station_status_rejects_naive_timestamp() -> None:
    payload = {
        "station_id": "ST_TEST",
        "timestamp": "2026-10-09T09:00:00",
        "total_ports": 1,
        "operational_ports": 1,
        "occupied_ports": 0,
        "available_ports": 1,
        "offline_ports": 0,
        "unknown_ports": 0,
        "occupancy_ratio": 0,
        "queue_length": None,
        "data_source": "station_api",
    }

    with pytest.raises(ValidationError, match="timestamp must include a timezone"):
        StationStatus.model_validate(payload)


def test_station_status_serializes_default_unknown_port_count() -> None:
    status = StationStatus.model_validate(
        {
            "station_id": "ST_TEST",
            "timestamp": "2026-10-09T09:00:00Z",
            "total_ports": 1,
            "operational_ports": 1,
            "occupied_ports": 0,
            "available_ports": 1,
            "offline_ports": 0,
            "occupancy_ratio": 0,
            "queue_length": None,
            "data_source": "station_api",
        }
    )

    assert status.model_dump()["unknown_ports"] == 0


def test_route_leg_rejects_naive_retrieval_timestamp() -> None:
    payload = {
        "origin": {"lat": 10.0, "lon": 106.0},
        "destination": {"lat": 10.1, "lon": 106.1},
        "distance_m": 1000,
        "duration_s": 300,
        "provider": "goong",
        "retrieved_at": "2026-10-09T09:00:00",
    }

    with pytest.raises(ValidationError, match="retrieved_at requires timezone"):
        RouteLeg.model_validate(payload)


def test_demo_event_rejects_naive_timestamps() -> None:
    payload = {
        "event_id": "event-test",
        "event_type": "congestion",
        "station_id": "ST_TEST",
        "start_at": "2026-10-09T09:00:00",
        "severity": "low",
        "effects": DemoEventEffects(),
        "is_synthetic": True,
    }

    with pytest.raises(ValidationError, match="demo event timestamps must include"):
        DemoEvent.model_validate(payload)


def test_forecast_result_rejects_naive_timestamps() -> None:
    payload = {
        "station_id": "ST_TEST",
        "generated_at": "2026-10-09T09:00:00",
        "target_at": "2026-10-09T09:05:00Z",
        "requested_horizon_min": 5,
        "used_horizon_min": 5,
        "predicted_occupancy_ratio": 0.5,
        "predicted_occupied_ports": 1,
        "operational_ports": 2,
        "prediction_source": "persistence",
        "flags": (),
    }

    with pytest.raises(ValidationError, match="forecast timestamps must include"):
        OccupancyForecastResult.model_validate(payload)
