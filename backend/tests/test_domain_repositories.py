from backend.app.config import load_settings
from backend.app.domain.repositories import load_domain_data


def test_phase5_data_loads_with_complete_station_coverage() -> None:
    domain_data = load_domain_data(load_settings().data_dir)

    stations = domain_data.stations.all()
    vehicles = domain_data.vehicles.all()
    statuses = domain_data.station_statuses.all()

    assert len(stations) == 16
    assert len(vehicles) == 3
    assert {station.station_id for station in stations} == {
        status.station_id for status in statuses
    }
    assert len(domain_data.planned_arrivals.all()) == 4
    assert domain_data.queue_assumptions.baseline_rate("ST_EVO_LAVIDA_Q7") == 0.6
    assert len(domain_data.routes.all()) == 16
    assert len(domain_data.demo_events.all()) == 4
    assert len(domain_data.demo_scenarios.all()) == 4


def test_repository_lookup_returns_validated_records() -> None:
    domain_data = load_domain_data(load_settings().data_dir)

    audi = domain_data.stations.get("ST_EVO_AUDI_HCM")
    audi_status = domain_data.station_statuses.get("ST_EVO_AUDI_HCM")
    vf5 = domain_data.vehicles.get("EV_VF5_PLUS")

    assert audi.properties.access == "private"
    assert audi.properties.total_ports == audi_status.total_ports == 4
    assert vf5.calculation_battery_kwh == 37.23
