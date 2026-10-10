"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, Response
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from redis import Redis, RedisError
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.exc import (
    OperationalError,
    SQLAlchemyError,
)
from sqlalchemy.exc import (
    TimeoutError as SQLAlchemyTimeoutError,
)
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.api import _station_has_synthetic_data, router
from backend.app.arrival_rate_repository import DatabaseArrivalRateRepository
from backend.app.catalog_repository import (
    DatabaseStationRepository,
    DatabaseStationStatusRepository,
    DatabaseVehicleRepository,
)
from backend.app.config import load_settings, validate_release_settings
from backend.app.database import create_database_engine, validate_database
from backend.app.domain import load_domain_data
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.geocoding import GeocodingService, GoongGeocodingProvider
from backend.app.domain.model_artifacts import ArtifactValidationError, JoblibOccupancyPredictor
from backend.app.domain.models import OccupancyForecastResult
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
from backend.app.incident_repository import DatabaseIncidentRepository
from backend.app.journey_repository import DatabaseJourneyRepository
from backend.app.logging_config import configure_logging
from backend.app.occupancy_forecast_cache import RedisOccupancyForecastCache
from backend.app.occupancy_history_repository import DatabaseOccupancyHistoryRepository
from backend.app.planned_arrival_repository import DatabasePlannedArrivalRepository
from backend.app.prediction_repository import DatabasePredictionRepository
from backend.app.rate_limit import consume_request
from backend.app.telemetry_repository import DatabaseRealtimeTelemetryStore

settings = load_settings()
validate_release_settings(settings)
configure_logging(settings.log_level)
logger = logging.getLogger("smart_ev.integration")
request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")

@asynccontextmanager
async def lifespan(application: FastAPI):
    expiry_task = None
    if not application.state.settings.demo_mode:
        expiry_task = asyncio.create_task(
            _expire_planned_arrivals_periodically(application)
        )
    try:
        yield
    finally:
        if expiry_task is not None:
            expiry_task.cancel()
            with suppress(asyncio.CancelledError):
                await expiry_task
        resources = (
            ("async_redis", application.state.redis_client, "aclose"),
            ("sync_redis", application.state.redis_sync_client, "close"),
            ("database", application.state.database_engine, "dispose"),
        )
        for resource_name, resource, close_method in resources:
            if resource is None:
                continue
            try:
                result = getattr(resource, close_method)()
                if close_method == "aclose":
                    await result
            except Exception:
                logger.exception("resource_shutdown_failed resource=%s", resource_name)


async def _expire_planned_arrivals_periodically(application: FastAPI) -> None:
    while True:
        try:
            expired = await asyncio.to_thread(
                application.state.planned_arrival_store.expire, datetime.now(UTC)
            )
            if expired:
                logger.info("planned_arrivals_expired count=%d", len(expired))
        except Exception:
            logger.exception("planned_arrival_expiry_failed")
        await asyncio.sleep(30)


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


def _stable_http_error_code(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "AUTHENTICATION_REQUIRED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        415: "UNSUPPORTED_MEDIA_TYPE",
        422: "VALIDATION_FAILED",
        429: "RATE_LIMITED",
        503: "DEPENDENCY_UNAVAILABLE",
    }.get(status_code, "HTTP_ERROR")


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": jsonable_encoder(exc.detail),
            "error_code": _stable_http_error_code(exc.status_code),
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": jsonable_encoder(exc.errors()),
            "error_code": "VALIDATION_FAILED",
        },
    )


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_request_error request_id=%s exception_type=%s",
        getattr(request.state, "request_id", None),
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "internal server error", "error_code": "INTERNAL_ERROR"},
    )


async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning(
        "database_operation_unavailable request_id=%s exception_type=%s",
        getattr(request.state, "request_id", None),
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=503,
        content={
            "detail": "database operation unavailable",
            "error_code": "DEPENDENCY_UNAVAILABLE",
        },
    )


app.add_exception_handler(OperationalError, database_unavailable_handler)
app.add_exception_handler(SQLAlchemyTimeoutError, database_unavailable_handler)


