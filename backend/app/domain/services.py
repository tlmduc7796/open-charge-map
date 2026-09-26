"""Pure Phase 05 calculations using kW, kWh, meters, minutes, and SOC ratios."""

from __future__ import annotations

import re

from backend.app.domain.models import (
    ChargingEstimateResult,
    CompatibilityResult,
    Connector,
    ReachabilityResult,
    Station,
    Vehicle,
)


def _reason_suffix(connector_type: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", connector_type.upper()).strip("_")


def _vehicle_connectors(vehicle: Vehicle, connector: Connector) -> tuple[str, ...]:
    return vehicle.ac_connectors if connector.current == "AC" else vehicle.dc_connectors


def _vehicle_power_limit(vehicle: Vehicle, connector: Connector) -> float:
    return vehicle.max_ac_power_kw if connector.current == "AC" else vehicle.max_dc_power_kw


def check_compatibility(vehicle: Vehicle, station: Station) -> CompatibilityResult:
    """Select the compatible connector path with the highest usable charging power."""
    matches: list[tuple[Connector, float, float]] = []
    for connector in station.properties.connectors:
        if connector.type in _vehicle_connectors(vehicle, connector):
            vehicle_limit = _vehicle_power_limit(vehicle, connector)
            effective_power = min(connector.max_power_kw, vehicle_limit)
            if effective_power > 0:
                matches.append((connector, vehicle_limit, effective_power))

    if not matches:
        return CompatibilityResult(
            vehicle_id=vehicle.vehicle_id,
            station_id=station.station_id,
            compatible=False,
            matched_connectors=(),
            vehicle_max_power_kw=0,
            station_max_power_kw=0,
            effective_power_kw=0,
            reason_codes=("NO_COMPATIBLE_CONNECTOR",),
        )

    selected_connector, vehicle_limit, effective_power = max(
        matches, key=lambda match: (match[2], match[0].max_power_kw)
    )
    matched_types = tuple(dict.fromkeys(match[0].type for match in matches))
    reason_codes = tuple(f"MATCHED_{_reason_suffix(name)}" for name in matched_types)
    return CompatibilityResult(
        vehicle_id=vehicle.vehicle_id,
        station_id=station.station_id,
        compatible=True,
        matched_connectors=matched_types,
        vehicle_max_power_kw=vehicle_limit,
        station_max_power_kw=selected_connector.max_power_kw,
        effective_power_kw=effective_power,
        reason_codes=reason_codes,
    )


def estimate_reachability(
    vehicle: Vehicle,
    station: Station,
    *,
    route_distance_m: float,
    initial_soc: float,
    route_id: str | None = None,
    route_duration_s: float | None = None,
) -> ReachabilityResult:
    if route_distance_m < 0:
        raise ValueError("route_distance_m must be non-negative")
    if route_duration_s is not None and route_duration_s < 0:
        raise ValueError("route_duration_s must be non-negative")
    if not 0 <= initial_soc <= 1:
        raise ValueError("initial_soc must be between 0 and 1")

    route_distance_km = route_distance_m / 1000
    trip_energy_kwh = route_distance_km * vehicle.consumption_wh_km / 1000
    arrival_soc = initial_soc - trip_energy_kwh / vehicle.calculation_battery_kwh

    return ReachabilityResult(
        vehicle_id=vehicle.vehicle_id,
        station_id=station.station_id,
        route_id=route_id,
        route_distance_m=route_distance_m,
        route_duration_s=route_duration_s,
        initial_soc=initial_soc,
        reserve_soc=vehicle.reserve_soc,
        trip_energy_kwh=trip_energy_kwh,
        estimated_arrival_soc=arrival_soc,
        reachable=arrival_soc >= vehicle.reserve_soc,
    )


def estimate_charging(
    vehicle: Vehicle,
    station: Station,
    *,
    arrival_soc: float,
    effective_power_kw: float,
    target_soc: float | None = None,
) -> ChargingEstimateResult:
    selected_target_soc = vehicle.default_target_soc if target_soc is None else target_soc
    if not 0 <= arrival_soc <= 1:
        raise ValueError("arrival_soc must be between 0 and 1")
    if not 0 <= selected_target_soc <= 1:
        raise ValueError("target_soc must be between 0 and 1")
    if effective_power_kw < 0:
        raise ValueError("effective_power_kw must be non-negative")

    soc_to_add = max(0.0, selected_target_soc - arrival_soc)
    energy_to_add_kwh = soc_to_add * vehicle.calculation_battery_kwh
    if energy_to_add_kwh > 0 and effective_power_kw == 0:
        raise ValueError("effective_power_kw must be positive when charging is required")
    estimated_charge_min = (
        energy_to_add_kwh / (effective_power_kw * vehicle.charging_efficiency) * 60
        if energy_to_add_kwh > 0
        else 0.0
    )

    return ChargingEstimateResult(
        vehicle_id=vehicle.vehicle_id,
        station_id=station.station_id,
        arrival_soc=arrival_soc,
        target_soc=selected_target_soc,
        energy_to_add_kwh=energy_to_add_kwh,
        effective_power_kw=effective_power_kw,
        charging_efficiency=vehicle.charging_efficiency,
        estimated_charge_min=estimated_charge_min,
    )
