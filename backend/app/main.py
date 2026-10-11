"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine

from backend.app.api import router
from backend.app.api_errors import install_api_error_handlers
from backend.app.api_v1 import router as v1_router
from backend.app.app_config_repository import AppConfigRepository
from backend.app.catalog_repository import (
    DatabaseStationRepository,
    DatabaseStationStatusRepository,
    DatabaseVehicleRepository,
)
from backend.app.config import load_settings
from backend.app.database import validate_database
from backend.app.domain import load_domain_data
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.geocoding import GeocodingService, GoongGeocodingProvider
from backend.app.domain.ml_gateway import DefaultMlGateway
from backend.app.domain.recommendation import (
    RecommendationService,
    RecommendationThresholds,
)
from backend.app.domain.routing import (
    GoongRoutingProvider,
    OsrmRoutingProvider,
    RoutingService,
)
from backend.app.domain.runtime import RuntimeStateStore
from backend.app.domain.search import SearchService
from backend.app.domain.trip_service import TripService
from backend.app.domain.wait_estimation import WaitEstimator
from backend.app.logging_config import configure_logging
from backend.app.search_store import SearchRateLimiter, SearchResultStore
from backend.app.simulation_repository import DatabaseSimulationRepository
from backend.app.station_state_repository import DatabaseStationStateRepository
from backend.app.trip_repository import DatabaseTripRepository

settings = load_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("smart_ev.integration")


SIMULATION_STEP_MINUTES = 5


def _simulation_tick_at(now: datetime) -> datetime:
    """Return the current five-minute bucket boundary (UTC)."""
    return now.replace(
        minute=(now.minute // SIMULATION_STEP_MINUTES) * SIMULATION_STEP_MINUTES,
        second=0,
        microsecond=0,
    )


async def _simulation_loop(app: FastAPI, stop: asyncio.Event) -> None:
    """Refresh simulated state on wall-clock five-minute boundaries."""
    while not stop.is_set():
        tick_at = _simulation_tick_at(datetime.now(UTC))
        try:
            stations_updated, predictions_updated = await asyncio.to_thread(
                app.state.simulation_repository.update_tick,
                changed_at=tick_at,
            )
            await asyncio.to_thread(app.state.runtime_state.refresh)
            logger.info(
                "database_simulation_tick_complete stations=%d predictions=%d",
                stations_updated,
                predictions_updated,
            )
        except Exception:
            logger.exception("database_simulation_tick_failed")
        next_tick_at = tick_at + timedelta(minutes=SIMULATION_STEP_MINUTES)
        wait_seconds = max(
            0.0, (next_tick_at - datetime.now(UTC)).total_seconds()
        )
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait_seconds)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker = None
    stop = asyncio.Event()
    if app.state.simulation_repository is not None:
        worker = asyncio.create_task(_simulation_loop(app, stop))
    try:
        yield
    finally:
        stop.set()
        if worker is not None:
            await worker


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
install_api_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.settings = settings
app.state.domain_data = load_domain_data(settings.data_dir)
# Every backend -> ML call goes through this gateway; it returns fixed defaults until the
# real models are integrated (see backend/app/domain/ml_gateway.py).
app.state.ml_gateway = DefaultMlGateway()
app.state.occupancy_forecast_service = OccupancyForecastService(
    ml_gateway=app.state.ml_gateway
)
uses_database = settings.catalog_storage == "database"
app.state.database_engine = (
    create_engine(settings.database_url, pool_pre_ping=True) if uses_database else None
)
app.state.database_status = (
    validate_database(app.state.database_engine) if uses_database else None
)
app.state.app_config_repository = AppConfigRepository(
    settings, app.state.database_engine
)
if settings.catalog_storage == "database":
    app.state.station_repository = DatabaseStationRepository(app.state.database_engine)
    app.state.vehicle_repository = DatabaseVehicleRepository(app.state.database_engine)
    app.state.station_status_repository = DatabaseStationStatusRepository(
        app.state.database_engine,
        stale_after_s=settings.station_status_stale_after_s,
    )
    app.state.station_state_repository = DatabaseStationStateRepository(
        app.state.database_engine
    )
    # The 5-minute random occupancy is a demo-only data source. It stays off by default so it
    # cannot pollute station_occupancy_5m with noise; real status arrives through
    # POST /api/v1/internal/station-occupancy.
    app.state.simulation_repository = (
        DatabaseSimulationRepository(app.state.database_engine)
        if settings.demo_random_simulation
        else None
    )
else:
    app.state.station_repository = app.state.domain_data.stations
    app.state.vehicle_repository = app.state.domain_data.vehicles
    app.state.station_status_repository = app.state.domain_data.station_statuses
    app.state.station_state_repository = None
    app.state.simulation_repository = None
app.state.runtime_state = RuntimeStateStore(app.state.station_status_repository)
# Baseline arrival rates come from the JSON fixture; persisting them is deferred.
app.state.arrival_rate_repository = app.state.domain_data.queue_assumptions
app.state.wait_estimator = WaitEstimator(
    app.state.arrival_rate_repository,
    scoring_wait_cap_min=settings.wait_scoring_cap_min,
    ml_gateway=app.state.ml_gateway,
)
goong_geocoding_provider = (
    GoongGeocodingProvider(
        settings.goong_api_key, timeout_s=settings.routing_timeout_s
    )
    if settings.goong_api_key
    else None
)
app.state.geocoding_service = GeocodingService(goong=goong_geocoding_provider)
goong_provider = (
    GoongRoutingProvider(settings.goong_api_key, timeout_s=settings.routing_timeout_s)
    if settings.goong_api_key
    else None
)
app.state.routing_service = RoutingService(
    goong=goong_provider,
    osrm=OsrmRoutingProvider(timeout_s=settings.routing_timeout_s),
)
app.state.recommendation_service = RecommendationService(
    app.state.runtime_state,
    app.state.routing_service,
    app.state.occupancy_forecast_service,
    app.state.wait_estimator,
    RecommendationThresholds(
        max_detour_min=settings.recommend_max_detour_min,
        max_wait_min=settings.recommend_max_wait_min,
        max_charge_min=settings.recommend_max_charge_min,
        soc_risk_buffer=settings.recommend_soc_risk_buffer,
    ),
    vehicle_repository=app.state.vehicle_repository,
    station_repository=app.state.station_repository,
    candidate_corridor_m=settings.recommend_candidate_corridor_m,
)
app.state.search_result_store = SearchResultStore()
app.state.search_rate_limiter = SearchRateLimiter(settings.search_rate_limit_per_min)
app.state.search_service = SearchService(
    app.state.recommendation_service,
    app.state.routing_service,
    app.state.vehicle_repository,
    app.state.station_repository,
    app.state.station_status_repository,
    app.state.runtime_state,
    app.state.occupancy_forecast_service,
    app.state.wait_estimator,
    app.state.search_result_store,
    settings.availability_green_min,
    app.state.app_config_repository,
)
app.state.trip_service = (
    TripService(
        DatabaseTripRepository(app.state.database_engine),
        app.state.search_result_store,
        app.state.app_config_repository,
        app.state.search_service,
        app.state.station_repository,
        app.state.station_status_repository,
        app.state.vehicle_repository,
    )
    if app.state.database_engine is not None
    else None
)
app.include_router(router)
app.include_router(v1_router)


@app.middleware("http")
async def integration_request_log(request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or uuid4().hex
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
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.get("/health", tags=["system"])
def health() -> dict[str, str | bool]:
    result: dict[str, str | bool] = {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }
    if app.state.database_engine is not None:
        try:
            result["database"] = validate_database(
                app.state.database_engine
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result