metrics_registry = CollectorRegistry(auto_describe=True)
http_responses_total = Counter(
    "smart_ev_http_responses_total",
    "HTTP responses started by the API.",
    ("method", "route", "status"),
    registry=metrics_registry,
)
http_response_start_duration_seconds = Histogram(
    "smart_ev_http_response_start_duration_seconds",
    "Seconds from request arrival until response headers are ready.",
    ("method", "route"),
    registry=metrics_registry,
)
occupancy_forecasts_total = Counter(
    "smart_ev_occupancy_forecasts_total",
    "Occupancy forecasts grouped by prediction source.",
    ("source",),
    registry=metrics_registry,
)
occupancy_prediction_persistence_failures_total = Counter(
    "smart_ev_occupancy_prediction_persistence_failures_total",
    "Occupancy prediction writes that failed without failing forecast delivery.",
    registry=metrics_registry,
)
occupancy_fallbacks_total = Counter(
    "smart_ev_occupancy_fallbacks_total",
    "Occupancy forecasts served by persistence, grouped by bounded reason.",
    ("reason",),
    registry=metrics_registry,
)
routing_provider_events_total = Counter(
    "smart_ev_routing_provider_events_total",
    "External routing provider outcomes grouped by provider and bounded event type.",
    ("provider", "event"),
    registry=metrics_registry,
)
station_status_records = Gauge(
    "smart_ev_station_status_records",
    "Eligible station records grouped by status freshness.",
    ("freshness",),
    registry=metrics_registry,
)
station_status_metrics_refresh_error = Gauge(
    "smart_ev_station_status_metrics_refresh_error",
    "Whether the latest station status freshness metric refresh failed.",
    registry=metrics_registry,
)
station_catalog_source_age_seconds = Gauge(
    "smart_ev_station_catalog_oldest_source_timestamp_age_seconds",
    "Age of the oldest eligible station source timestamp, in seconds.",
    registry=metrics_registry,
)
station_catalog_timestamp_basis_records = Gauge(
    "smart_ev_station_catalog_timestamp_basis_records",
    "Eligible station records grouped by the basis of their catalog timestamp.",
    ("basis",),
    registry=metrics_registry,
)
station_catalog_future_timestamps = Gauge(
    "smart_ev_station_catalog_future_timestamps",
    "Eligible station records whose catalog timestamp is ahead of the API clock.",
    registry=metrics_registry,
)
occupancy_history_stations = Gauge(
    "smart_ev_occupancy_history_stations",
    "Eligible release stations grouped by complete observed-history coverage.",
    ("coverage",),
    registry=metrics_registry,
)
occupancy_history_metrics_refresh_error = Gauge(
    "smart_ev_occupancy_history_metrics_refresh_error",
    "Whether the latest observed-history coverage metric refresh failed.",
    registry=metrics_registry,
)
occupancy_history_coverage_ratio = Gauge(
    "smart_ev_occupancy_history_coverage_ratio",
    "Fraction of eligible release stations with a complete recent observed lookback window.",
    registry=metrics_registry,
)


def record_occupancy_forecast(result: OccupancyForecastResult) -> None:
    occupancy_forecasts_total.labels(result.prediction_source).inc()
    if result.prediction_source == "model":
        return
    if "STATION_OFFLINE" in result.flags:
        reason = "station_offline"
    elif "OBSERVED_HISTORY_UNAVAILABLE" in result.flags:
        reason = "observed_history_unavailable"
    elif "MODEL_INFERENCE_FAILED" in result.flags:
        reason = "model_inference_failed"
    else:
        reason = "model_unavailable"
    occupancy_fallbacks_total.labels(reason).inc()


def persist_occupancy_forecasts(
    results: tuple[OccupancyForecastResult, ...],
) -> None:
    prediction_repository = getattr(app.state, "prediction_repository", None)
    if prediction_repository is None:
        return
    try:
        prediction_repository.save_occupancy_forecasts(results)
    except Exception as exc:
        occupancy_prediction_persistence_failures_total.inc()
        logger.error(
            "occupancy_prediction_batch_persist_failed count=%s error_type=%s",
            len(results),
            type(exc).__name__,
        )


def record_routing_provider_event(provider: str, event: str) -> None:
    routing_provider_events_total.labels(provider, event).inc()


