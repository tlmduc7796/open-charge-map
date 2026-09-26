"""Validated routing, demo-event, recommendation, and Phase 07 API models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.app.domain.models import DomainModel


class GeoPoint(DomainModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = None


class RouteWaypoint(GeoPoint):
    station_id: str | None = None


class LineStringGeometry(DomainModel):
    type: Literal["LineString"]
    coordinates: tuple[tuple[float, float], ...] = Field(min_length=2)


class RouteRecord(DomainModel):
    route_id: str = Field(min_length=1)
    provider: Literal["goong", "osrm"]
    origin: GeoPoint
    destination: GeoPoint
    waypoints: tuple[RouteWaypoint, ...]
    geometry: LineStringGeometry
    distance_m: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    retrieved_at: datetime
    request_hash: str = Field(min_length=64, max_length=64)
    data_source: Literal["routing_api"]


class RouteResult(DomainModel):
    route_id: str
    provider: Literal["goong", "osrm"]
    resolution_source: Literal["cache", "live"]
    origin: GeoPoint
    destination: GeoPoint
    waypoints: tuple[RouteWaypoint, ...]
    geometry: LineStringGeometry
    distance_m: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    flags: tuple[str, ...] = ()


class DemoEventEffects(DomainModel):
    offline_ports_delta: int = 0
    queue_length_delta: int = 0
    occupied_ports_delta: int = 0


class DemoEvent(DomainModel):
    event_id: str = Field(min_length=1)
    event_type: Literal["congestion", "port_outage", "queue_spike", "station_recovery"]
    station_id: str = Field(min_length=1)
    start_at: datetime
    end_at: datetime | None = None
    severity: Literal["low", "medium", "high"]
    effects: DemoEventEffects
    description: str = ""
    is_synthetic: Literal[True]


class RecommendationPreference(DomainModel):
    wait_weight: float = Field(ge=0, le=1)
    detour_weight: float = Field(ge=0, le=1)
    charging_time_weight: float = Field(ge=0, le=1)
    soc_risk_weight: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_weight_sum(self) -> RecommendationPreference:
        total = (
            self.wait_weight
            + self.detour_weight
            + self.charging_time_weight
            + self.soc_risk_weight
        )
        if abs(total - 1) > 1e-9:
            raise ValueError("recommendation weights must sum to 1")
        return self


class DemoScenario(DomainModel):
    scenario_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    vehicle_id: str = Field(min_length=1)
    initial_soc: float = Field(ge=0, le=1)
    target_soc: float = Field(ge=0, le=1)
    origin: GeoPoint
    destination: GeoPoint
    departure_at: datetime
    preference: RecommendationPreference
    event_ids: tuple[str, ...]
    route_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("departure_at")
    @classmethod
    def departure_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("departure_at requires timezone")
        return value


class CandidateExclusion(DomainModel):
    station_id: str
    reason_codes: tuple[str, ...] = Field(min_length=1)


class RecommendationItem(DomainModel):
    station_id: str
    station_name: str
    route_id: str
    route_provider: str
    route: RouteResult
    matched_connectors: tuple[str, ...]
    effective_power_kw: float = Field(gt=0)
    route_distance_to_station_m: float = Field(ge=0)
    route_duration_to_station_s: float = Field(ge=0)
    detour_min: float = Field(ge=0)
    arrival_soc: float = Field(ge=0, le=1)
    predicted_occupied_ports: float = Field(ge=0)
    predicted_occupancy_ratio: float | None = Field(default=None, ge=0, le=1)
    prediction_source: str
    estimated_wait_min: float = Field(ge=0)
    estimated_charge_min: float = Field(ge=0)
    energy_to_add_kwh: float = Field(ge=0)
    wait_score: float = Field(ge=0, le=1)
    detour_score: float = Field(ge=0, le=1)
    charging_time_score: float = Field(ge=0, le=1)
    soc_risk_score: float = Field(ge=0, le=1)
    final_score: float = Field(ge=0, le=1)
    rank: int = Field(gt=0)
    flags: tuple[str, ...]


class JourneyRecommendationResult(DomainModel):
    scenario_id: str
    generated_at: datetime
    vehicle_id: str
    direct_route: RouteResult
    recommendations: tuple[RecommendationItem, ...]
    excluded_candidates: tuple[CandidateExclusion, ...]
    active_event_ids: tuple[str, ...]
    scoring_method: Literal["fixed_threshold_weighted_sum"] = (
        "fixed_threshold_weighted_sum"
    )


class JourneyRecommendationRequest(DomainModel):
    scenario_id: str
    apply_scenario_events: bool = False
    vehicle_id: str | None = None
    initial_soc: float | None = Field(default=None, ge=0, le=1)
    target_soc: float | None = Field(default=None, ge=0, le=1)
    origin: GeoPoint | None = None
    destination: GeoPoint | None = None
    departure_at: datetime | None = None

    @field_validator("departure_at")
    @classmethod
    def departure_requires_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("departure_at requires timezone")
        return value


class RouteRequest(DomainModel):
    origin: GeoPoint
    destination: GeoPoint
    waypoints: tuple[RouteWaypoint, ...] = ()
    preferred_route_id: str | None = None


class PlannedArrivalCreateRequest(DomainModel):
    arrival_id: str | None = None
    station_id: str
    vehicle_id: str | None = None
    eta_at: datetime
    eta_window_start: datetime
    eta_window_end: datetime
    expected_energy_kwh: float = Field(ge=0)
    expected_charge_duration_min: float = Field(gt=0)
    arrival_probability: float = Field(ge=0, le=1)
    expires_at: datetime
    route_id: str | None = None


class PlannedArrivalCommitRequest(DomainModel):
    station_id: str
    vehicle_id: str
    departure_at: datetime
    route_id: str
    route_duration_to_station_s: float = Field(ge=0)
    expected_energy_kwh: float = Field(ge=0)
    expected_charge_duration_min: float = Field(gt=0)

    @field_validator("departure_at")
    @classmethod
    def departure_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("departure_at requires timezone")
        return value


class PlaceSuggestion(DomainModel):
    place_id: str
    description: str
    main_text: str
    secondary_text: str = ""
    provider: Literal["goong", "demo"]


class GeocodedPlace(DomainModel):
    place_id: str
    label: str
    location: GeoPoint
    provider: Literal["goong", "demo"]


class ModelStatus(DomainModel):
    prediction_source: Literal["persistence", "model"]
    model_artifact_available: bool
    preprocessor_artifact_available: bool
    metadata_available: bool
    model_adapter_loaded: bool
    release_ready: bool
    flags: tuple[str, ...]
