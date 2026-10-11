"""Legacy HTTP endpoints: catalog reads, geocoding, routing and model status."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.app.domain.phase7_models import ModelStatus, RouteRequest, RouteResult

router = APIRouter()


@router.get("/stations", tags=["stations"])
def list_stations(request: Request):
    return request.app.state.station_repository.all()


@router.get("/stations/{station_id}/status", tags=["stations"])
def station_status(station_id: str, request: Request):
    try:
        return request.app.state.station_status_repository.get(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc


@router.get("/stations/{station_id}", tags=["stations"])
def station_detail(station_id: str, request: Request):
    try:
        return request.app.state.station_repository.get(station_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="station not found") from exc


@router.get("/vehicles", tags=["vehicles"])
def list_vehicles(request: Request):
    return request.app.state.vehicle_repository.all()


@router.get("/geocoding/autocomplete", tags=["geocoding"])
def autocomplete_location(query: str, request: Request):
    return request.app.state.geocoding_service.autocomplete(query)


@router.get("/geocoding/details/{place_id:path}", tags=["geocoding"])
def geocoding_details(place_id: str, request: Request):
    try:
        return request.app.state.geocoding_service.details(place_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/route", response_model=RouteResult, tags=["routing"])
def route(payload: RouteRequest, request: Request) -> RouteResult:
    try:
        return request.app.state.routing_service.route(
            payload.origin, payload.destination, payload.waypoints
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/model/status", response_model=ModelStatus, tags=["model"])
def model_status(request: Request) -> ModelStatus:
    settings = request.app.state.settings
    model_available = settings.model_artifact_path.is_file()
    preprocessor_available = settings.model_preprocessor_path.is_file()
    metadata_available = settings.model_meta_path.is_file()
    forecasting = request.app.state.occupancy_forecast_service
    model_loaded = forecasting.model_loaded
    artifacts_available = model_available and preprocessor_available and metadata_available
    release_ready = artifacts_available and model_loaded
    flags: tuple[str, ...] = ()
    if not artifacts_available:
        flags = ("PHASE_04_ARTIFACTS_UNAVAILABLE",)
    elif not model_loaded:
        flags = ("MODEL_ADAPTER_NOT_LOADED",)
    if not model_loaded and forecasting.prediction_source == "default":
        flags = (*flags, "ML_DEFAULT_VALUES_ACTIVE")
    return ModelStatus(
        prediction_source=forecasting.prediction_source,
        model_artifact_available=model_available,
        preprocessor_artifact_available=preprocessor_available,
        metadata_available=metadata_available,
        model_adapter_loaded=model_loaded,
        release_ready=release_ready,
        flags=flags,
    )