def record_station_status_freshness() -> tuple[str, ...] | None:
    try:
        stations = app.state.station_repository.all()
        if not settings.demo_mode:
            stations = tuple(
                station for station in stations if not _station_has_synthetic_data(station)
            )
        timestamp_freshness = _station_catalog_timestamp_freshness(stations)
        station_catalog_source_age_seconds.set(
            timestamp_freshness["oldest_source_timestamp_age_seconds"] or 0
        )
        station_catalog_timestamp_basis_records.labels("source").set(
            timestamp_freshness["source_timestamp_count"]
        )
        station_catalog_timestamp_basis_records.labels("database_updated_at").set(
            timestamp_freshness["database_timestamp_fallback_count"]
        )
        station_catalog_timestamp_basis_records.labels("missing").set(
            timestamp_freshness["missing_timestamp_count"]
        )
        station_catalog_future_timestamps.set(timestamp_freshness["future_timestamp_count"])
        statuses = {
            status.station_id: status for status in app.state.runtime_state.all()
        }
        fresh_count = 0
        for station in stations:
            status = statuses.get(station.station_id)
            if status is not None and not status.is_stale and status.data_source not in {
                "synthetic",
                "unknown",
                "runtime",
            }:
                fresh_count += 1
        eligible_count = len(stations)
        station_status_records.labels("eligible").set(eligible_count)
        station_status_records.labels("fresh").set(fresh_count)
        station_status_records.labels("stale").set(eligible_count - fresh_count)
        station_status_metrics_refresh_error.set(0)
        return tuple(station.station_id for station in stations)
    except Exception:
        station_status_metrics_refresh_error.set(1)
        logger.exception("station_status_metrics_refresh_failed")
        return None


def _station_catalog_timestamp_freshness(
    stations,
) -> dict[str, str | int | float | None]:
    """Separate source timestamps from database update-time fallbacks."""
    now = datetime.now(UTC)
    record_timestamps: list[datetime] = []
    source_timestamps: list[datetime] = []
    source_count = 0
    database_fallback_count = 0
    missing_count = 0
    future_count = 0
    for station in stations:
        timestamp = station.properties.source_updated_at
        basis = station.properties.source_updated_at_basis
        if timestamp is None or timestamp.utcoffset() is None or basis == "missing":
            missing_count += 1
            continue
        if timestamp > now:
            future_count += 1
        record_timestamps.append(timestamp)
        if basis == "source":
            source_count += 1
            source_timestamps.append(timestamp)
        elif basis == "database_updated_at":
            database_fallback_count += 1
    record_ages = [max(0.0, (now - value).total_seconds()) for value in record_timestamps]
    source_ages = [max(0.0, (now - value).total_seconds()) for value in source_timestamps]
    return {
        "source_timestamp_count": source_count,
        "database_timestamp_fallback_count": database_fallback_count,
        "missing_timestamp_count": missing_count,
        "future_timestamp_count": future_count,
        "oldest_source_timestamp": min(source_timestamps).isoformat()
        if source_timestamps
        else None,
        "oldest_source_timestamp_age_seconds": round(max(source_ages), 1)
        if source_ages
        else None,
        "oldest_catalog_timestamp": min(record_timestamps).isoformat()
        if record_timestamps
        else None,
        "oldest_catalog_timestamp_age_seconds": round(max(record_ages), 1)
        if record_ages
        else None,
    }


def _catalog_source_freshness_check(
    stations, *, max_age_s: float
) -> dict[str, str | int | float]:
    now = datetime.now(UTC)
    fresh = stale = missing = future = 0
    for station in stations:
        timestamp = station.properties.source_updated_at
        if (
            timestamp is None
            or timestamp.utcoffset() is None
            or station.properties.source_updated_at_basis != "source"
        ):
            missing += 1
            continue
        age_s = (now - timestamp.astimezone(UTC)).total_seconds()
        if age_s < 0:
            future += 1
        elif age_s > max_age_s:
            stale += 1
        else:
            fresh += 1
    return {
        "source_freshness_status": (
            "ok" if stations and fresh == len(stations) else "unavailable"
        ),
        "fresh_source_timestamps": fresh,
        "stale_source_timestamps": stale,
        "missing_source_timestamps": missing,
        "future_source_timestamps": future,
        "source_max_age_seconds": max_age_s,
    }


