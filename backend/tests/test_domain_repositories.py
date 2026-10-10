from datetime import UTC, datetime

from backend.app.catalog_repository import _station_from_row, _vehicle_from_row
from backend.app.config import load_settings
from backend.app.domain.repositories import load_domain_data


def test_phase5_data_loads_with_complete_station_coverage() -> None:
    domain_data = load_domain_data(load_settings().data_dir)

    stations = domain_data.stations.all()
    vehicles = domain_data.vehicles.all()
    statuses = domain_data.station_statuses.all()

    assert stations
    assert vehicles
    assert {station.station_id for station in stations} == {
        status.station_id for status in statuses
    }
    assert all(
        arrival.station_id in {station.station_id for station in stations}
        for arrival in domain_data.planned_arrivals.all()
    )
    assert domain_data.queue_assumptions.baseline_rate("ST_EVO_LAVIDA_Q7") == 0.6
    assert domain_data.routes.all()
    assert domain_data.demo_events.all()
    assert domain_data.demo_scenarios.all()


def test_repository_lookup_returns_validated_records() -> None:
    domain_data = load_domain_data(load_settings().data_dir)

    audi = domain_data.stations.get("ST_EVO_AUDI_HCM")
    audi_status = domain_data.station_statuses.get("ST_EVO_AUDI_HCM")
    vf5 = domain_data.vehicles.get("EV_VF5_PLUS")

    assert audi.properties.access == "private"
    assert audi.properties.total_ports == audi_status.total_ports == 4
    assert vf5.calculation_battery_kwh == 37.23
    assert not vf5.is_release_eligible


def test_vehicle_synthetic_fields_make_profile_ineligible_for_release() -> None:
    vehicle = load_domain_data(load_settings().data_dir).vehicles.get("EV_VF5_PLUS")
    field_marked_synthetic = vehicle.model_copy(
        update={"is_synthetic": False, "synthetic_fields": ("max_dc_power_kw",)}
    )

    assert not field_marked_synthetic.is_release_eligible


def test_database_catalog_mappers_preserve_import_provenance() -> None:
    source_updated_at = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
    station = _station_from_row(
        {
            "connectors": [{
                "type": "CCS2",
                "current": "DC",
                "max_power_kw": 120,
                "count": 1,
                "source": "operator_verified",
            }],
            "code": "OPS-001",
            "provider_station_id": "source-001",
            "name": "Operational station",
            "address": "Test address",
            "operator_name": "Operator",
            "longitude": 106.7,
            "latitude": 10.8,
            "opening_hours": None,
            "access_level": "public",
            "access_note": None,
            "source_updated_at": source_updated_at,
            "source_updated_at_basis": "source",
            "provenance": {"name": {"provider": "operator_feed"}},
            "amenities": [],
        }
    )
    vehicle = _vehicle_from_row(
        {
            "code": "MODEL-001",
            "brand": "Maker",
            "model": "Model",
            "variant": None,
            "battery_kwh": 76,
            "consumption_kwh_per_100km": 17,
            "max_ac_kw": 11,
            "max_dc_kw": 150,
            "market": "VN",
            "provenance": {
                "catalog_import": {"source": "manufacturer specification"},
                "_calculation_defaults": {
                    "reserve_soc": 0.1,
                    "default_target_soc": 0.8,
                    "charging_efficiency": 0.92,
                },
            },
            "connectors": [{"code": "CCS2", "current": "DC"}],
        }
    )

    assert station.properties.source_updated_at == source_updated_at
    assert station.properties.source_updated_at_basis == "source"
    assert station.properties.source_provider == "operator_feed"
    assert vehicle.source == "manufacturer specification"


def test_station_repository_pages_are_stable_and_filter_synthetic_records() -> None:
    stations = load_domain_data(load_settings().data_dir).stations
    eligible = stations.page(limit=200, include_synthetic=False)
    first = stations.page(limit=1, include_synthetic=True)
    second = stations.page(
        limit=1,
        after_station_id=first[0].station_id,
        include_synthetic=True,
    )

    assert first and second
    assert first[0].station_id < second[0].station_id
    assert all(not stations._is_synthetic(station) for station in eligible)
