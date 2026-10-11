"""Validated models for the Phase 05 static, runtime, and derived data."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Connector(DomainModel):
    type: str = Field(min_length=1)
    current: Literal["AC", "DC"]
    max_power_kw: float = Field(gt=0)
    count: int = Field(gt=0)
    source: str = Field(min_length=1)


class StationProperties(DomainModel):
    station_id: str = Field(min_length=1)
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
    synthetic_fields: tuple[str, ...]

    @model_validator(mode="after")
    def validate_connector_count(self) -> StationProperties:
        connector_count = sum(connector.count for connector in self.connectors)
        if connector_count != self.total_ports:
            raise ValueError("connector counts must sum to total_ports")
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

    @property
    def calculation_battery_kwh(self) -> float:
        return self.usable_battery_kwh or self.battery_capacity_kwh


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
    synthetic_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_capacity_invariants(self) -> StationStatus:
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


class StationArrivalRate(DomainModel):
    station_id: str = Field(min_length=1)
    baseline_arrival_rate_per_hour: float = Field(ge=0)


class QueueAssumptions(DomainModel):
    station_rates: tuple[StationArrivalRate, ...] = Field(min_length=1)
    data_source: Literal["synthetic"]

    @model_validator(mode="after")
    def validate_unique_rates(self) -> QueueAssumptions:
        station_ids = [rate.station_id for rate in self.station_rates]
        if len(station_ids) != len(set(station_ids)):
            raise ValueError("queue station rates must have unique station_id")
        return self


class OccupancyWindow(DomainModel):
    """The 12 most recent contiguous 5-minute occupancy ratios of one station.

    `lags[0]` is the newest bucket (`lag_1` in `ml/features.py`), `lags[11]` the oldest.
    `t_last` is the bucket start of `lags[0]`.
    """

    station_id: str = Field(min_length=1)
    lags: tuple[float, ...] = Field(min_length=12, max_length=12)
    t_last: datetime
    total_ports: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_window(self) -> OccupancyWindow:
        if self.t_last.tzinfo is None:
            raise ValueError("t_last must include a timezone")
        if any(not 0 <= value <= 1 for value in self.lags):
            raise ValueError("occupancy ratios must be between 0 and 1")
        return self


class OccupancyForecastResult(DomainModel):
    station_id: str
    requested_horizon_min: int = Field(ge=0)
    # 0 is the newest observation itself (no prediction).
    used_horizon_min: int = Field(ge=0)
    predicted_occupancy_ratio: float | None = Field(default=None, ge=0, le=1)
    predicted_occupied_ports: float = Field(ge=0)
    operational_ports: int = Field(ge=0)
    prediction_source: Literal["model", "model_profile", "persistence", "default"]
    model_version: str | None = None
    flags: tuple[str, ...]
    data_source: Literal["derived"] = "derived"

    @model_validator(mode="after")
    def validate_predicted_capacity(self) -> OccupancyForecastResult:
        if self.predicted_occupied_ports > self.operational_ports:
            raise ValueError("predicted occupied ports cannot exceed operational ports")
        if self.operational_ports == 0 and self.predicted_occupancy_ratio is not None:
            raise ValueError("occupancy ratio must be null when no ports are operational")
        return self


class ArrivalForecast(DomainModel):
    """Forecasts at the five-minute milestones around and after the arrival at a station.

    All times are minutes after the newest observation (`t_last`). `milestones_min` starts at
    the milestone at or before the arrival (`arrival_lead_min`), so `forecasts[0]` is the
    milestone just before it (the same one when the arrival falls exactly on a milestone) and
    `forecasts[1]` the first milestone after it.
    """

    arrival_lead_min: float = Field(ge=0)
    milestones_min: tuple[int, ...] = Field(min_length=2)
    forecasts: tuple[OccupancyForecastResult, ...]

    @model_validator(mode="after")
    def validate_milestones(self) -> ArrivalForecast:
        if len(self.milestones_min) != len(self.forecasts):
            raise ValueError("every milestone needs one forecast")
        first = self.milestones_min[0]
        if not first <= self.arrival_lead_min < first + 5:
            raise ValueError("first milestone must be the one at or before the arrival")
        if any(
            later - earlier != 5
            for earlier, later in zip(self.milestones_min, self.milestones_min[1:], strict=False)
        ):
            raise ValueError("milestones must be five minutes apart")
        return self

    @property
    def at_arrival(self) -> OccupancyForecastResult:
        """The forecast of the first milestone at or after the arrival."""
        return self.forecasts[0 if self.arrival_lead_min == self.milestones_min[0] else 1]


class WaitDistribution(DomainModel):
    """Wait-time summary returned by the ML boundary: P(W>0), E[W] and W90."""

    p_wait: float = Field(ge=0, le=1)
    expected_wait_min: float = Field(ge=0)
    p90_wait_min: float = Field(ge=0)
    source: Literal["model", "default"]


class WaitEstimateResult(DomainModel):
    """Wait derived from forecast free ports at the milestones following the arrival."""

    station_id: str
    evaluation_at: datetime
    operational_ports: int = Field(ge=0)
    predicted_occupied_ports: float = Field(ge=0)
    required_free_ports: int = Field(ge=0)
    # Free ports at the arrival (the worse of the two surrounding milestones); None = offline.
    free_ports_at_arrival: int | None = Field(default=None, ge=0)
    # Minutes after arrival at which the rule is met; None when it never is (wait is capped).
    satisfied_at_min: float | None = Field(default=None, ge=0)
    estimated_wait_min: float = Field(ge=0)
    scoring_wait_cap_min: float = Field(gt=0)
    wait_distribution: WaitDistribution | None = None
    flags: tuple[str, ...]
    data_source: Literal["derived"] = "derived"