def record_occupancy_history_coverage(
    eligible_station_ids: tuple[str, ...] | None,
) -> None:
    try:
        if eligible_station_ids is None:
            raise RuntimeError("eligible station catalog is unavailable")
        if settings.demo_mode or app.state.occupancy_history_repository is None:
            measured_station_ids: tuple[str, ...] = ()
            covered_stations = 0
        else:
            measured_station_ids = eligible_station_ids
            covered_stations = (
                app.state.occupancy_history_repository.count_stations_with_complete_history(
                    measured_station_ids,
                    as_of=datetime.now(UTC),
                    steps=app.state.occupancy_forecast_service.lookback_steps,
                )
            )
        occupancy_history_stations.labels("eligible").set(len(measured_station_ids))
        occupancy_history_stations.labels("covered").set(covered_stations)
        occupancy_history_coverage_ratio.set(
            covered_stations / len(measured_station_ids) if measured_station_ids else 1
        )
        occupancy_history_metrics_refresh_error.set(0)
    except Exception:
        occupancy_history_metrics_refresh_error.set(1)
        logger.exception("occupancy_history_coverage_metrics_refresh_failed")


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Journey-Access-Token", "X-Request-ID"],
)
app.state.settings = settings
app.state.oidc_jwks_client = (
    PyJWKClient(
        settings.oidc_jwks_url,
        cache_jwk_set=True,
        lifespan=300,
        timeout=3,
        cooldown_duration=30,
    )
    if settings.oidc_jwks_url
    else None
)
app.state.metrics_registry = metrics_registry
app.state.persist_occupancy_forecasts = persist_occupancy_forecasts
app.state.domain_data = load_domain_data(settings.data_dir)
app.state.redis_client = (
    AsyncRedis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.redis_connect_timeout_s,
        socket_timeout=settings.redis_command_timeout_s,
    )
    if settings.redis_url
    else None
)
app.state.redis_sync_client = (
    Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=settings.redis_connect_timeout_s,
        socket_timeout=settings.redis_command_timeout_s,
    )
    if settings.redis_url
    else None
)
uses_database = (
    settings.catalog_storage == "database"
    or settings.planned_arrivals_storage == "database"
    or settings.realtime_telemetry_storage == "database"
    or settings.journey_storage == "database"
    or settings.occupancy_history_storage == "database"
)
app.state.database_engine = (
    create_database_engine(
        settings.database_url,
        connect_timeout_s=settings.database_connect_timeout_s,
        statement_timeout_ms=settings.database_statement_timeout_ms,
    )
    if uses_database
    else None
)
app.state.database_revision = (
    validate_database(app.state.database_engine) if uses_database else None
)
app.state.prediction_repository = (
    DatabasePredictionRepository(app.state.database_engine)
    if not settings.demo_mode and app.state.database_engine is not None
    else None
)
if settings.catalog_storage == "database":
    app.state.station_repository = DatabaseStationRepository(app.state.database_engine)
    app.state.vehicle_repository = DatabaseVehicleRepository(app.state.database_engine)
    app.state.station_status_repository = DatabaseStationStatusRepository(
        app.state.database_engine
    )
else:
    app.state.station_repository = app.state.domain_data.stations
    app.state.vehicle_repository = app.state.domain_data.vehicles
    app.state.station_status_repository = app.state.domain_data.station_statuses
app.state.model_metadata = None
app.state.model_load_error = None
occupancy_forecast_cache = (
    RedisOccupancyForecastCache(app.state.redis_sync_client)
    if app.state.redis_sync_client is not None
    else None
)
cache_namespace = "persistence"
try:
    predictor, metadata = JoblibOccupancyPredictor.from_files(
        settings.model_artifact_path,
        settings.model_preprocessor_path,
        settings.model_meta_path,
    )
    app.state.occupancy_forecast_service = OccupancyForecastService(
        predictor,
        model_horizons_min=tuple(metadata["horizons_min"]),
        require_observed_history=not settings.demo_mode,
        model_version=metadata["model_version"],
        on_forecast=record_occupancy_forecast,
        cache=occupancy_forecast_cache,
        cache_namespace=json.dumps(metadata, sort_keys=True, separators=(",", ":")),
        cache_ttl_s=settings.occupancy_forecast_cache_ttl_s,
    )
    app.state.model_metadata = metadata
    cache_namespace = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    logger.info("occupancy_model_loaded profile=%s", metadata.get("profile"))
