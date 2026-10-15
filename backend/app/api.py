"""Legacy HTTP endpoints: catalog reads, geocoding, routing and model status."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from backend.app.domain.phase7_models import ModelStatus, RouteRequest, RouteResult
from backend.app.domain.xgboost_predictor import model_files_available

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


@router.get("/geocoding/reverse", tags=["geocoding"])
def geocoding_reverse(
    request: Request,
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
):
    try:
        return request.app.state.geocoding_service.reverse(lat, lon)
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
    model_available = model_files_available(settings.model_dir)
    metadata_available = settings.model_meta_path.is_file()
    forecasting = request.app.state.occupancy_forecast_service
    model_loaded = forecasting.model_loaded
    flags: list[str] = []
    if not model_available:
        flags.append("MODEL_ARTIFACT_UNAVAILABLE")
    elif not model_loaded:
        flags.append("MODEL_ADAPTER_NOT_LOADED")
    if not model_loaded and forecasting.prediction_source == "default":
        flags.append("ML_DEFAULT_VALUES_ACTIVE")
    if model_loaded:
        # Simulator-trained boosters remain demo artifacts. Comparisons with persistence
        # belong to each training run's report, not a hard-coded claim about every model.
        flags.extend(
            (
                "SYNTHETIC_TRAINING_DATA",
                "MODEL_METADATA_CONTRACT_NOT_MET",
            )
        )
    return ModelStatus(
        prediction_source=forecasting.prediction_source,
        model_artifact_available=model_available,
        # Feature engineering lives in code (ml/features.py); there is no separate artifact.
        preprocessor_artifact_available=model_available,
        metadata_available=metadata_available,
        model_adapter_loaded=model_loaded,
        release_ready=False,
        flags=tuple(flags),
    )
