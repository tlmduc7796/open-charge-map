import pytest

from backend.app.config import load_settings
from backend.app.domain.repositories import DomainData, load_domain_data
from backend.app.domain.services import (
    check_compatibility,
    estimate_charging,
    estimate_reachability,
)


@pytest.fixture(scope="module")
def domain_data() -> DomainData:
    return load_domain_data(load_settings().data_dir)


def test_connector_mismatch_is_rejected(domain_data: DomainData) -> None:
    vehicle = domain_data.vehicles.get("EV_GBT_CITY_DEMO")
    station = domain_data.stations.get("ST_EVO_LAVIDA_Q7")

    result = check_compatibility(vehicle, station)

    assert result.compatible is False
    assert result.matched_connectors == ()
    assert result.effective_power_kw == 0
    assert result.reason_codes == ("NO_COMPATIBLE_CONNECTOR",)


def test_effective_power_uses_vehicle_limit_for_matching_current(
    domain_data: DomainData,
) -> None:
    vehicle = domain_data.vehicles.get("EV_VF5_PLUS")
    station = domain_data.stations.get("ST_EVO_AUDI_HCM")

    result = check_compatibility(vehicle, station)

    assert result.compatible is True
    assert result.matched_connectors == ("CCS2", "Type2")
    assert result.vehicle_max_power_kw == 50
    assert result.station_max_power_kw == 180
    assert result.effective_power_kw == 50
    assert result.reason_codes == ("MATCHED_CCS2", "MATCHED_TYPE2")


def test_ac_effective_power_uses_lower_vehicle_limit(domain_data: DomainData) -> None:
    vehicle = domain_data.vehicles.get("EV_VF5_PLUS")
    station = domain_data.stations.get("ST_EVO_DEUTSCHES_HAUS")

    result = check_compatibility(vehicle, station)

    assert result.vehicle_max_power_kw == 6.6
    assert result.station_max_power_kw == 22
    assert result.effective_power_kw == 6.6


def test_insufficient_soc_is_not_reachable(domain_data: DomainData) -> None:
    vehicle = domain_data.vehicles.get("EV_VF5_PLUS")
    station = domain_data.stations.get("ST_EVO_LAVIDA_Q7")

    result = estimate_reachability(
        vehicle,
        station,
        route_distance_m=10_000,
        initial_soc=0.10,
    )

    assert result.trip_energy_kwh == pytest.approx(1.241)
    assert result.estimated_arrival_soc < vehicle.reserve_soc
    assert result.reachable is False


def test_arrival_at_reserve_soc_is_reachable(domain_data: DomainData) -> None:
    vehicle = domain_data.vehicles.get("EV_VF5_PLUS")
    station = domain_data.stations.get("ST_EVO_LAVIDA_Q7")

    result = estimate_reachability(
        vehicle,
        station,
        route_distance_m=0,
        initial_soc=vehicle.reserve_soc,
    )

    assert result.estimated_arrival_soc == vehicle.reserve_soc
    assert result.reachable is True


def test_reachability_rejects_invalid_inputs(domain_data: DomainData) -> None:
    vehicle = domain_data.vehicles.get("EV_VF5_PLUS")
    station = domain_data.stations.get("ST_EVO_LAVIDA_Q7")

    with pytest.raises(ValueError, match="route_distance_m"):
        estimate_reachability(
            vehicle,
            station,
            route_distance_m=-1,
            initial_soc=0.5,
        )


def test_charging_estimate_uses_battery_power_and_efficiency(
    domain_data: DomainData,
) -> None:
    vehicle = domain_data.vehicles.get("EV_VF5_PLUS")
    station = domain_data.stations.get("ST_EVO_LAVIDA_Q7")

    result = estimate_charging(
        vehicle,
        station,
        arrival_soc=0.20,
        target_soc=0.80,
        effective_power_kw=50,
    )

    assert result.energy_to_add_kwh == pytest.approx(22.338)
    assert result.estimated_charge_min == pytest.approx(29.784)


def test_no_charging_is_needed_at_or_above_target(domain_data: DomainData) -> None:
    vehicle = domain_data.vehicles.get("EV_VF5_PLUS")
    station = domain_data.stations.get("ST_EVO_LAVIDA_Q7")

    result = estimate_charging(
        vehicle,
        station,
        arrival_soc=0.85,
        target_soc=0.80,
        effective_power_kw=0,
    )

    assert result.energy_to_add_kwh == 0
    assert result.estimated_charge_min == 0


def test_positive_charge_rejects_zero_effective_power(domain_data: DomainData) -> None:
    vehicle = domain_data.vehicles.get("EV_VF5_PLUS")
    station = domain_data.stations.get("ST_EVO_LAVIDA_Q7")

    with pytest.raises(ValueError, match="effective_power_kw must be positive"):
        estimate_charging(
            vehicle,
            station,
            arrival_soc=0.20,
            target_soc=0.80,
            effective_power_kw=0,
        )
