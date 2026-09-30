"""FastAPI application entry point."""

from __future__ import annotations

import logging
from time import perf_counter

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api import router
from backend.app.config import load_settings
from backend.app.domain import load_domain_data
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.geocoding import GeocodingService, GoongGeocodingProvider
from backend.app.domain.model_artifacts import ArtifactValidationError, JoblibOccupancyPredictor
from backend.app.domain.realtime import (
    DiscreteEventWaitSimulator,
    RealtimeTelemetryStore,
    ResidualDurationService,
)
from backend.app.domain.recommendation import (
    RecommendationService,
    RecommendationThresholds,
)
from backend.app.domain.routing import (
    GoongRoutingProvider,
    OsrmRoutingProvider,
    RoutingService,
)
from backend.app.domain.runtime import PlannedArrivalStore, RuntimeStateStore
from backend.app.domain.wait_estimation import WaitEstimator
from backend.app.logging_config import configure_logging

settings = load_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("smart_ev.integration")

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.settings = settings
app.state.domain_data = load_domain_data(settings.data_dir)
app.state.model_metadata = None
app.state.model_load_error = None
try:
    predictor, metadata = JoblibOccupancyPredictor.from_files(
        settings.model_artifact_path,
        settings.model_preprocessor_path,
        settings.model_meta_path,
    )
    app.state.occupancy_forecast_service = OccupancyForecastService(predictor)
    app.state.model_metadata = metadata
    logger.info("occupancy_model_loaded profile=%s", metadata.get("profile"))
except (ArtifactValidationError, FileNotFoundError):
    app.state.occupancy_forecast_service = OccupancyForecastService()
    if all(
        path.is_file()
        for path in (
            settings.model_artifact_path,
            settings.model_preprocessor_path,
            settings.model_meta_path,
        )
    ):
        app.state.model_load_error = "MODEL_RELEASE_INVALID"
        logger.warning("occupancy model artifacts exist but failed validation")
    else:
        app.state.model_load_error = "PHASE_04_ARTIFACTS_UNAVAILABLE"
app.state.wait_estimator = WaitEstimator(
    app.state.domain_data.queue_assumptions,
    scoring_wait_cap_min=settings.wait_scoring_cap_min,
)
app.state.runtime_state = RuntimeStateStore(
    app.state.domain_data.station_statuses,
    app.state.domain_data.demo_events,
)
app.state.planned_arrival_store = PlannedArrivalStore(
    app.state.domain_data.planned_arrivals
)
# No residual-duration artifact is loaded yet.  The simulator therefore accepts
# provider-reported remaining durations only, and fails closed if they are absent.
app.state.realtime_telemetry_store = RealtimeTelemetryStore()
app.state.des_wait_simulator = DiscreteEventWaitSimulator(ResidualDurationService())
goong_geocoding_provider = (
    GoongGeocodingProvider(
        settings.goong_api_key, timeout_s=settings.routing_timeout_s
    )
    if settings.goong_api_key
    else None
)
app.state.geocoding_service = GeocodingService(
    app.state.domain_data.demo_scenarios.all(), goong=goong_geocoding_provider
)
goong_provider = (
    GoongRoutingProvider(settings.goong_api_key, timeout_s=settings.routing_timeout_s)
    if settings.goong_api_key
    else None
)
app.state.routing_service = RoutingService(
    app.state.domain_data.routes,
    goong=goong_provider,
    osrm=OsrmRoutingProvider(timeout_s=settings.routing_timeout_s),
)
app.state.recommendation_service = RecommendationService(
    app.state.domain_data,
    app.state.runtime_state,
    app.state.planned_arrival_store,
    app.state.routing_service,
    app.state.occupancy_forecast_service,
    app.state.wait_estimator,
    RecommendationThresholds(
        max_detour_min=settings.recommend_max_detour_min,
        max_wait_min=settings.recommend_max_wait_min,
        max_charge_min=settings.recommend_max_charge_min,
        soc_risk_buffer=settings.recommend_soc_risk_buffer,
    ),
)
app.include_router(router)


@app.middleware("http")
async def integration_request_log(request, call_next):
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed method=%s path=%s", request.method, request.url.path)
        raise
    logger.info(
        "request_complete method=%s path=%s status=%s duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        (perf_counter() - started_at) * 1000,
    )
    return response


@app.get("/health", tags=["system"])
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "demo_mode": settings.demo_mode,
    }