except (ArtifactValidationError, FileNotFoundError):
    app.state.occupancy_forecast_service = OccupancyForecastService(
        require_observed_history=not settings.demo_mode,
        on_forecast=record_occupancy_forecast,
        cache=occupancy_forecast_cache,
        cache_namespace=cache_namespace,
        cache_ttl_s=settings.occupancy_forecast_cache_ttl_s,
    )
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
if settings.planned_arrivals_storage == "database":
    app.state.arrival_rate_repository = DatabaseArrivalRateRepository(
        app.state.database_engine,
        app.state.domain_data.queue_assumptions,
    )
    app.state.planned_arrival_store = DatabasePlannedArrivalRepository(
        app.state.database_engine,
        app.state.domain_data.planned_arrivals.all(),
    )
else:
    app.state.arrival_rate_repository = app.state.domain_data.queue_assumptions
    app.state.planned_arrival_store = PlannedArrivalStore(
        app.state.domain_data.planned_arrivals
    )
app.state.wait_estimator = WaitEstimator(
    app.state.arrival_rate_repository,
    scoring_wait_cap_min=settings.wait_scoring_cap_min,
)
app.state.journey_repository = (
    DatabaseJourneyRepository(app.state.database_engine)
    if settings.journey_storage == "database"
    else None
)
app.state.incident_repository = (
    DatabaseIncidentRepository(app.state.database_engine)
    if settings.journey_storage == "database"
    else None
)
app.state.occupancy_history_repository = (
    DatabaseOccupancyHistoryRepository(app.state.database_engine)
    if settings.occupancy_history_storage == "database"
    else None
)
# No residual-duration artifact is loaded yet.  The simulator therefore accepts
# provider-reported remaining durations only, and fails closed if they are absent.
app.state.realtime_telemetry_store = (
    DatabaseRealtimeTelemetryStore(app.state.database_engine)
    if settings.realtime_telemetry_storage == "database"
    else RealtimeTelemetryStore()
)
app.state.runtime_state = RuntimeStateStore(
    app.state.station_status_repository,
    app.state.domain_data.demo_events,
    telemetry=app.state.realtime_telemetry_store,
    telemetry_max_age_s=settings.realtime_telemetry_max_age_s,
    enforce_freshness=not settings.demo_mode,
)
app.state.des_wait_simulator = DiscreteEventWaitSimulator(ResidualDurationService())
goong_geocoding_provider = (
    GoongGeocodingProvider(settings.goong_api_key, timeout_s=settings.routing_timeout_s)
    if settings.goong_api_key
    else None
)
app.state.geocoding_service = GeocodingService(
    app.state.domain_data.demo_scenarios.all(),
    goong=goong_geocoding_provider,
    allow_demo_fallback=settings.demo_mode,
)
goong_provider = (
    GoongRoutingProvider(settings.goong_api_key, timeout_s=settings.routing_timeout_s)
    if settings.goong_api_key
    else None
)
app.state.routing_service = RoutingService(
    app.state.domain_data.routes,
    goong=goong_provider,
    osrm=OsrmRoutingProvider(
        base_url=settings.osrm_base_url,
        timeout_s=settings.routing_timeout_s,
    ),
    require_leg_metrics=not settings.demo_mode,
    record_provider_event=record_routing_provider_event,
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
    vehicle_repository=app.state.vehicle_repository,
    station_repository=app.state.station_repository,
    candidate_corridor_m=settings.recommend_candidate_corridor_m,
    max_candidates=settings.recommend_max_candidates,
    allow_synthetic_data=settings.demo_mode,
    occupancy_history=app.state.occupancy_history_repository,
    incident_impacts=app.state.incident_repository,
    prediction_writer=app.state.persist_occupancy_forecasts,
)
app.include_router(router)


def custom_openapi() -> dict:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    error_response = {
        "description": (
            "API error. `error_code` is stable; `detail` contains the legacy message "
            "or validation data."
        ),
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["detail", "error_code"],
                    "properties": {
                        "detail": {},
                        "error_code": {"type": "string"},
                    },
                }
            }
        },
    }
    http_methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    for path_item in schema.get("paths", {}).values():
        for method, operation in path_item.items():
            if method not in http_methods or not isinstance(operation, dict):
                continue
            responses = operation.setdefault("responses", {})
            if "422" in responses:
                responses["422"] = {
                    **error_response,
                    "description": "Request validation failed.",
                }
            responses.setdefault("default", error_response)
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


