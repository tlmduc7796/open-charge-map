"""Validated routing, journey-query and recommendation models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.app.domain.models import DomainModel, WaitDistribution


class GeoPoint(DomainModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = None


class RouteWaypoint(GeoPoint):
    station_id: str | None = None


class LineStringGeometry(DomainModel):
    type: Literal["LineString"]
    coordinates: tuple[tuple[float, float], ...] = Field(min_length=2)


class RouteResult(DomainModel):
    route_id: str
    provider: Literal["goong", "osrm"]
    origin: GeoPoint
    destination: GeoPoint
    waypoints: tuple[RouteWaypoint, ...]
    geometry: LineStringGeometry
    distance_m: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    flags: tuple[str, ...] = ()


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


class JourneyQuery(DomainModel):
    """One journey the recommendation engine evaluates."""

    vehicle_id: str = Field(min_length=1)
    initial_soc: float = Field(ge=0, le=1)
    target_soc: float = Field(ge=0, le=1)
    origin: GeoPoint
    destination: GeoPoint
    departure_at: datetime
    preference: RecommendationPreference

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
    wait_distribution: WaitDistribution | None = None
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
    generated_at: datetime
    vehicle_id: str
    direct_route: RouteResult
    recommendations: tuple[RecommendationItem, ...]
    excluded_candidates: tuple[CandidateExclusion, ...]
    scoring_method: Literal["fixed_threshold_weighted_sum"] = (
        "fixed_threshold_weighted_sum"
    )


class RouteRequest(DomainModel):
    origin: GeoPoint
    destination: GeoPoint
    waypoints: tuple[RouteWaypoint, ...] = ()


class PlaceSuggestion(DomainModel):
    place_id: str
    description: str
    main_text: str
    secondary_text: str = ""
    provider: Literal["goong"]


class GeocodedPlace(DomainModel):
    place_id: str
    label: str
    location: GeoPoint
    provider: Literal["goong"]


class ModelStatus(DomainModel):
    prediction_source: Literal["persistence", "model", "default"]
    model_artifact_available: bool
    preprocessor_artifact_available: bool
    metadata_available: bool
    model_adapter_loaded: bool
    release_ready: bool
    flags: tuple[str, ...]
