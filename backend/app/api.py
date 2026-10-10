"""HTTP endpoints for the Phase 07 backend demo flow."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import secrets
from collections import Counter
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from hmac import new as hmac_new
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from redis import RedisError

from backend.app.domain.models import (
    PlannedArrival,
    StationOccupancyForecast,
    StationOccupancyObservation,
    StationStatus,
)
from backend.app.domain.phase7_models import (
    DemoScenario,
    JourneyRecommendationRequest,
    JourneyRecommendationResult,
    ModelStatus,
    PlannedArrivalCommitRequest,
    PlannedArrivalCreateRequest,
    RecommendationPreference,
    RouteRequest,
    RouteResult,
    StationIncidentAdminRecord,
    StationIncidentReport,
    StationIncidentReportRequest,
    StationIncidentReviewRequest,
    TripPositionRequest,
)
from backend.app.domain.queue_lab import (
    QueueLabSimulationRequest,
    QueueLabSimulationResult,
)
from backend.app.domain.queue_lab import (
    demo_request as queue_lab_demo_request,
)
from backend.app.domain.queue_lab import (
    simulate_queue_lab as run_queue_lab,
)
from backend.app.domain.realtime import (
    DESWaitRequest,
    DESWaitResult,
    StationTelemetrySnapshot,
    validate_observation_timestamp,
)
from backend.app.identity import require_authenticated_user
from backend.app.journey_repository import IdempotencyConflict

router = APIRouter()
logger = logging.getLogger(__name__)
STATION_STATUS_CHANNEL = "smart-ev:station-status-updated"
IDEMPOTENCY_KEY_PATTERN = re.compile(r"[A-Za-z0-9._:-]{16,200}")


def _require_demo_mode(request: Request) -> None:
    if not request.app.state.settings.demo_mode:
        raise HTTPException(status_code=403, detail="demo mode is disabled")


def _scope_journey_idempotency_key(
    idempotency_key: str, identity: dict, settings
) -> str:
    """Bind release idempotency and capability tokens to one OIDC principal."""
    signing_key = settings.journey_token_signing_key
    subject = identity.get("sub")
    issuer = identity.get("iss") or settings.oidc_issuer
    if signing_key is None:
        raise HTTPException(
            status_code=503,
            detail="journey capability signing is not configured",
        )
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status_code=401, detail="access token has no user subject")
    if not isinstance(issuer, str) or not issuer.strip():
        raise HTTPException(status_code=503, detail="identity issuer is not configured")
    material = f"journey-idempotency-v1\0{issuer}\0{subject}\0{idempotency_key}"
    return hmac_new(signing_key.encode("utf-8"), material.encode("utf-8"), "sha256").hexdigest()


def _journey_capability_token(idempotency_key: str, signing_key: str) -> str:
    material = f"journey-capability-v1\0{idempotency_key}"
    return hmac_new(signing_key.encode("utf-8"), material.encode("utf-8"), "sha256").hexdigest()


def _require_telemetry_key(request: Request, supplied_key: str | None) -> None:
    expected_key = request.app.state.settings.telemetry_ingest_api_key
    if expected_key is None:
        if request.app.state.settings.demo_mode:
            return
        raise HTTPException(status_code=503, detail="telemetry ingestion is not configured")
    if supplied_key is None or not compare_digest(
        supplied_key.encode("utf-8"), expected_key.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="invalid telemetry API key")


def _require_planned_arrival_admin_key(
    request: Request, supplied_key: str | None
) -> None:
    if request.app.state.settings.demo_mode:
        return
    expected_key = request.app.state.settings.planned_arrival_admin_api_key
    if expected_key is None:
        raise HTTPException(status_code=503, detail="planned-arrival operations are not configured")
    if supplied_key is None or not compare_digest(
        supplied_key.encode("utf-8"), expected_key.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="invalid planned-arrival admin key")


def _require_incident_review_key(request: Request, supplied_key: str | None) -> None:
    expected_key = request.app.state.settings.incident_review_api_key
    if expected_key is None:
        raise HTTPException(status_code=503, detail="incident review is not configured")
    if supplied_key is None or not compare_digest(
        supplied_key.encode("utf-8"), expected_key.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="invalid incident review API key")


def _authorize_planned_arrival_owner(
    request: Request,
    arrival,
    journey_id: UUID | None,
    authorization: str | None,
) -> None:
    if request.app.state.settings.demo_mode:
        return
    if journey_id is None or arrival.journey_id != str(journey_id):
        raise HTTPException(status_code=404, detail="planned arrival not found")
    repository = request.app.state.journey_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="journey persistence is disabled")
    try:
        repository.get(journey_id, access_token=_extract_bearer_token(authorization))
    except (KeyError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail="planned arrival not found") from exc


def _station_has_synthetic_data(station) -> bool:
    source_provider = getattr(station.properties, "source_provider", "")
    return (
        bool(station.properties.synthetic_fields)
        or "synthetic" in source_provider.casefold()
        or any(
            "synthetic" in connector.source.casefold()
            for connector in station.properties.connectors
        )
    )


def _release_safe_status(request: Request, status: StationStatus) -> StationStatus:
    if not request.app.state.settings.demo_mode and status.data_source in {
        "synthetic",
        "simulated",
        "unknown",
        "runtime",
    }:
        return status.model_copy(update={"is_stale": True})
    return status


def _current_station_status(request: Request, station_id: str) -> StationStatus:
    runtime = request.app.state.runtime_state
    if request.app.state.settings.demo_mode:
        runtime.refresh()
        return runtime.get(station_id)
    statuses = runtime.get_many((station_id,))
    if not statuses:
        raise KeyError(station_id)
    return statuses[0]


def _extract_bearer_token(authorization: str | None) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=404, detail="journey not found")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=404, detail="journey not found")
    return token


def _scenario_from_payload(payload: JourneyRecommendationRequest, request: Request):
    if payload.scenario_id is None:
        vehicle_id = payload.vehicle_id
        assert vehicle_id is not None
        vehicle = request.app.state.vehicle_repository.get(vehicle_id)
        assert payload.initial_soc is not None
        assert payload.origin is not None
        assert payload.destination is not None
        scenario = DemoScenario(
            scenario_id="LIVE",
            name="Live journey request",
            vehicle_id=vehicle_id,
            initial_soc=payload.initial_soc,
            target_soc=(
                payload.target_soc
                if payload.target_soc is not None
                else vehicle.default_target_soc
            ),
            origin=payload.origin,
            destination=payload.destination,
            departure_at=payload.departure_at or datetime.now(UTC),
            preference=RecommendationPreference(
                wait_weight=0.40,
                detour_weight=0.25,
                charging_time_weight=0.25,
                soc_risk_weight=0.10,
            ),
            event_ids=(),
            route_ids=(),
        )
        return scenario

    _require_demo_mode(request)
    scenario = request.app.state.domain_data.demo_scenarios.get(payload.scenario_id)
    overrides = {
        key: value
        for key, value in {
            "vehicle_id": payload.vehicle_id,
            "initial_soc": payload.initial_soc,
            "target_soc": payload.target_soc,
            "origin": payload.origin,
            "destination": payload.destination,
            "departure_at": payload.departure_at,
        }.items()
        if value is not None
    }
    return scenario.model_copy(update=overrides) if overrides else scenario


@router.get("/stations", tags=["stations"])
def list_stations(
    request: Request,
    limit: int = Query(default=100, ge=1, le=200),
    after_station_id: str | None = None,
):
    """Return a stable, keyset-paginated page of at most 200 catalog records."""
    return request.app.state.station_repository.page(
        limit=limit,
        after_station_id=after_station_id,
        include_synthetic=request.app.state.settings.demo_mode,
    )


@router.get("/stations/search", tags=["stations"])
def search_stations(
    request: Request,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_m: float | None = None,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    """Search the station catalog by a bounded geodesic radius or WGS84 bbox."""
    center_values = (latitude, longitude, radius_m)
    bbox_values = (west, south, east, north)
    has_center = any(value is not None for value in center_values)
    has_bbox = any(value is not None for value in bbox_values)
    if has_center == has_bbox:
        raise HTTPException(
            status_code=422,
            detail="provide either latitude/longitude/radius_m or west/south/east/north",
        )
    if has_center:
        if any(value is None for value in center_values):
            raise HTTPException(
                status_code=422,
                detail="latitude, longitude, and radius_m must be provided together",
            )
        assert latitude is not None and longitude is not None and radius_m is not None
        if (
            not all(math.isfinite(value) for value in center_values if value is not None)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
            or not 1 <= radius_m <= 100_000
        ):
            raise HTTPException(
                status_code=422,
                detail="center coordinates or radius_m are outside supported bounds",
            )
        stations = request.app.state.station_repository.within_radius(
            longitude,
            latitude,
            radius_m,
            limit,
            include_synthetic=request.app.state.settings.demo_mode,
        )
    else:
        if any(value is None for value in bbox_values):
            raise HTTPException(
                status_code=422,
                detail="west, south, east, and north must be provided together",
            )
        assert west is not None and south is not None and east is not None and north is not None
        if (
            not all(math.isfinite(value) for value in bbox_values if value is not None)
            or not -180 <= west <= 180
            or not -180 <= east <= 180
            or not -90 <= south < north <= 90
            or west == east
        ):
            raise HTTPException(
                status_code=422,
                detail="bbox coordinates are outside supported bounds",
            )
        stations = request.app.state.station_repository.within_bbox(
            west,
            south,
            east,
            north,
            limit,
            include_synthetic=request.app.state.settings.demo_mode,
        )
    if not request.app.state.settings.demo_mode:
        stations = tuple(
            station for station in stations if not _station_has_synthetic_data(station)
        )
    return stations


@router.get("/stations/{station_id}/status", tags=["stations"])
def station_status(station_id: str, request: Request):
    try:
        station = request.app.state.station_repository.get(station_id)
        if not request.app.state.settings.demo_mode and _station_has_synthetic_data(station):
            raise HTTPException(status_code=404, detail="station not found")
        status = _current_station_status(request, station_id)
        return _release_safe_status(request, status)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc


@router.get("/stations/statuses", response_model=list[StationStatus], tags=["stations"])
def station_statuses(
    request: Request,
    station_ids: list[str] = Query(min_length=1, max_length=200),
):
    """Return a bounded batch of current snapshots for a visible station set."""
    if len(station_ids) != len(set(station_ids)):
        raise HTTPException(status_code=422, detail="station_ids must be unique")
    eligible_ids = request.app.state.station_repository.filter_ids(
        tuple(station_ids),
        include_synthetic=request.app.state.settings.demo_mode,
    )
    if request.app.state.settings.demo_mode:
        request.app.state.runtime_state.refresh()
        current_statuses = request.app.state.runtime_state.all()
    else:
        current_statuses = request.app.state.runtime_state.get_many(eligible_ids)
    by_id = {status.station_id: status for status in current_statuses}
    return [
        _release_safe_status(request, by_id[station_id])
        for station_id in eligible_ids
        if station_id in by_id
    ]


@router.get(
    "/stations/{station_id}/history",
    response_model=list[StationOccupancyObservation],
    tags=["stations"],
)
def station_occupancy_history(
    station_id: str,
    request: Request,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = Query(default=288, ge=1, le=1000),
):
    """Return up to 1000 observed five-minute occupancy buckets, oldest first."""
    now = datetime.now(UTC)
    end = end_at or now
    start = start_at or end - timedelta(hours=24)
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status_code=422, detail="history timestamps must include a timezone")
    if start >= end or end - start > timedelta(days=30):
        raise HTTPException(
            status_code=422,
            detail="history range must be positive and at most 30 days",
        )
    try:
        station = request.app.state.station_repository.get(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc
    if not request.app.state.settings.demo_mode and _station_has_synthetic_data(station):
        raise HTTPException(status_code=404, detail="station not found")
    repository = request.app.state.occupancy_history_repository
    if repository is None:
        if request.app.state.settings.demo_mode:
            return []
        raise HTTPException(status_code=503, detail="occupancy history is unavailable")
    try:
        rows = repository.get_observations(
            station_id, start_at=start, end_at=end, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [
        StationOccupancyObservation(
            station_id=station_id,
            bucket_at=row["bucket_at"],
            total_ports=row["total_ports"],
            operational_ports=row["operational_ports"],
            occupied_ports=row["occupied_ports"],
            occupancy_ratio=(
                row["occupied_ports"] / row["operational_ports"]
                if row["operational_ports"]
                else None
            ),
            queue_length=row["queue_length"],
        )
        for row in rows
    ]


@router.get(
    "/stations/{station_id}/forecast",
    response_model=StationOccupancyForecast,
    tags=["stations"],
)
def station_occupancy_forecast(
    station_id: str,
    request: Request,
    horizon_min: int = 15,
):
    """Return a timestamped occupancy forecast for a supported product horizon."""
    if horizon_min not in (5, 10, 15, 20, 25, 30):
        raise HTTPException(
            status_code=422,
            detail="horizon_min must be one of 5, 10, 15, 20, 25, or 30",
        )
    try:
        station = request.app.state.station_repository.get(station_id)
        if not request.app.state.settings.demo_mode and _station_has_synthetic_data(station):
            raise HTTPException(status_code=404, detail="station not found")
        status = _release_safe_status(request, _current_station_status(request, station_id))
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc

    if status.is_stale:
        raise HTTPException(status_code=503, detail="station status is stale or unverified")
    if status.timestamp.tzinfo is None:
        raise HTTPException(status_code=503, detail="station status timestamp has no timezone")

    history_repository = request.app.state.occupancy_history_repository
    history = (
        history_repository.get_history(
            station_id,
            as_of=status.timestamp,
            steps=request.app.state.occupancy_forecast_service.lookback_steps,
        )
        if history_repository is not None
        else None
    )
    generated_at = datetime.now(UTC)
    target_at = generated_at + timedelta(minutes=horizon_min)
    forecast = request.app.state.occupancy_forecast_service.forecast_occupancy(
        status,
        horizon_min=horizon_min,
        occupancy_history=history,
        forecast_at=target_at,
    )
    request.app.state.persist_occupancy_forecasts((forecast,))
    return {
        **forecast.model_dump(mode="json"),
        "confidence": None,
    }


@router.get("/stations/{station_id}", tags=["stations"])
def station_detail(station_id: str, request: Request):
    try:
        station = request.app.state.station_repository.get(station_id)
        if not request.app.state.settings.demo_mode and _station_has_synthetic_data(station):
            raise HTTPException(status_code=404, detail="station not found")
        return station
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc


@router.get("/vehicles", tags=["vehicles"])
def list_vehicles(request: Request):
    vehicles = request.app.state.vehicle_repository.all()
    if request.app.state.settings.demo_mode:
        return vehicles
    return tuple(vehicle for vehicle in vehicles if vehicle.is_release_eligible)


@router.get("/journeys/{journey_id}", tags=["journeys"])
def get_journey(
    journey_id: UUID,
    request: Request,
    authorization: str | None = Header(default=None),
):
    repository = request.app.state.journey_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="journey persistence is disabled")
    try:
        stored = repository.get(
            journey_id, access_token=_extract_bearer_token(authorization)
        )
        stored["active_planned_arrival"] = (
            request.app.state.planned_arrival_store.active_for_journey(str(journey_id))
        )
        return stored
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="journey not found") from exc


@router.delete("/journeys/{journey_id}/access-token", status_code=204, tags=["journeys"])
def revoke_journey_access(
    journey_id: UUID,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    repository = request.app.state.journey_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="journey persistence is disabled")
    try:
        repository.revoke_access(journey_id, access_token=_extract_bearer_token(authorization))
    except (KeyError, PermissionError) as exc:
        raise HTTPException(status_code=404, detail="journey not found") from exc
    return Response(status_code=204)


@router.post("/journeys/{journey_id}/positions", tags=["journeys"])
def record_journey_position(
    journey_id: UUID,
    payload: TripPositionRequest,
    request: Request,
    authorization: str | None = Header(default=None),
):
    repository = request.app.state.journey_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="journey persistence is disabled")
    try:
        position_result = repository.record_position(
            journey_id,
            payload,
            access_token=_extract_bearer_token(authorization),
            deviation_threshold_m=request.app.state.settings.replan_deviation_threshold_m,
            min_reroute_interval_min=request.app.state.settings.replan_min_interval_min,
        )
        if not position_result["replan_suggested"]:
            return {"position": position_result, "recommendation": None}
        if payload.battery_pct is None:
            return {
                "position": position_result,
                "recommendation": None,
                "replan_reason": "BATTERY_LEVEL_REQUIRED",
            }

        stored_journey = repository.get(
            journey_id, access_token=_extract_bearer_token(authorization)
        )
        previous_request = JourneyRecommendationRequest.model_validate(
            stored_journey["request"]
        )
        replan_payload = previous_request.model_copy(
            update={
                "scenario_id": None,
                "apply_scenario_events": False,
                "initial_soc": payload.battery_pct / 100,
                "origin": payload.location,
                "departure_at": payload.recorded_at,
            }
        )
        scenario = _scenario_from_payload(replan_payload, request)
        result = request.app.state.recommendation_service.recommend_scenario(scenario)
        result = result.model_copy(
            update={"scenario_id": None, "journey_id": str(journey_id)}
        )
        repository.save_replan(journey_id, replan_payload, result)
        return {"position": position_result, "recommendation": result}
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="journey not found") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey or vehicle not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/stations/{station_id}/incidents",
    response_model=StationIncidentReport,
    status_code=201,
    tags=["incidents"],
)
def report_station_incident(
    station_id: str,
    payload: StationIncidentReportRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> StationIncidentReport:
    repository = request.app.state.incident_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="incident persistence is disabled")
    try:
        result = repository.report(
            payload.journey_id,
            station_id,
            payload,
            access_token=_extract_bearer_token(authorization),
        )
        return StationIncidentReport.model_validate(result)
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail="journey not found") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="journey or station not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/admin/incidents", response_model=list[StationIncidentAdminRecord], tags=["incidents"])
def list_station_incidents_for_review(
    request: Request,
    status: Literal["open", "triaged", "resolved", "rejected"] | None = None,
    limit: int = 100,
    api_key: str | None = Header(default=None, alias="X-Incident-Review-API-Key"),
) -> list[StationIncidentAdminRecord]:
    _require_incident_review_key(request, api_key)
    repository = request.app.state.incident_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="incident persistence is disabled")
    try:
        records = repository.list_for_review(status=status, limit=limit)
        return [StationIncidentAdminRecord.model_validate(record) for record in records]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch(
    "/admin/incidents/{incident_id}/review",
    response_model=StationIncidentAdminRecord,
    tags=["incidents"],
)
def review_station_incident(
    incident_id: UUID,
    payload: StationIncidentReviewRequest,
    request: Request,
    api_key: str | None = Header(default=None, alias="X-Incident-Review-API-Key"),
) -> StationIncidentAdminRecord:
    _require_incident_review_key(request, api_key)
    repository = request.app.state.incident_repository
    if repository is None:
        raise HTTPException(status_code=503, detail="incident persistence is disabled")
    try:
        record = repository.review(incident_id, payload)
        return StationIncidentAdminRecord.model_validate(record)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="incident not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/demo/scenarios", tags=["demo"])
def list_demo_scenarios(request: Request):
    _require_demo_mode(request)
    return request.app.state.domain_data.demo_scenarios.all()


@router.get("/geocoding/autocomplete", tags=["geocoding"])
def autocomplete_location(
    request: Request,
    query: str = Query(min_length=2, max_length=200),
    _user: dict = Depends(require_authenticated_user),
):
    try:
        return request.app.state.geocoding_service.autocomplete(query)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/geocoding/details/{place_id:path}", tags=["geocoding"])
def geocoding_details(
    request: Request,
    place_id: str = Path(min_length=1, max_length=256),
    _user: dict = Depends(require_authenticated_user),
):
    try:
        return request.app.state.geocoding_service.details(place_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="demo place not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/route", response_model=RouteResult, tags=["routing"])
def route(
    payload: RouteRequest,
    request: Request,
    _user: dict = Depends(require_authenticated_user),
) -> RouteResult:
    try:
        return request.app.state.routing_service.route(
            payload.origin,
            payload.destination,
            payload.waypoints,
            preferred_route_id=payload.preferred_route_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="route cache not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/journey/recommend",
    response_model=JourneyRecommendationResult,
    tags=["journey"],
)
def recommend(
    payload: JourneyRecommendationRequest,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _user: dict = Depends(require_authenticated_user),
) -> JourneyRecommendationResult:
    try:
        scoped_idempotency_key = idempotency_key
        if idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(
            idempotency_key
        ):
            raise HTTPException(
                status_code=422,
                detail="Idempotency-Key must be 16-200 safe ASCII characters",
            )
        repository = request.app.state.journey_repository
        if (
            not request.app.state.settings.demo_mode
            and payload.scenario_id is None
            and repository is not None
            and idempotency_key is None
        ):
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key is required for release journey requests",
            )
        repository = request.app.state.journey_repository
        if (
            not request.app.state.settings.demo_mode
            and payload.scenario_id is None
            and repository is not None
            and idempotency_key is not None
        ):
            signing_key = request.app.state.settings.journey_token_signing_key
            if signing_key is None:
                raise HTTPException(
                    status_code=503,
                    detail="journey capability signing is not configured",
                )
            scoped_idempotency_key = _scope_journey_idempotency_key(
                idempotency_key, _user, request.app.state.settings
            )
            access_token = _journey_capability_token(
                scoped_idempotency_key, signing_key
            )
            replay = repository.lookup_idempotent(
                payload,
                scoped_idempotency_key,
                access_token=access_token,
                access_token_ttl_days=request.app.state.settings.journey_token_ttl_days,
            )
            if replay is not None:
                response.headers["X-Journey-Access-Token"] = access_token
                return replay
        if payload.apply_scenario_events:
            _require_demo_mode(request)
        scenario = _scenario_from_payload(payload, request)
        result = request.app.state.recommendation_service.recommend_scenario(
            scenario,
            apply_scenario_events=payload.apply_scenario_events,
        )
        if payload.scenario_id is None:
            access_token = None
            if repository is not None:
                if not request.app.state.settings.demo_mode and idempotency_key is not None:
                    signing_key = request.app.state.settings.journey_token_signing_key
                    if signing_key is None:
                        raise HTTPException(
                            status_code=503,
                            detail="journey capability signing is not configured",
                        )
                    if scoped_idempotency_key is None:
                        scoped_idempotency_key = _scope_journey_idempotency_key(
                            idempotency_key, _user, request.app.state.settings
                        )
                    access_token = _journey_capability_token(
                        scoped_idempotency_key, signing_key
                    )
                else:
                    access_token = secrets.token_urlsafe(32)
            journey_id = str(uuid4()) if repository is not None else None
            result = result.model_copy(
                update={"scenario_id": None, "journey_id": journey_id}
            )
            if repository is not None:
                normalized_request = payload.model_copy(
                    update={
                        "vehicle_id": scenario.vehicle_id,
                        "initial_soc": scenario.initial_soc,
                        "target_soc": scenario.target_soc,
                        "origin": scenario.origin,
                        "destination": scenario.destination,
                        "departure_at": scenario.departure_at,
                    }
                )
                assert access_token is not None
                result = repository.save(
                    normalized_request,
                    result,
                    access_token=access_token,
                    access_token_ttl_days=request.app.state.settings.journey_token_ttl_days,
                    idempotency_key=scoped_idempotency_key,
                    idempotency_request=payload,
                )
                response.headers["X-Journey-Access-Token"] = access_token
        return result
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="scenario data not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/demo/events/{event_id}/apply", tags=["demo"])
def apply_event(event_id: str, request: Request):
    _require_demo_mode(request)
    try:
        request.app.state.runtime_state.refresh()
        status = request.app.state.runtime_state.apply(event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="event not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "event_id": event_id,
        "active_event_ids": request.app.state.runtime_state.active_event_ids(),
        "station_status": status,
    }


@router.post("/demo/reset", tags=["demo"])
def reset_demo(request: Request) -> dict[str, str]:
    _require_demo_mode(request)
    request.app.state.runtime_state.reset()
    request.app.state.planned_arrival_store.reset()
    request.app.state.realtime_telemetry_store.reset()
    return {"status": "reset"}


def _validate_arrival_references(
    request: Request, station_id: str, vehicle_id: str | None
) -> None:
    station = request.app.state.station_repository.get(station_id)
    if (
        not request.app.state.settings.demo_mode
        and _station_has_synthetic_data(station)
    ):
        raise KeyError(station_id)
    if vehicle_id is not None:
        vehicle = request.app.state.vehicle_repository.get(vehicle_id)
        if not request.app.state.settings.demo_mode and not vehicle.is_release_eligible:
            raise KeyError(vehicle_id)


@router.put(
    "/realtime/stations/{station_id}/telemetry",
    response_model=StationTelemetrySnapshot,
    tags=["realtime"],
)
def upsert_station_telemetry(
    station_id: str,
    payload: StationTelemetrySnapshot,
    request: Request,
    api_key: str | None = Header(default=None, alias="X-Telemetry-API-Key"),
) -> StationTelemetrySnapshot:
    """Ingest one complete station snapshot from a configured telemetry source."""
    _require_telemetry_key(request, api_key)
    if not request.app.state.settings.demo_mode and payload.data_source == "simulated":
        raise HTTPException(status_code=422, detail="simulated telemetry is disabled")
    try:
        station = request.app.state.station_repository.get(station_id)
        if (
            not request.app.state.settings.demo_mode
            and _station_has_synthetic_data(station)
        ):
            raise KeyError(station_id)
        if payload.station_id != station_id:
            raise ValueError("path station_id does not match telemetry station_id")
        try:
            validate_observation_timestamp(
                payload.observed_at,
                now=datetime.now(UTC),
                max_future_skew_s=(
                    request.app.state.settings.realtime_telemetry_max_future_skew_s
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if len(payload.ports) != station.properties.total_ports:
            raise ValueError("telemetry snapshot must include every station port")
        expected_connector_counts = Counter(
            connector.type
            for connector in station.properties.connectors
            for _ in range(connector.count)
        )
        reported_connector_counts = Counter(
            connector_type
            for port in payload.ports
            for connector_type in port.connector_types
        )
        if reported_connector_counts != expected_connector_counts:
            raise ValueError(
                "telemetry connector counts do not match station catalog"
            )
        if not request.app.state.settings.demo_mode:
            port_inventory_reader = getattr(
                request.app.state.station_repository,
                "telemetry_port_inventory",
                None,
            )
            if not callable(port_inventory_reader):
                raise HTTPException(
                    status_code=503,
                    detail="release catalog cannot validate telemetry port identity",
                )
            catalog_ports = dict(port_inventory_reader(station_id))
            reported_ports = {
                port.port_id: tuple(port.connector_types) for port in payload.ports
            }
            if set(reported_ports) != set(catalog_ports):
                raise ValueError("telemetry port IDs do not match station catalog")
            if any(
                connector_types != (catalog_ports[port_id],)
                for port_id, connector_types in reported_ports.items()
            ):
                raise ValueError(
                    "telemetry port connector types do not match station catalog"
                )
        telemetry_store = request.app.state.realtime_telemetry_store
        upsert_with_change = getattr(telemetry_store, "upsert_with_change", None)
        if upsert_with_change is None:
            snapshot = telemetry_store.upsert(payload)
            changed = True
        else:
            snapshot, changed = upsert_with_change(payload)
        redis_client = request.app.state.redis_sync_client
        if changed and redis_client is not None:
            try:
                redis_client.publish(STATION_STATUS_CHANNEL, station_id)
            except RedisError:
                # PostgreSQL remains the source of truth; SSE polling is the fallback.
                logger.exception("station_status_publish_failed station_id=%s", station_id)
        return snapshot
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/realtime/stations/{station_id}/telemetry",
    response_model=StationTelemetrySnapshot,
    tags=["realtime"],
)
def station_telemetry(
    station_id: str,
    request: Request,
    api_key: str | None = Header(default=None, alias="X-Telemetry-API-Key"),
) -> StationTelemetrySnapshot:
    _require_telemetry_key(request, api_key)
    try:
        station = request.app.state.station_repository.get(station_id)
        if (
            not request.app.state.settings.demo_mode
            and _station_has_synthetic_data(station)
        ):
            raise KeyError(station_id)
        snapshot = request.app.state.realtime_telemetry_store.get(station_id)
        if (
            not request.app.state.settings.demo_mode
            and snapshot.data_source == "simulated"
        ):
            raise KeyError(station_id)
        return snapshot
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="telemetry snapshot not found") from exc


@router.get("/realtime/stations/status/events", tags=["realtime"])
async def station_status_events(
    request: Request,
    station_ids: list[str] = Query(default=[], max_length=200),
) -> StreamingResponse:
    """Stream status for a bounded visible station set; poll DB as recovery."""
    if len(station_ids) > 200 or len(station_ids) != len(set(station_ids)):
        raise HTTPException(status_code=422, detail="station_ids must be unique and at most 200")
    if not request.app.state.settings.demo_mode and not station_ids:
        raise HTTPException(status_code=422, detail="station_ids are required in release mode")
    eligible_station_ids = set(
        request.app.state.station_repository.filter_ids(
            tuple(station_ids),
            include_synthetic=request.app.state.settings.demo_mode,
        )
    )
    async def events():
        previous_payload = None
        redis_client = request.app.state.redis_client
        pubsub = None
        if redis_client is not None:
            try:
                pubsub = redis_client.pubsub()
                await pubsub.subscribe(STATION_STATUS_CHANNEL)
            except RedisError:
                logger.exception("station_status_subscribe_failed; falling back to polling")
                if pubsub is not None:
                    await pubsub.aclose()
                pubsub = None
        first_event = True
        try:
            while not await request.is_disconnected():
                if not first_event:
                    if pubsub is None:
                        await asyncio.sleep(request.app.state.settings.realtime_poll_interval_s)
                    else:
                        try:
                            await pubsub.get_message(
                                ignore_subscribe_messages=True,
                                timeout=request.app.state.settings.realtime_poll_interval_s,
                            )
                        except RedisError:
                            logger.exception(
                                "station_status_stream_failed; falling back to polling"
                            )
                            await pubsub.aclose()
                            pubsub = None
                            await asyncio.sleep(
                                request.app.state.settings.realtime_poll_interval_s
                            )
                first_event = False
                visible_station_ids = eligible_station_ids
                if not station_ids and request.app.state.settings.demo_mode:
                    visible_station_ids = {
                        station.station_id
                        for station in request.app.state.station_repository.all()
                    }
                if request.app.state.settings.demo_mode:
                    request.app.state.runtime_state.refresh()
                    current_statuses = request.app.state.runtime_state.all()
                else:
                    current_statuses = request.app.state.runtime_state.get_many(
                        tuple(sorted(visible_station_ids))
                    )
                statuses = [
                    _release_safe_status(request, status).model_dump(mode="json")
                    for status in current_statuses
                    if status.station_id in visible_station_ids
                ]
                payload = json.dumps(statuses, separators=(",", ":"), sort_keys=True)
                if payload != previous_payload:
                    yield f"event: station_status\ndata: {payload}\n\n"
                    previous_payload = payload
                else:
                    yield ": keep-alive\n\n"
        finally:
            if pubsub is not None:
                await pubsub.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/realtime/stations/{station_id}/simulate-wait",
    response_model=DESWaitResult,
    tags=["realtime"],
)
def simulate_realtime_wait(
    station_id: str,
    payload: DESWaitRequest,
    request: Request,
    api_key: str | None = Header(default=None, alias="X-Telemetry-API-Key"),
) -> DESWaitResult:
    _require_telemetry_key(request, api_key)
    _require_demo_mode(request)
    try:
        snapshot = request.app.state.realtime_telemetry_store.get(station_id)
        return request.app.state.des_wait_simulator.estimate(snapshot, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="telemetry snapshot not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/queue-lab/default-scenario",
    response_model=QueueLabSimulationRequest,
    tags=["queue-lab"],
)
def queue_lab_default_scenario(request: Request) -> QueueLabSimulationRequest:
    """Return the documented fixed-duration scenario whose wait is 28 minutes."""
    _require_demo_mode(request)
    return queue_lab_demo_request()


@router.post(
    "/queue-lab/simulate",
    response_model=QueueLabSimulationResult,
    tags=["queue-lab"],
)
def simulate_queue_lab(
    payload: QueueLabSimulationRequest, request: Request
) -> QueueLabSimulationResult:
    """Run the standalone deterministic / synthetic Monte Carlo queue simulator."""
    _require_demo_mode(request)
    return run_queue_lab(payload)


@router.get("/planned-arrivals", tags=["planned-arrivals"])
def list_planned_arrivals(
    request: Request,
    api_key: str | None = Header(default=None, alias="X-Planned-Arrival-Admin-Key"),
):
    _require_planned_arrival_admin_key(request, api_key)
    return request.app.state.planned_arrival_store.all()


@router.post(
    "/planned-arrivals",
    response_model=PlannedArrival,
    tags=["planned-arrivals"],
)
def register_planned_arrival(
    payload: PlannedArrivalCreateRequest,
    request: Request,
    api_key: str | None = Header(default=None, alias="X-Planned-Arrival-Admin-Key"),
) -> PlannedArrival:
    _require_planned_arrival_admin_key(request, api_key)
    try:
        _validate_arrival_references(request, payload.station_id, payload.vehicle_id)
        return request.app.state.planned_arrival_store.register(
            payload, created_at=datetime.now(UTC)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="arrival reference not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/planned-arrivals/commit",
    response_model=PlannedArrival,
    tags=["planned-arrivals"],
)
def commit_planned_arrival(
    payload: PlannedArrivalCommitRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> PlannedArrival:
    try:
        if not request.app.state.settings.demo_mode:
            if payload.journey_id is None:
                raise HTTPException(status_code=422, detail="journey_id is required")
            journey_repository = request.app.state.journey_repository
            if journey_repository is None:
                raise HTTPException(status_code=503, detail="journey persistence is disabled")
            try:
                stored = journey_repository.get(
                    payload.journey_id,
                    access_token=_extract_bearer_token(authorization),
                )
            except (KeyError, PermissionError) as exc:
                raise HTTPException(status_code=404, detail="journey not found") from exc
            journey_request = JourneyRecommendationRequest.model_validate(stored["request"])
            if payload.vehicle_id != journey_request.vehicle_id:
                raise HTTPException(status_code=409, detail="vehicle does not match journey")
            recommendation = stored["recommendation"]
            selected = next(
                (
                    item for item in recommendation.get("recommendations", ())
                    if item.get("station_id") == payload.station_id
                ),
                None,
            )
            if selected is None:
                raise HTTPException(
                    status_code=409,
                    detail="station is not part of this journey recommendation",
                )
            payload = payload.model_copy(
                update={
                    "route_id": selected["route_id"],
                    "route_duration_to_station_s": selected[
                        "route_duration_to_station_s"
                    ],
                    "expected_energy_kwh": selected["energy_to_add_kwh"],
                    "expected_charge_duration_min": selected[
                        "estimated_charge_min"
                    ],
                }
            )
        _validate_arrival_references(request, payload.station_id, payload.vehicle_id)
        eta_at = payload.departure_at + timedelta(seconds=payload.route_duration_to_station_s)
        create_request = PlannedArrivalCreateRequest(
            arrival_id=payload.arrival_id,
            journey_id=payload.journey_id,
            station_id=payload.station_id,
            vehicle_id=payload.vehicle_id,
            eta_at=eta_at,
            eta_window_start=eta_at - timedelta(minutes=5),
            eta_window_end=eta_at + timedelta(minutes=5),
            expected_energy_kwh=payload.expected_energy_kwh,
            expected_charge_duration_min=payload.expected_charge_duration_min,
            arrival_probability=0.85,
            expires_at=eta_at + timedelta(minutes=10),
            route_id=payload.route_id,
        )
        return request.app.state.planned_arrival_store.register(
            create_request, created_at=datetime.now(UTC)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="arrival reference not found") from exc
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/planned-arrivals/expire", tags=["planned-arrivals"])
def expire_planned_arrivals(
    evaluation_at: datetime,
    request: Request,
    api_key: str | None = Header(default=None, alias="X-Planned-Arrival-Admin-Key"),
):
    _require_planned_arrival_admin_key(request, api_key)
    if evaluation_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="evaluation_at requires timezone")
    return request.app.state.planned_arrival_store.expire(evaluation_at)


@router.post(
    "/planned-arrivals/{arrival_id}/cancel",
    response_model=PlannedArrival,
    tags=["planned-arrivals"],
)
def cancel_planned_arrival(
    arrival_id: str,
    request: Request,
    journey_id: UUID | None = None,
    authorization: str | None = Header(default=None),
) -> PlannedArrival:
    try:
        arrival = request.app.state.planned_arrival_store.get(arrival_id)
        _authorize_planned_arrival_owner(request, arrival, journey_id, authorization)
        return request.app.state.planned_arrival_store.cancel(arrival_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="arrival not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/planned-arrivals/{arrival_id}/arrived",
    response_model=PlannedArrival,
    tags=["planned-arrivals"],
)
def mark_planned_arrival_arrived(
    arrival_id: str,
    request: Request,
    journey_id: UUID | None = None,
    authorization: str | None = Header(default=None),
) -> PlannedArrival:
    try:
        arrival = request.app.state.planned_arrival_store.get(arrival_id)
        _authorize_planned_arrival_owner(request, arrival, journey_id, authorization)
        return request.app.state.planned_arrival_store.mark_arrived(arrival_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="arrival not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/model/status", response_model=ModelStatus, tags=["model"])
def model_status(request: Request) -> ModelStatus:
    settings = request.app.state.settings
    model_available = settings.model_artifact_path.is_file()
    preprocessor_available = settings.model_preprocessor_path.is_file()
    metadata_available = settings.model_meta_path.is_file()
    model_loaded = request.app.state.occupancy_forecast_service.model_loaded
    metadata = request.app.state.model_metadata
    artifacts_available = model_available and preprocessor_available and metadata_available
    history_storage_ready = (
        settings.demo_mode or settings.occupancy_history_storage == "database"
    )
    release_ready = artifacts_available and model_loaded and history_storage_ready
    flags: tuple[str, ...] = ()
    if not artifacts_available:
        flags = (request.app.state.model_load_error or "PHASE_04_ARTIFACTS_UNAVAILABLE",)
    elif not model_loaded:
        flags = (request.app.state.model_load_error or "MODEL_ADAPTER_NOT_LOADED",)
    elif not history_storage_ready:
        flags = ("OBSERVED_HISTORY_STORAGE_UNAVAILABLE",)
    return ModelStatus(
        prediction_source="model" if model_loaded else "persistence",
        model_artifact_available=model_available,
        preprocessor_artifact_available=preprocessor_available,
        metadata_available=metadata_available,
        model_adapter_loaded=model_loaded,
        release_ready=release_ready,
        flags=flags,
        model_version=metadata.get("model_version") if metadata else None,
        model_profile=metadata.get("profile") if metadata else None,
        serving_reason=(
            "Validated model release loaded"
            if metadata and history_storage_ready
            else "Validated model loaded; observed occupancy history storage is unavailable"
            if metadata
            else "No approved ML release deployed"
        ),
    )