@app.middleware("http")
async def collect_http_metrics(request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)
    started_at = perf_counter()
    response = None
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_template = getattr(route, "path", "unmatched")
        method = request.method if request.method in {
            "GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"
        } else "OTHER"
        http_responses_total.labels(method, route_template, str(status)).inc()
        http_response_start_duration_seconds.labels(method, route_template).observe(
            perf_counter() - started_at
        )


@app.middleware("http")
async def integration_request_log(request, call_next):
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed request_id=%s method=%s path=%s",
            request_id_context.get(),
            request.method,
            request.url.path,
        )
        raise
    logger.info(
        "request_complete request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
        request_id_context.get(),
        request.method,
        request.url.path,
        response.status_code,
        (perf_counter() - started_at) * 1000,
    )
    return response


@app.middleware("http")
async def distributed_rate_limit(request, call_next):
    if request.url.path in {
        "/health",
        "/health/live",
        "/health/ready",
        "/health/checks",
        "/metrics",
    }:
        return await call_next(request)
    redis_client = request.app.state.redis_client
    if redis_client is None:
        if request.app.state.settings.demo_mode:
            return await call_next(request)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "distributed rate limiting is unavailable",
                "error_code": "DEPENDENCY_UNAVAILABLE",
            },
        )

    request_class = "read" if request.method in {"GET", "HEAD", "OPTIONS"} else "write"
    limit = (
        request.app.state.settings.api_rate_limit_read_per_min
        if request_class == "read"
        else request.app.state.settings.api_rate_limit_write_per_min
    )
    client_identity = request.client.host if request.client is not None else "unknown"
    try:
        allowed, remaining, retry_after = await consume_request(
            redis_client, client_identity, request_class, limit
        )
    except RedisError:
        logger.exception("rate_limit_store_unavailable request_class=%s", request_class)
        if request.app.state.settings.demo_mode:
            return await call_next(request)
        return JSONResponse(
            status_code=503,
            content={
                "detail": "distributed rate limiting is unavailable",
                "error_code": "DEPENDENCY_UNAVAILABLE",
            },
        )
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "request rate limit exceeded", "error_code": "RATE_LIMITED"},
            headers={"Retry-After": str(retry_after), "X-RateLimit-Remaining": "0"},
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response


@app.middleware("http")
async def request_id_middleware(request, call_next):
    supplied_id = request.headers.get("X-Request-ID", "")
    request_id = (
        supplied_id
        if REQUEST_ID_PATTERN.fullmatch(supplied_id)
        else uuid4().hex
    )
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_context.reset(token)


@app.get("/health", tags=["system"])
def health() -> dict[str, str | bool]:
    result: dict[str, str | bool] = {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "demo_mode": settings.demo_mode,
    }
    if app.state.database_engine is not None:
        try:
            result["database_revision"] = validate_database(app.state.database_engine)
        except RuntimeError as exc:
            logger.warning("health_database_unavailable error_type=%s", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="database is unavailable or its schema is not ready",
            ) from exc
    return result


@app.get("/metrics", include_in_schema=False, tags=["system"])
def prometheus_metrics(request: Request) -> Response:
    """Expose Prometheus metrics to scrapers on the internal application network."""
    eligible_station_ids = record_station_status_freshness()
    record_occupancy_history_coverage(eligible_station_ids)
    return Response(
        content=generate_latest(request.app.state.metrics_registry),
        headers={"Content-Type": CONTENT_TYPE_LATEST},
    )


