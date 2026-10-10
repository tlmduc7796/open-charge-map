from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.app.catalog_repository import (
    _STATION_SELECT,
    DatabaseStationRepository,
    _station_from_row,
    _status_from_row,
    _synthetic_fields,
    _vehicle_from_row,
)


class _Result:
    def mappings(self):
        return ()


class _Connection:
    def __init__(self, capture: dict) -> None:
        self.capture = capture

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters):
        self.capture["query"] = str(statement)
        self.capture["parameters"] = parameters
        return _Result()


class _Engine:
    def __init__(self) -> None:
        self.capture: dict = {}

    def connect(self):
        return _Connection(self.capture)


def test_corridor_candidates_use_a_bound_limit_and_release_filter() -> None:
    engine = _Engine()
    repository = DatabaseStationRepository(engine)

    result = repository.candidates(
        106.7,
        10.7,
        106.8,
        10.8,
        5_000,
        limit=37,
    )

    assert result == ()
    assert "LIMIT :limit" in engine.capture["query"]
    assert "origin' = 'synthetic'" in engine.capture["query"]
    assert "provider' ILIKE '%synthetic%'" in engine.capture["query"]
    assert engine.capture["parameters"]["limit"] == 37


def test_database_mapper_marks_synthetic_provider_fields_ineligible() -> None:
    assert _synthetic_fields(
        {
            "battery_kwh": {
                "origin": "observed",
                "provider": "Synthetic import feed",
            }
        }
    ) == ("battery_kwh",)
    assert _synthetic_fields(
        {
            "_calculation_defaults_provenance": {
                "reserve_soc": {
                    "origin": "operator_policy",
                    "provider": "Synthetic policy source",
                }
            }
        }
    ) == ("_calculation_defaults_provenance.reserve_soc",)


def test_database_status_preserves_connector_scoped_port_states_internally() -> None:
    status = _status_from_row(
        {
            "code": "ST_TEST",
            "reported_at": datetime.now(UTC),
            "total_ports": 2,
            "operational_ports": 2,
            "occupied_ports": 1,
            "available_ports": 1,
            "offline_ports": 0,
            "unknown_ports": 0,
            "occupancy_ratio": 0.5,
            "queue_length": 0,
            "avg_session_duration_min": 30,
            "synthetic_status": False,
            "port_runtime_statuses": [
                {"connector_types": ["CCS2"], "state": "charging"},
                {"connector_types": ["Type2"], "state": "available"},
            ],
        }
    )

    assert status.port_runtime_statuses is not None
    assert [port.connector_types for port in status.port_runtime_statuses] == [
        ("CCS2",),
        ("Type2",),
    ]
    assert "port_runtime_statuses" not in status.model_dump()


def test_catalog_query_and_mapping_preserve_power_tiers_for_same_connector() -> None:
    station = _station_from_row(
        {
            "code": "ST_POWER_TIERS",
            "name": "Reviewed station",
            "address": "1 Test Street",
            "operator_name": "Operator",
            "longitude": 106.7,
            "latitude": 10.8,
            "opening_hours": None,
            "access_level": "public",
            "access_note": None,
            "source_updated_at": datetime.now(UTC),
            "source_updated_at_basis": "source",
            "provenance": {},
            "provider_station_id": None,
            "connectors": [
                {
                    "type": "CCS2",
                    "current": "DC",
                    "max_power_kw": 120,
                    "count": 1,
                    "source": "database",
                },
                {
                    "type": "CCS2",
                    "current": "DC",
                    "max_power_kw": 180,
                    "count": 2,
                    "source": "database",
                },
            ],
            "amenities": [],
        }
    )

    power_groups = station.properties.connectors
    assert [(connector.max_power_kw, connector.count) for connector in power_groups] == [
        (120, 1),
        (180, 2),
    ]
    assert "GROUP BY p.connector_code, ct.current_type, p.max_power_kw" in _STATION_SELECT


def test_database_vehicle_preserves_nominal_and_usable_battery_capacity() -> None:
    vehicle = _vehicle_from_row(
        {
            "code": "MODEL_001",
            "brand": "Maker",
            "model": "Model",
            "variant": "Long range",
            "battery_kwh": 80,
            "usable_battery_kwh": 76,
            "consumption_kwh_per_100km": 17,
            "max_ac_kw": 11,
            "max_dc_kw": 150,
            "market": "VN",
            "provenance": {
                "battery_kwh": {"origin": "observed", "source_ref": "manufacturer"},
                "usable_battery_kwh": {
                    "origin": "observed",
                    "source_ref": "manufacturer",
                },
                "_calculation_defaults": {
                    "reserve_soc": 0.1,
                    "default_target_soc": 0.8,
                    "charging_efficiency": 0.9,
                },
            },
            "connectors": [{"code": "CCS2", "current": "DC"}],
        }
    )

    assert vehicle.battery_capacity_kwh == 80
    assert vehicle.usable_battery_kwh == 76
    assert vehicle.calculation_battery_kwh == 76


@pytest.mark.parametrize("limit", [0, -1, 502])
def test_corridor_candidate_query_rejects_unbounded_limits(limit: int) -> None:
    repository = DatabaseStationRepository(_Engine())

    with pytest.raises(ValueError, match="candidate query limit"):
        repository.candidates(106.7, 10.7, 106.8, 10.8, 5_000, limit=limit)
