"""Versioned public API models and boundary-unit adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )


class ApiPoint(ApiModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class ConfigResponse(ApiModel):
    reroute_deviation_m: int
    reroute_eta_delta_min: int
    near_station_radius_m: int
    arrival_radius_m: int
    position_interval_sec: int
    reroute_cooldown_sec: int
    low_battery_pct: int
    stations_version: str
    vehicles_version: str
    station_status_stale_after_sec: int
    updated_at: datetime


class PortStatusUpdate(ApiModel):
    port_id: str = Field(min_length=1)
    status: Literal["available", "charging", "out_of_service", "unknown"]
    reported_at: datetime
    session_started_at: datetime | None = None
    estimated_finish_at: datetime | None = None

    @field_validator("reported_at", "session_started_at", "estimated_finish_at")
    @classmethod
    def timestamps_require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps require timezone")
        return value


class PortStatusBatchRequest(ApiModel):
    updates: tuple[PortStatusUpdate, ...] = Field(min_length=1, max_length=1000)


class PortStatusBatchResponse(ApiModel):
    updated: int = Field(ge=0)
    ignored: int = Field(ge=0)
    updated_at: datetime


class StationSummary(ApiModel):
    id: str
    name: str
    address: str
    location: ApiPoint
    color: Literal["green", "yellow", "red", "grey"]
    available_ports: int = Field(ge=0)
    total_ports: int = Field(ge=0)
    connectors: tuple[str, ...]
    updated_at: datetime


class ConnectorNow(ApiModel):
    color: Literal["green", "yellow", "red", "grey"]
    available: int = Field(ge=0)
    charging: int = Field(ge=0)
    out_of_service: int = Field(ge=0)
    unknown: int = Field(ge=0)
    total: int = Field(ge=0)


class ConnectorDetail(ApiModel):
    code: str
    max_power_kw: float = Field(gt=0)
    now: ConnectorNow


class StationDetail(StationSummary):
    opening_hours: str | dict | None
    by_connector: tuple[ConnectorDetail, ...]


class StationAvailability(ApiModel):
    station_id: str
    color: Literal["green", "yellow", "red", "grey"]
    available_ports: int = Field(ge=0)
    total_ports: int = Field(ge=0)
    prediction_source: str
    updated_at: datetime


class AvailabilityResponse(ApiModel):
    offset: Literal[0, 5, 10, 15, 20, 25, 30]
    is_prediction: bool
    items: tuple[StationAvailability, ...]
    updated_at: datetime


class PortResponse(ApiModel):
    id: str
    label: str
    connector: str
    status: Literal["available", "charging", "out_of_service", "unknown"]
    minutes_to_finish: int | None = Field(default=None, ge=0)
    updated_at: datetime


class SearchStationsRequest(ApiModel):
    origin: ApiPoint
    vehicle_id: str = Field(min_length=1)
    battery_pct: float = Field(ge=0, le=100)
    limit: int = Field(default=10, ge=1, le=25)


class SearchRouteRequest(ApiModel):
    origin: ApiPoint
    destination: ApiPoint
    vehicle_id: str = Field(min_length=1)
    battery_pct: float = Field(ge=0, le=100)
    limit: int = Field(default=10, ge=1, le=25)


class SearchRouteSummary(ApiModel):
    route_id: str
    provider: str
    distance_km: float = Field(ge=0)
    travel_min: float = Field(ge=0)
    geometry: tuple[tuple[float, float], ...]


class SearchStationOption(ApiModel):
    rank: int = Field(gt=0)
    station: StationSummary
    route: SearchRouteSummary
    distance_km: float = Field(ge=0)
    travel_min: float = Field(ge=0)
    wait_min: float = Field(ge=0)
    charge_min: float = Field(ge=0)
    to_dest_min: float | None = Field(default=None, ge=0)
    total_min: float = Field(ge=0)
    arrive_battery_pct: float
    prediction_source: str
    flags: tuple[str, ...]


class SearchExclusion(ApiModel):
    station_id: str
    reason_codes: tuple[str, ...] = Field(min_length=1)


class SearchStationsResponse(ApiModel):
    search_id: str
    reachable_km: float = Field(ge=0)
    stations: tuple[SearchStationOption, ...]
    excluded_candidates: tuple[SearchExclusion, ...] = ()
    nearest_station: StationSummary | None = None
    missing_km: float | None = Field(default=None, ge=0)
    updated_at: datetime


class SearchRouteResponse(ApiModel):
    search_id: str
    case: Literal["enough", "needCharge", "fallback"]
    direct_route: SearchRouteSummary
    direct_min: float = Field(ge=0)
    stations: tuple[SearchStationOption, ...]
    excluded_candidates: tuple[SearchExclusion, ...] = ()
    missing_km: float | None = Field(default=None, ge=0)
    nearest_station: StationSummary | None = None
    updated_at: datetime