@app.get("/health/live", tags=["system"])
def liveness() -> dict[str, str]:
    """Report that the API process is running without checking dependencies."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["system"])
async def readiness() -> dict[str, object]:
    """Report whether this process can serve using its configured persistence mode."""
    model_check: dict[str, str] = {
        "status": "loaded" if app.state.model_metadata is not None else "fallback",
        "prediction_source": "model" if app.state.model_metadata is not None else "persistence",
    }
    if app.state.model_metadata is None and app.state.model_load_error:
        model_check["reason"] = app.state.model_load_error
    checks: dict[str, object] = {
        "database": {"status": "not_required"},
        "catalog": {"status": "not_required"},
        "redis": {"status": "not_required"},
        "identity": {"status": "not_required"},
        "occupancy_model": model_check,
    }
    if not settings.demo_mode:
        jwks_client = app.state.oidc_jwks_client
        if jwks_client is None:
            checks["identity"] = {
                "status": "unavailable",
                "reason": "identity signing keys are not configured",
            }
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "checks": checks},
            )
        try:
            signing_keys = await asyncio.to_thread(jwks_client.get_signing_keys)
        except PyJWTError as exc:
            logger.warning("oidc_jwks_unavailable error_type=%s", type(exc).__name__)
            checks["identity"] = {
                "status": "unavailable",
                "reason": "identity signing keys are unavailable",
            }
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "checks": checks},
            ) from exc
        if not signing_keys:
            checks["identity"] = {
                "status": "unavailable",
                "reason": "identity signing keys are empty",
            }
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "checks": checks},
            )
        checks["identity"] = {"status": "ok", "signing_keys": len(signing_keys)}
    if app.state.database_engine is not None:
        try:
            revision = validate_database(app.state.database_engine)
        except RuntimeError as exc:
            logger.warning("readiness_database_unavailable error_type=%s", type(exc).__name__)
            checks["database"] = {
                "status": "unavailable",
                "reason": "database is unavailable or its schema is not ready",
            }
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "checks": checks},
            ) from exc
        checks["database"] = {"status": "ok", "revision": revision}
        if not settings.demo_mode and settings.catalog_storage == "database":
            try:
                stations = tuple(
                    station
                    for station in app.state.station_repository.all()
                    if not _station_has_synthetic_data(station)
                )
                vehicles = tuple(
                    vehicle
                    for vehicle in app.state.vehicle_repository.all()
                    if vehicle.is_release_eligible
                )
            except SQLAlchemyError as exc:
                logger.warning("readiness_catalog_unavailable error_type=%s", type(exc).__name__)
                checks["catalog"] = {
                    "status": "unavailable",
                    "reason": "operational catalog could not be read",
                }
                raise HTTPException(
                    status_code=503,
                    detail={"status": "not_ready", "checks": checks},
                ) from exc
            catalog_check = {
                "status": "incomplete",
                "eligible_stations": len(stations),
                "eligible_vehicles": len(vehicles),
            }
            catalog_check.update(_station_catalog_timestamp_freshness(stations))
            catalog_source_freshness = _catalog_source_freshness_check(
                stations,
                max_age_s=settings.catalog_source_max_age_s or 0,
            )
            catalog_check.update(catalog_source_freshness)
            if (
                stations
                and vehicles
                and catalog_source_freshness["source_freshness_status"] == "ok"
            ):
                catalog_check["status"] = "ok"
            checks["catalog"] = catalog_check
            if catalog_check["status"] != "ok":
                raise HTTPException(
                    status_code=503,
                    detail={"status": "not_ready", "checks": checks},
                )
            eligible_station_ids = {station.station_id for station in stations}
            fresh_statuses = tuple(
                status
                for status in app.state.runtime_state.all()
                if status.station_id in eligible_station_ids
                and not status.is_stale
                and status.data_source in {"station_api", "camera_vision", "combined"}
            )
            operational_statuses = tuple(
                status for status in fresh_statuses if status.operational_ports > 0
            )
            checks["station_status"] = {
                "status": "ok" if operational_statuses else "unavailable",
                "fresh_stations": len(fresh_statuses),
                "operational_stations": len(operational_statuses),
                "eligible_stations": len(stations),
            }
            if not operational_statuses:
                raise HTTPException(
                    status_code=503,
                    detail={"status": "not_ready", "checks": checks},
                )
    if app.state.redis_client is not None:
        try:
            await app.state.redis_client.ping()
        except RedisError as exc:
            logger.warning("readiness_redis_unavailable error_type=%s", type(exc).__name__)
            checks["redis"] = {
                "status": "unavailable",
                "reason": "rate-limit and realtime storage is unavailable",
            }
            raise HTTPException(
                status_code=503,
                detail={"status": "not_ready", "checks": checks},
            ) from exc
        checks["redis"] = {"status": "ok"}
    return {
        "status": "ready",
        "service": settings.app_name,
        "environment": settings.app_env,
        "demo_mode": settings.demo_mode,
        "checks": checks,
    }


@app.get("/health/checks", tags=["system"])
async def health_checks() -> dict[str, object]:
    """Expose dependency and model fallback state for deployment monitoring."""
    return await readiness()
