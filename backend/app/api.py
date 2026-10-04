"""HTTP endpoints for the Phase 07 backend demo flow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from backend.app.domain.models import PlannedArrival
from backend.app.domain.phase7_models import (
    JourneyRecommendationRequest,
    JourneyRecommendationResult,
    ModelStatus,
    PlannedArrivalCommitRequest,
    PlannedArrivalCreateRequest,
    RouteRequest,
    RouteResult,
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
)

router = APIRouter()


def _scenario_from_payload(payload: JourneyRecommendationRequest, request: Request):
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
def list_stations(request: Request):
    return request.app.state.domain_data.stations.all()


@router.get("/stations/{station_id}/status", tags=["stations"])
def station_status(station_id: str, request: Request):
    try:
        return request.app.state.runtime_state.get(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc


@router.get("/stations/{station_id}", tags=["stations"])
def station_detail(station_id: str, request: Request):
    try:
        return request.app.state.domain_data.stations.get(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc


@router.get("/vehicles", tags=["vehicles"])
def list_vehicles(request: Request):
    return request.app.state.domain_data.vehicles.all()


@router.get("/demo/scenarios", tags=["demo"])
def list_demo_scenarios(request: Request):
    return request.app.state.domain_data.demo_scenarios.all()


@router.get("/geocoding/autocomplete", tags=["geocoding"])
def autocomplete_location(query: str, request: Request):
    return request.app.state.geocoding_service.autocomplete(query)


@router.get("/geocoding/details/{place_id:path}", tags=["geocoding"])
def geocoding_details(place_id: str, request: Request):
    try:
        return request.app.state.geocoding_service.details(place_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="demo place not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/route", response_model=RouteResult, tags=["routing"])
def route(payload: RouteRequest, request: Request) -> RouteResult:
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
    payload: JourneyRecommendationRequest, request: Request
) -> JourneyRecommendationResult:
    try:
        scenario = _scenario_from_payload(payload, request)
        return request.app.state.recommendation_service.recommend_scenario(
            scenario,
            apply_scenario_events=payload.apply_scenario_events,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="scenario data not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/demo/events/{event_id}/apply", tags=["demo"])
def apply_event(event_id: str, request: Request):
    try:
        status = request.app.state.runtime_state.apply(event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="event not found") from exc
    return {
        "event_id": event_id,
        "active_event_ids": request.app.state.runtime_state.active_event_ids(),
        "station_status": status,
    }


@router.post("/demo/reset", tags=["demo"])
def reset_demo(request: Request) -> dict[str, str]:
    request.app.state.runtime_state.reset()
    request.app.state.planned_arrival_store.reset()
    request.app.state.realtime_telemetry_store.reset()
    return {"status": "reset"}


@router.put(
    "/realtime/stations/{station_id}/telemetry",
    response_model=StationTelemetrySnapshot,
    tags=["realtime"],
)
def upsert_station_telemetry(
    station_id: str,
    payload: StationTelemetrySnapshot,
    request: Request,
) -> StationTelemetrySnapshot:
    """Adapter endpoint for the future frontend simulator or station provider."""
    try:
        request.app.state.domain_data.stations.get(station_id)
        if payload.station_id != station_id:
            raise ValueError("path station_id does not match telemetry station_id")
        return request.app.state.realtime_telemetry_store.upsert(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/realtime/stations/{station_id}/telemetry",
    response_model=StationTelemetrySnapshot,
    tags=["realtime"],
)
def station_telemetry(station_id: str, request: Request) -> StationTelemetrySnapshot:
    try:
        return request.app.state.realtime_telemetry_store.get(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="telemetry snapshot not found") from exc


@router.post(
    "/realtime/stations/{station_id}/simulate-wait",
    response_model=DESWaitResult,
    tags=["realtime"],
)
def simulate_realtime_wait(
    station_id: str,
    payload: DESWaitRequest,
    request: Request,
) -> DESWaitResult:
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
def queue_lab_default_scenario() -> QueueLabSimulationRequest:
    """Return the documented fixed-duration scenario whose wait is 28 minutes."""
    return queue_lab_demo_request()


@router.post(
    "/queue-lab/simulate",
    response_model=QueueLabSimulationResult,
    tags=["queue-lab"],
)
def simulate_queue_lab(payload: QueueLabSimulationRequest) -> QueueLabSimulationResult:
    """Run the standalone deterministic / synthetic Monte Carlo queue simulator."""
    return run_queue_lab(payload)


@router.get("/planned-arrivals", tags=["planned-arrivals"])
def list_planned_arrivals(request: Request):
    return request.app.state.planned_arrival_store.all()


@router.post(
    "/planned-arrivals",
    response_model=PlannedArrival,
    tags=["planned-arrivals"],
)
def register_planned_arrival(
    payload: PlannedArrivalCreateRequest, request: Request
) -> PlannedArrival:
    data = request.app.state.domain_data
    try:
        data.stations.get(payload.station_id)
        if payload.vehicle_id is not None:
            data.vehicles.get(payload.vehicle_id)
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
    payload: PlannedArrivalCommitRequest, request: Request
) -> PlannedArrival:
    data = request.app.state.domain_data
    try:
        data.stations.get(payload.station_id)
        data.vehicles.get(payload.vehicle_id)
        eta_at = payload.departure_at + timedelta(seconds=payload.route_duration_to_station_s)
        create_request = PlannedArrivalCreateRequest(
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


@router.post("/planned-arrivals/expire", tags=["planned-arrivals"])
def expire_planned_arrivals(evaluation_at: datetime, request: Request):
    if evaluation_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="evaluation_at requires timezone")
    return request.app.state.planned_arrival_store.expire(evaluation_at)


@router.post(
    "/planned-arrivals/{arrival_id}/cancel",
    response_model=PlannedArrival,
    tags=["planned-arrivals"],
)
def cancel_planned_arrival(arrival_id: str, request: Request) -> PlannedArrival:
    try:
        return request.app.state.planned_arrival_store.cancel(arrival_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="arrival not found") from exc


@router.post(
    "/planned-arrivals/{arrival_id}/arrived",
    response_model=PlannedArrival,
    tags=["planned-arrivals"],
)
def mark_planned_arrival_arrived(arrival_id: str, request: Request) -> PlannedArrival:
    try:
        return request.app.state.planned_arrival_store.mark_arrived(arrival_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="arrival not found") from exc


@router.get("/model/status", response_model=ModelStatus, tags=["model"])
def model_status(request: Request) -> ModelStatus:
    settings = request.app.state.settings
    model_available = settings.model_artifact_path.is_file()
    preprocessor_available = settings.model_preprocessor_path.is_file()
    metadata_available = settings.model_meta_path.is_file()
    model_loaded = request.app.state.occupancy_forecast_service.model_loaded
    metadata = request.app.state.model_metadata
    artifacts_available = model_available and preprocessor_available and metadata_available
    release_ready = artifacts_available and model_loaded
    flags: tuple[str, ...] = ()
    if not artifacts_available:
        flags = (request.app.state.model_load_error or "PHASE_04_ARTIFACTS_UNAVAILABLE",)
    elif not model_loaded:
        flags = (request.app.state.model_load_error or "MODEL_ADAPTER_NOT_LOADED",)
    return ModelStatus(
        prediction_source="model" if model_loaded else "persistence",
        model_artifact_available=model_available,
        preprocessor_artifact_available=preprocessor_available,
        metadata_available=metadata_available,
        model_adapter_loaded=model_loaded,
        release_ready=release_ready,
        flags=flags,
        model_version=metadata.get("format_version") if metadata else None,
        model_profile=metadata.get("profile") if metadata else None,
        serving_reason=(
            "Validated model release loaded" if metadata else "No approved ML release deployed"
        ),
    )
