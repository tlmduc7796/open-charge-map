"""Validated routing, demo-event, recommendation, and Phase 07 API models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

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


class RouteLeg(DomainModel):
    origin: GeoPoint
    destination: GeoPoint
    distance_m: float = Field(ge=0)
    duration_s: float = Field(ge=0)
    geometry: LineStringGeometry | None = None
    provider: Literal["goong", "osrm"]
    retrieved_at: datetime
    flags: tuple[str, ...] = ()

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_at_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retrieved_at requires timezone")
        return value


class RouteRecord(DomainModel):
    route_id: str = Field(min_length=1)
    provider: Literal["goong", "osrm"]
    origin: GeoPoint
    destination: GeoPoint
    waypoints: tuple[RouteWaypoint, ...]
    geometry: LineStringGeometry
    distance_m: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    legs: tuple[RouteLeg, ...] = ()
    retrieved_at: datetime
    request_hash: str = Field(min_length=64, max_length=64)
    data_source: Literal["routing_api"]

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_at_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retrieved_at requires timezone")
        return value


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
    legs: tuple[RouteLeg, ...] = ()
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

    @model_validator(mode="after")
    def validate_event_timeline(self) -> DemoEvent:
        if self.start_at.tzinfo is None or (
            self.end_at is not None and self.end_at.tzinfo is None
        ):
            raise ValueError("demo event timestamps must include a timezone")
        if self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


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
    route_ids: tuple[str, ...] = ()

    @field_validator("departure_at")
    @classmethod
    def departure_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("departure_at requires timezone")
        return value


class CandidateExclusion(DomainModel):
    station_id: str
    reason_codes: tuple[str, ...] = Field(min_length=1)


class UnreachableStationFallback(DomainModel):
    station_id: str
    station_name: str
    straight_line_distance_m: float = Field(ge=0)
    is_reachable: Literal[False] = False
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
    drive_to_station_min: float = Field(ge=0)
    drive_station_to_destination_min: float = Field(ge=0)
    detour_min: float = Field(ge=0)
    arrival_soc: float = Field(ge=0, le=1)
    destination_soc: float = Field(ge=0, le=1)
    minimum_soc: float = Field(ge=0, le=1)
    predicted_occupied_ports: float = Field(ge=0)
    predicted_occupancy_ratio: float | None = Field(default=None, ge=0, le=1)
    # Canonical release fields; defaults keep older persisted recommendation snapshots readable.
    predicted_free_ports: float | None = Field(default=None, ge=0)
    prediction_source: str
    model_version: str | None = None
    estimated_wait_min: float = Field(ge=0)
    wait_expected_min: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Wait estimate adjusted by forecast occupancy and known queue at station ETA; "
            "may be zero with a projected free compatible port and an empty observed queue."
        ),
    )
    wait_probability: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Stationary Erlang C probability of waiting under station-wide arrival/service "
            "rates; not conditional on the forecast snapshot."
        ),
    )
    wait_p90_min: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Approximate stationary Erlang C wait P90 with a current-state floor; "
            "not calibrated using operational telemetry."
        ),
    )
    wait_method: Literal["erlang_c", "scoring_cap"]
    wait_data_source: Literal["derived"] = "derived"
    estimated_charge_min: float = Field(ge=0)
    charge_min: float | None = Field(default=None, ge=0)
    soc_after_charge: float | None = Field(default=None, ge=0, le=1)
    total_time_min: float = Field(ge=0)
    energy_to_add_kwh: float = Field(ge=0)
    wait_score: float = Field(
        ge=0, le=1, description="Diagnostic component score; does not determine rank."
    )
    detour_score: float = Field(
        ge=0, le=1, description="Diagnostic component score; does not determine rank."
    )
    charging_time_score: float = Field(
        ge=0, le=1, description="Diagnostic component score; does not determine rank."
    )
    soc_risk_score: float = Field(
        ge=0, le=1, description="Diagnostic component score; does not determine rank."
    )
    final_score: float = Field(
        ge=0,
        le=1,
        description=(
            "Legacy weighted diagnostic score; rank is determined by the versioned "
            "total-time policy, not this score."
        ),
    )
    rank: int = Field(gt=0)
    flags: tuple[str, ...]

    @model_validator(mode="after")
    def validate_total_time(self) -> RecommendationItem:
        expected_total = (
            self.drive_to_station_min
            + (
                self.wait_expected_min
                if self.wait_expected_min is not None
                else self.estimated_wait_min
            )
            + (
                self.charge_min
                if self.charge_min is not None
                else self.estimated_charge_min
            )
            + self.drive_station_to_destination_min
        )
        if abs(self.total_time_min - expected_total) > 0.01:
            raise ValueError(
                "total_time_min must equal drive, wait, charge, and onward-drive time"
            )
        return self


class JourneyRecommendationResult(DomainModel):
    scenario_id: str | None
    journey_id: str | None = None
    generated_at: datetime
    vehicle_id: str
    direct_route: RouteResult
    outcome: Literal["direct_no_charge", "charging_stops", "no_reachable_station"]
    recommendations: tuple[RecommendationItem, ...]
    excluded_candidates: tuple[CandidateExclusion, ...]
    fallback_candidate: UnreachableStationFallback | None = None
    active_event_ids: tuple[str, ...]
    flags: tuple[str, ...] = ()
    candidate_limit: int | None = None
    ranking_policy_version: str = "total_expected_time_v1"
    scoring_method: Literal["fixed_threshold_weighted_sum"] = Field(
        default="fixed_threshold_weighted_sum",
        description=(
            "Method used for legacy diagnostic scores; ranking follows "
            "ranking_policy_version."
        ),
    )

    @field_validator("generated_at")
    @classmethod
    def generated_at_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at requires timezone")
        return value


class JourneyRecommendationRequest(DomainModel):
    scenario_id: str | None = None
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

    @model_validator(mode="after")
    def dynamic_journey_requires_inputs(self) -> JourneyRecommendationRequest:
        if self.scenario_id is None and any(
            value is None
            for value in (
                self.vehicle_id,
                self.initial_soc,
                self.origin,
                self.destination,
            )
        ):
            raise ValueError(
                "vehicle_id, initial_soc, origin and destination are required "
                "when scenario_id is omitted"
            )
        return self


class TripPositionRequest(DomainModel):
    recorded_at: datetime
    location: GeoPoint
    speed_kmh: float | None = Field(default=None, ge=0)
    heading: float | None = Field(default=None, ge=0, lt=360)
    battery_pct: float | None = Field(default=None, ge=0, le=100)
    distance_km: float | None = Field(default=None, ge=0)

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("recorded_at requires timezone")
        return value


class StationIncidentReportRequest(DomainModel):
    journey_id: UUID
    idempotency_key: str = Field(min_length=16, max_length=100)
    incident_type: Literal[
        "port_unavailable",
        "queue_inaccurate",
        "access_problem",
        "safety_concern",
        "other",
    ]
    description: str = Field(min_length=3, max_length=500)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("description must contain at least 3 non-space characters")
        return normalized


class StationIncidentReport(DomainModel):
    incident_id: str
    journey_id: str
    station_id: str
    incident_type: Literal[
        "port_unavailable",
        "queue_inaccurate",
        "access_problem",
        "safety_concern",
        "other",
    ]
    description: str
    status: Literal["open", "triaged", "resolved", "rejected"]
    created_at: datetime
    data_source: Literal["user_report"] = "user_report"

    @field_validator("created_at")
    @classmethod
    def created_at_requires_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at requires timezone")
        return value


class StationIncidentReviewRequest(DomainModel):
    status: Literal["triaged", "resolved", "rejected"]
    review_note: str | None = Field(default=None, max_length=500)

    @field_validator("review_note")
    @classmethod
    def normalize_review_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized) < 3:
            raise ValueError("review_note must contain at least 3 non-space characters")
        return normalized

    @model_validator(mode="after")
    def finalized_status_requires_note(self) -> StationIncidentReviewRequest:
        if self.status in {"resolved", "rejected"} and self.review_note is None:
            raise ValueError("resolved and rejected incidents require a review note")
        return self


class StationIncidentAdminRecord(StationIncidentReport):
    updated_at: datetime
    reviewed_at: datetime | None = None
    review_note: str | None = None

    @field_validator("updated_at", "reviewed_at")
    @classmethod
    def admin_timestamps_require_timezone(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("incident admin timestamps require timezone")
        return value


class RouteRequest(DomainModel):
    origin: GeoPoint
    destination: GeoPoint
    waypoints: tuple[RouteWaypoint, ...] = ()
    preferred_route_id: str | None = None


class PlannedArrivalCreateRequest(DomainModel):
    arrival_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$",
    )
    journey_id: UUID | None = None
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

    @model_validator(mode="after")
    def validate_arrival_timeline(self) -> PlannedArrivalCreateRequest:
        timestamps = (
            self.eta_at,
            self.eta_window_start,
            self.eta_window_end,
            self.expires_at,
        )
        if any(timestamp.tzinfo is None for timestamp in timestamps):
            raise ValueError("planned arrival timestamps must include a timezone")
        if not self.eta_window_start <= self.eta_at <= self.eta_window_end:
            raise ValueError("eta_at must be inside its ETA window")
        if self.expires_at <= self.eta_window_end:
            raise ValueError("expires_at must be after eta_window_end")
        return self


class PlannedArrivalCommitRequest(DomainModel):
    arrival_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$",
    )
    journey_id: UUID | None = None
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
    model_version: str | None = None
    model_profile: str | None = None
    serving_reason: str | None = None
