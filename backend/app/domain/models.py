"""Validated models for the Phase 05 static, runtime, and derived data."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Connector(DomainModel):
    type: str = Field(min_length=1)
    current: Literal["AC", "DC"]
    max_power_kw: float = Field(gt=0)
    count: int = Field(gt=0)
    source: str = Field(min_length=1)


class StationProperties(DomainModel):
    station_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$",
    )
    provider_station_id: str | None = None
    name: str = Field(min_length=1)
    address: str = Field(min_length=1)
    operator: str | None = None
    zone_id: str | None = None
    total_ports: int = Field(gt=0)
    connectors: tuple[Connector, ...] = Field(min_length=1)
    amenities: tuple[str, ...] = ()
    opening_hours: str | dict[str, Any] | None = None
    access: Literal["public", "customers", "private", "unknown"]
    notes: tuple[str, ...]
    source_provider: str = Field(min_length=1)
    source_updated_at: datetime | None = None
    source_updated_at_basis: Literal[
        "source", "database_updated_at", "missing"
    ] = "missing"
    synthetic_fields: tuple[str, ...]

    @model_validator(mode="after")
    def validate_connector_count(self) -> StationProperties:
        if self.source_updated_at is not None and self.source_updated_at.tzinfo is None:
            raise ValueError("source_updated_at must include a timezone")
        connector_count = sum(connector.count for connector in self.connectors)
        if connector_count != self.total_ports:
            raise ValueError("connector counts must sum to total_ports")
        if self.source_updated_at is None:
            if self.source_updated_at_basis != "missing":
                raise ValueError("timestamp basis requires source_updated_at")
        elif self.source_updated_at_basis == "missing":
            # Static source catalogs predate the explicit basis field.
            object.__setattr__(self, "source_updated_at_basis", "source")
        return self


class PointGeometry(DomainModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]

    @model_validator(mode="after")
    def validate_coordinates(self) -> PointGeometry:
        longitude, latitude = self.coordinates
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("coordinates must be valid WGS84 longitude/latitude")
        return self


class Station(DomainModel):
    type: Literal["Feature"]
    geometry: PointGeometry
    properties: StationProperties

    @property
    def station_id(self) -> str:
        return self.properties.station_id


class StationCollection(DomainModel):
    type: Literal["FeatureCollection"]
    features: tuple[Station, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> StationCollection:
        station_ids = [station.station_id for station in self.features]
        if len(station_ids) != len(set(station_ids)):
            raise ValueError("station_id values must be unique")
        return self


class Vehicle(DomainModel):
    vehicle_id: str = Field(min_length=1)
    make: str = Field(min_length=1)
    model: str = Field(min_length=1)
    variant: str | None = None
    battery_capacity_kwh: float = Field(gt=0)
    usable_battery_kwh: float | None = Field(default=None, gt=0)
    max_ac_power_kw: float = Field(ge=0)
    max_dc_power_kw: float = Field(ge=0)
    ac_connectors: tuple[str, ...]
    dc_connectors: tuple[str, ...]
    consumption_wh_km: float = Field(gt=0)
    reserve_soc: float = Field(ge=0, le=1)
    default_target_soc: float = Field(ge=0, le=1)
    charging_efficiency: float = Field(gt=0, le=1)
    source: str = Field(min_length=1)
    is_synthetic: bool
    synthetic_fields: tuple[str, ...]

    @model_validator(mode="after")
    def validate_battery_capacities(self) -> Vehicle:
        if (
            self.usable_battery_kwh is not None
            and self.usable_battery_kwh > self.battery_capacity_kwh
        ):
            raise ValueError("usable battery capacity cannot exceed battery capacity")
        return self

    @property
    def is_release_eligible(self) -> bool:
        """Whether this profile can be exposed and used in release journeys."""
        return (
            not self.is_synthetic
            and not self.synthetic_fields
            and "synthetic" not in self.source.casefold()
        )

    @property
    def calculation_battery_kwh(self) -> float:
        return self.usable_battery_kwh or self.battery_capacity_kwh


class PortRuntimeStatus(DomainModel):
    connector_types: tuple[str, ...] = Field(min_length=1)
    state: Literal["available", "charging", "offline", "out_of_service", "unknown"]
    observed_at: datetime | None = None

    @model_validator(mode="after")
    def validate_observed_at(self) -> PortRuntimeStatus:
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("port observation timestamp must include a timezone")
        return self


class StationStatus(DomainModel):
    station_id: str = Field(min_length=1)
    timestamp: datetime
    total_ports: int = Field(gt=0)
    operational_ports: int = Field(ge=0)
    occupied_ports: int = Field(ge=0)
    available_ports: int = Field(ge=0)
    offline_ports: int = Field(ge=0)
    unknown_ports: int = Field(default=0, ge=0)
    occupancy_ratio: float | None = Field(default=None, ge=0, le=1)
    queue_length: int | None = Field(default=None, ge=0)
    avg_session_duration_min: float | None = Field(default=None, gt=0)
    data_source: str = Field(min_length=1)
    is_stale: bool = False
    # Internal detail retained from telemetry so journey waits can scope capacity
    # to the vehicle's compatible connectors without exposing provider port data.
    port_runtime_statuses: tuple[PortRuntimeStatus, ...] | None = Field(
        default=None, exclude=True
    )
    queue_connector_types: tuple[tuple[str, ...], ...] | None = Field(
        default=None, exclude=True
    )

    @model_validator(mode="after")
    def validate_capacity_invariants(self) -> StationStatus:
        if self.timestamp.tzinfo is None:
            raise ValueError("station status timestamp must include a timezone")
        if self.operational_ports + self.offline_ports + self.unknown_ports != self.total_ports:
            raise ValueError(
                "operational_ports + offline_ports + unknown_ports must equal total_ports"
            )
        if self.occupied_ports + self.available_ports != self.operational_ports:
            raise ValueError("occupied_ports + available_ports must equal operational_ports")
        expected_ratio = (
            self.occupied_ports / self.operational_ports if self.operational_ports else None
        )
        if expected_ratio is None and self.occupancy_ratio is not None:
            raise ValueError("occupancy_ratio must be null when operational_ports is zero")
        if expected_ratio is not None and (
            self.occupancy_ratio is None or abs(self.occupancy_ratio - expected_ratio) > 1e-9
        ):
            raise ValueError("occupancy_ratio does not match occupied/operational ports")
        return self


class CompatibilityResult(DomainModel):
    vehicle_id: str
    station_id: str
    compatible: bool
    matched_connectors: tuple[str, ...]
    vehicle_max_power_kw: float
    station_max_power_kw: float
    effective_power_kw: float
    reason_codes: tuple[str, ...]
    data_source: Literal["derived"] = "derived"


class ReachabilityResult(DomainModel):
    vehicle_id: str
    station_id: str
    route_id: str | None = None
    route_distance_m: float = Field(ge=0)
    route_duration_s: float | None = Field(default=None, ge=0)
    initial_soc: float = Field(ge=0, le=1)
    reserve_soc: float = Field(ge=0, le=1)
    trip_energy_kwh: float = Field(ge=0)
    estimated_arrival_soc: float
    reachable: bool
    data_source: Literal["derived"] = "derived"


class ChargingEstimateResult(DomainModel):
    vehicle_id: str
    station_id: str
    arrival_soc: float = Field(ge=0, le=1)
    target_soc: float = Field(ge=0, le=1)
    energy_to_add_kwh: float = Field(ge=0)
    effective_power_kw: float = Field(ge=0)
    charging_efficiency: float = Field(gt=0, le=1)
    estimated_charge_min: float = Field(ge=0)
    data_source: Literal["derived"] = "derived"


class PlannedArrival(DomainModel):
    arrival_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$",
    )
    journey_id: str | None = None
    station_id: str = Field(min_length=1)
    vehicle_id: str | None = None
    created_at: datetime
    eta_at: datetime
    eta_window_start: datetime
    eta_window_end: datetime
    expected_energy_kwh: float = Field(ge=0)
    expected_charge_duration_min: float = Field(gt=0)
    arrival_probability: float = Field(ge=0, le=1)
    expires_at: datetime
    route_id: str | None = None
    status: Literal["planned", "arrived", "cancelled", "expired"]
    data_source: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_timeline(self) -> PlannedArrival:
        timestamps = (
            self.created_at,
            self.eta_at,
            self.eta_window_start,
            self.eta_window_end,
            self.expires_at,
        )
        if any(timestamp.tzinfo is None for timestamp in timestamps):
            raise ValueError("planned arrival timestamps must include a timezone")
        if not self.eta_window_start <= self.eta_at <= self.eta_window_end:
            raise ValueError("eta_at must be inside its ETA window")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        if self.expires_at <= self.eta_window_end:
            raise ValueError("expires_at must be after eta_window_end")
        return self


class StationArrivalRate(DomainModel):
    station_id: str = Field(min_length=1)
    baseline_arrival_rate_per_hour: float = Field(ge=0)


class ScenarioArrivalRate(DomainModel):
    scenario_id: str = Field(min_length=1)
    station_id: str = Field(min_length=1)
    baseline_arrival_rate_per_hour: float = Field(ge=0)


class QueueAssumptions(DomainModel):
    planned_arrival_window_min: int = Field(gt=0)
    station_rates: tuple[StationArrivalRate, ...] = Field(min_length=1)
    scenario_overrides: tuple[ScenarioArrivalRate, ...]
    data_source: Literal["synthetic"]

    @model_validator(mode="after")
    def validate_unique_rates(self) -> QueueAssumptions:
        station_ids = [rate.station_id for rate in self.station_rates]
        if len(station_ids) != len(set(station_ids)):
            raise ValueError("queue station rates must have unique station_id")
        override_keys = [
            (override.scenario_id, override.station_id)
            for override in self.scenario_overrides
        ]
        if len(override_keys) != len(set(override_keys)):
            raise ValueError("queue scenario overrides must be unique per scenario/station")
        return self


class OccupancyForecastResult(DomainModel):
    station_id: str
    generated_at: datetime | None = None
    target_at: datetime | None = None
    requested_horizon_min: int = Field(gt=0)
    used_horizon_min: int = Field(gt=0)
    predicted_occupancy_ratio: float | None = Field(default=None, ge=0, le=1)
    predicted_occupied_ports: float = Field(ge=0)
    operational_ports: int = Field(ge=0)
    prediction_source: Literal["model", "persistence"]
    model_version: str | None = None
    flags: tuple[str, ...]
    data_source: Literal["derived"] = "derived"

    @model_validator(mode="after")
    def validate_predicted_capacity(self) -> OccupancyForecastResult:
        if any(
            timestamp is not None and timestamp.tzinfo is None
            for timestamp in (self.generated_at, self.target_at)
        ):
            raise ValueError("forecast timestamps must include a timezone")
        if self.predicted_occupied_ports > self.operational_ports:
            raise ValueError("predicted occupied ports cannot exceed operational ports")
        if self.operational_ports == 0 and self.predicted_occupancy_ratio is not None:
            raise ValueError("occupancy ratio must be null when no ports are operational")
        return self


class StationOccupancyForecast(OccupancyForecastResult):
    """Public station forecast contract with explicit calibration availability."""

    generated_at: datetime
    target_at: datetime
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_forecast_timeline(self) -> StationOccupancyForecast:
        if self.generated_at.tzinfo is None or self.target_at.tzinfo is None:
            raise ValueError("forecast timestamps must include a timezone")
        if self.target_at <= self.generated_at:
            raise ValueError("forecast target_at must be after generated_at")
        return self


class StationOccupancyObservation(DomainModel):
    station_id: str
    bucket_at: datetime
    total_ports: int = Field(gt=0)
    operational_ports: int = Field(ge=0)
    occupied_ports: int = Field(ge=0)
    occupancy_ratio: float | None = Field(default=None, ge=0, le=1)
    queue_length: int | None = Field(default=None, ge=0)
    data_source: Literal["observed"] = "observed"

    @model_validator(mode="after")
    def validate_observation(self) -> StationOccupancyObservation:
        if self.bucket_at.tzinfo is None:
            raise ValueError("occupancy bucket timestamp must include a timezone")
        if (
            self.operational_ports > self.total_ports
            or self.occupied_ports > self.operational_ports
        ):
            raise ValueError("occupancy counts exceed configured capacity")
        expected_ratio = (
            self.occupied_ports / self.operational_ports if self.operational_ports else None
        )
        if self.occupancy_ratio != expected_ratio:
            raise ValueError("occupancy ratio does not match observed counts")
        return self


class WaitEstimateResult(DomainModel):
    station_id: str
    evaluation_at: datetime
    operational_ports: int = Field(ge=0)
    predicted_occupied_ports: float = Field(ge=0)
    current_queue_length: int = Field(ge=0)
    avg_session_duration_min: float = Field(gt=0)
    baseline_arrival_rate_per_hour: float = Field(ge=0)
    planned_arrival_rate_per_hour: float = Field(ge=0)
    total_arrival_rate_per_hour: float = Field(ge=0)
    service_rate_per_server_per_hour: float = Field(gt=0)
    traffic_intensity: float | None = Field(default=None, ge=0)
    erlang_c_probability_wait: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Stationary M/M/c probability that an arrival waits; this is not "
            "conditioned on the current forecast snapshot."
        ),
    )
    erlang_expected_wait_min: float = Field(
        ge=0, description="Unconditional stationary M/M/c expected queue wait in minutes."
    )
    erlang_wait_p90_min: float | None = Field(
        default=None,
        ge=0,
        description="Approximate stationary M/M/c unconditional wait P90 in minutes.",
    )
    current_state_wait_min: float = Field(
        ge=0, description="Deterministic wait floor estimated from forecast occupancy and queue."
    )
    estimated_wait_min: float = Field(
        ge=0,
        description=(
            "Serving wait estimate combining the current-state floor with Erlang C; "
            "zero when a projected compatible port is free and the observed queue is empty."
        ),
    )
    estimated_wait_p90_min: float = Field(
        ge=0,
        description=(
            "Approximate Erlang C wait P90 with the current-state floor and configured cap; "
            "not calibrated on operational telemetry."
        ),
    )
    method: Literal["erlang_c", "scoring_cap"]
    scoring_wait_cap_min: float = Field(gt=0)
    flags: tuple[str, ...]
    data_source: Literal["derived"] = "derived"

    @model_validator(mode="after")
    def validate_evaluation_timestamp(self) -> WaitEstimateResult:
        if self.evaluation_at.tzinfo is None:
            raise ValueError("evaluation_at must include a timezone")
        return self
