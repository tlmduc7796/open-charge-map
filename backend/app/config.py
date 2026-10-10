"""Environment-backed application settings and canonical project paths."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _resolve_from_root(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _parse_positive_float(name: str, raw_value: str) -> float:
    value = float(raw_value)
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _read_positive_float(name: str, default: float) -> float:
    return _parse_positive_float(name, os.getenv(name, str(default)))


def _read_positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _read_bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _validate_release_cors_origins(origins: tuple[str, ...]) -> None:
    if not origins or any(not origin for origin in origins):
        raise ValueError("release mode requires explicit CORS_ORIGINS")
    if len(set(origins)) != len(origins):
        raise ValueError("release mode requires unique CORS_ORIGINS")
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("release CORS_ORIGINS must be valid HTTP(S) origins") from exc
        hostname = parsed.hostname
        if (
            parsed.scheme not in {"http", "https"}
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or "*" in origin
        ):
            raise ValueError("release CORS_ORIGINS must be valid HTTP(S) origins")
        is_loopback = hostname.lower() == "localhost"
        try:
            is_loopback = is_loopback or ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            pass
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
            raise ValueError(
                "release CORS_ORIGINS must use HTTPS except for loopback origins"
            )


def _read_csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


def _read_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(choices))}")
    return value


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    log_level: str
    demo_mode: bool
    goong_api_key: str | None
    redis_url: str | None
    redis_connect_timeout_s: float
    redis_command_timeout_s: float
    api_rate_limit_read_per_min: int
    api_rate_limit_write_per_min: int
    database_url: str
    database_connect_timeout_s: int
    database_statement_timeout_ms: int
    catalog_storage: str
    planned_arrivals_storage: str
    realtime_telemetry_storage: str
    journey_storage: str
    realtime_telemetry_max_age_s: float
    realtime_telemetry_max_future_skew_s: float
    catalog_source_max_age_s: float | None
    occupancy_forecast_cache_ttl_s: int
    telemetry_ingest_api_key: str | None
    planned_arrival_admin_api_key: str | None
    incident_review_api_key: str | None
    journey_token_signing_key: str | None
    oidc_issuer: str | None
    oidc_audience: str | None
    oidc_jwks_url: str | None
    realtime_poll_interval_s: float
    occupancy_history_storage: str
    replan_deviation_threshold_m: float
    replan_min_interval_min: float
    journey_token_ttl_days: int
    data_dir: Path
    model_artifact_path: Path
    model_preprocessor_path: Path
    model_meta_path: Path
    wait_scoring_cap_min: float
    routing_timeout_s: float
    osrm_base_url: str
    recommend_max_detour_min: float
    recommend_max_wait_min: float
    recommend_max_charge_min: float
    recommend_soc_risk_buffer: float
    recommend_candidate_corridor_m: float
    recommend_max_candidates: int
    cors_origins: tuple[str, ...]

    def required_data_paths(self) -> tuple[Path, ...]:
        return (
            self.data_dir / "static" / "stations.geojson",
            self.data_dir / "static" / "vehicles.json",
            self.data_dir / "runtime" / "station_status.json",
            self.data_dir / "runtime" / "planned_arrivals.json",
            self.data_dir / "demo" / "demo_events.json",
            self.data_dir / "demo" / "demo_scenarios.json",
            self.data_dir / "demo" / "queue_assumptions.json",
            self.data_dir / "routes" / "route_base_direct.json",
            self.data_dir / "routes" / "route_via_lavida.json",
            self.data_dir / "routes" / "route_via_deutsches_haus.json",
        )


def load_settings() -> Settings:
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    production_like = app_env in {"production", "prod", "staging"}
    key = os.getenv("GOONG_API_KEY", "").strip() or None
    telemetry_key = os.getenv("TELEMETRY_INGEST_API_KEY", "").strip() or None
    planned_arrival_admin_key = (
        os.getenv("PLANNED_ARRIVAL_ADMIN_API_KEY", "").strip() or None
    )
    incident_review_key = os.getenv("INCIDENT_REVIEW_API_KEY", "").strip() or None
    journey_token_signing_key = (
        os.getenv("JOURNEY_TOKEN_SIGNING_KEY", "").strip() or None
    )
    oidc_issuer = os.getenv("OIDC_ISSUER", "").strip() or None
    oidc_audience = os.getenv("OIDC_AUDIENCE", "").strip() or None
    oidc_jwks_url = os.getenv("OIDC_JWKS_URL", "").strip() or None
    catalog_source_max_age_raw = os.getenv("CATALOG_SOURCE_MAX_AGE_S", "").strip()
    return Settings(
        app_name="Smart EV Journey API",
        app_env=app_env,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        demo_mode=_read_bool("DEMO_MODE", not production_like),
        goong_api_key=key,
        redis_url=os.getenv("REDIS_URL", "").strip() or None,
        redis_connect_timeout_s=_read_positive_float("REDIS_CONNECT_TIMEOUT_S", 2),
        redis_command_timeout_s=_read_positive_float("REDIS_COMMAND_TIMEOUT_S", 3),
        api_rate_limit_read_per_min=_read_positive_int("API_RATE_LIMIT_READ_PER_MIN", 120),
        api_rate_limit_write_per_min=_read_positive_int("API_RATE_LIMIT_WRITE_PER_MIN", 30),
        database_url=os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://smart_ev:smart_ev@127.0.0.1:5433/smart_ev_data",
        ),
        database_connect_timeout_s=_read_positive_int("DATABASE_CONNECT_TIMEOUT_S", 5),
        database_statement_timeout_ms=_read_positive_int(
            "DATABASE_STATEMENT_TIMEOUT_MS", 15000
        ),
        catalog_storage=_read_choice(
            "CATALOG_STORAGE", "memory", {"database", "memory"}
        ),
        planned_arrivals_storage=_read_choice(
            "PLANNED_ARRIVALS_STORAGE", "memory", {"database", "memory"}
        ),
        realtime_telemetry_storage=_read_choice(
            "REALTIME_TELEMETRY_STORAGE", "memory", {"database", "memory"}
        ),
        journey_storage=_read_choice(
            "JOURNEY_STORAGE", "memory", {"database", "memory"}
        ),
        realtime_telemetry_max_age_s=_read_positive_float(
            "REALTIME_TELEMETRY_MAX_AGE_S", 300
        ),
        realtime_telemetry_max_future_skew_s=_read_positive_float(
            "REALTIME_TELEMETRY_MAX_FUTURE_SKEW_S", 60
        ),
        catalog_source_max_age_s=(
            _parse_positive_float(
                "CATALOG_SOURCE_MAX_AGE_S", catalog_source_max_age_raw
            )
            if catalog_source_max_age_raw
            else None
        ),
        occupancy_forecast_cache_ttl_s=_read_positive_int(
            "OCCUPANCY_FORECAST_CACHE_TTL_S", 300
        ),
        telemetry_ingest_api_key=telemetry_key,
        planned_arrival_admin_api_key=planned_arrival_admin_key,
        incident_review_api_key=incident_review_key,
        journey_token_signing_key=journey_token_signing_key,
        oidc_issuer=oidc_issuer,
        oidc_audience=oidc_audience,
        oidc_jwks_url=oidc_jwks_url,
        realtime_poll_interval_s=_read_positive_float(
            "REALTIME_POLL_INTERVAL_S", 15
        ),
        occupancy_history_storage=_read_choice(
            "OCCUPANCY_HISTORY_STORAGE", "memory", {"database", "memory"}
        ),
        replan_deviation_threshold_m=_read_positive_float(
            "REPLAN_DEVIATION_THRESHOLD_M", 500
        ),
        replan_min_interval_min=_read_positive_float("REPLAN_MIN_INTERVAL_MIN", 10),
        journey_token_ttl_days=_read_positive_int("JOURNEY_TOKEN_TTL_DAYS", 30),
        data_dir=_resolve_from_root(os.getenv("DATA_DIR", "data")),
        model_artifact_path=_resolve_from_root(
            os.getenv("MODEL_ARTIFACT_PATH", "ml/artifacts/occupancy_model.joblib")
        ),
        model_preprocessor_path=_resolve_from_root(
            os.getenv(
                "MODEL_PREPROCESSOR_PATH",
                "ml/artifacts/occupancy_preprocessor.joblib",
            )
        ),
        model_meta_path=_resolve_from_root(
            os.getenv("MODEL_META_PATH", "ml/artifacts/occupancy_model_meta.json")
        ),
        wait_scoring_cap_min=_read_positive_float("WAIT_SCORING_CAP_MIN", 120),
        routing_timeout_s=_read_positive_float("ROUTING_TIMEOUT_S", 8),
        osrm_base_url=os.getenv(
            "OSRM_BASE_URL", "https://router.project-osrm.org"
        ).strip().rstrip("/"),
        recommend_max_detour_min=_read_positive_float(
            "RECOMMEND_MAX_DETOUR_MIN", 30
        ),
        recommend_max_wait_min=_read_positive_float("RECOMMEND_MAX_WAIT_MIN", 120),
        recommend_max_charge_min=_read_positive_float(
            "RECOMMEND_MAX_CHARGE_MIN", 90
        ),
        recommend_soc_risk_buffer=_read_positive_float(
            "RECOMMEND_SOC_RISK_BUFFER", 0.20
        ),
        recommend_candidate_corridor_m=_read_positive_float(
            "RECOMMEND_CANDIDATE_CORRIDOR_M", 5_000
        ),
        recommend_max_candidates=_read_bounded_int(
            "RECOMMEND_MAX_CANDIDATES", 50, minimum=1, maximum=500
        ),
        cors_origins=_read_csv("CORS_ORIGINS", "http://127.0.0.1:5173"),
    )


def validate_release_settings(settings: Settings) -> None:
    """Reject release startup when operational state would be process-local."""
    if settings.app_env.lower() in {"production", "prod", "staging"} and settings.demo_mode:
        raise ValueError("DEMO_MODE must be false when APP_ENV is production or staging")
    if settings.demo_mode:
        return

    _validate_release_cors_origins(settings.cors_origins)

    storage_modes = {
        "CATALOG_STORAGE": settings.catalog_storage,
        "PLANNED_ARRIVALS_STORAGE": settings.planned_arrivals_storage,
        "REALTIME_TELEMETRY_STORAGE": settings.realtime_telemetry_storage,
        "JOURNEY_STORAGE": settings.journey_storage,
        "OCCUPANCY_HISTORY_STORAGE": settings.occupancy_history_storage,
    }
    memory_backed = [name for name, mode in storage_modes.items() if mode != "database"]
    if memory_backed:
        raise ValueError(
            "release mode requires database storage for: " + ", ".join(memory_backed)
        )
    api_keys = {
        "TELEMETRY_INGEST_API_KEY": settings.telemetry_ingest_api_key,
        "PLANNED_ARRIVAL_ADMIN_API_KEY": settings.planned_arrival_admin_api_key,
        "INCIDENT_REVIEW_API_KEY": settings.incident_review_api_key,
    }
    for name, value in api_keys.items():
        if value is None or len(value) < 32:
            raise ValueError(f"release mode requires a 32-character {name}")
    if len(set(api_keys.values())) != len(api_keys):
        raise ValueError("release mode requires distinct API keys")
    if (
        settings.journey_token_signing_key is None
        or len(settings.journey_token_signing_key) < 32
    ):
        raise ValueError("release mode requires a 32-character JOURNEY_TOKEN_SIGNING_KEY")
    if settings.redis_url is None:
        raise ValueError("release mode requires REDIS_URL for rate limiting and realtime events")
    try:
        osrm_url = urlsplit(settings.osrm_base_url)
        _ = osrm_url.port
    except ValueError as exc:
        raise ValueError("OSRM_BASE_URL must be a valid HTTPS URL") from exc
    if (
        osrm_url.scheme != "https"
        or not osrm_url.hostname
        or osrm_url.username
        or osrm_url.password
        or osrm_url.query
        or osrm_url.fragment
    ):
        raise ValueError("OSRM_BASE_URL must be a valid HTTPS URL")
    if osrm_url.hostname.lower() == "router.project-osrm.org":
        raise ValueError(
            "release mode requires an operator-managed OSRM endpoint, not the public demo service"
        )
    oidc_values = {
        "OIDC_ISSUER": settings.oidc_issuer,
        "OIDC_AUDIENCE": settings.oidc_audience,
        "OIDC_JWKS_URL": settings.oidc_jwks_url,
    }
    missing_oidc = [name for name, value in oidc_values.items() if not value]
    if missing_oidc:
        raise ValueError("release mode requires OIDC settings: " + ", ".join(missing_oidc))
    for name, value in (
        ("OIDC_ISSUER", settings.oidc_issuer),
        ("OIDC_JWKS_URL", settings.oidc_jwks_url),
    ):
        if value is None:
            continue
        parsed = urlsplit(value)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError(f"{name} must be a valid HTTPS URL") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"{name} must be a valid HTTPS URL")
    if settings.goong_api_key is None:
        raise ValueError("release mode requires GOONG_API_KEY for geocoding")
    if settings.catalog_source_max_age_s is None:
        raise ValueError(
            "release mode requires an approved CATALOG_SOURCE_MAX_AGE_S threshold"
        )
