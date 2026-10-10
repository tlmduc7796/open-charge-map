import pytest

from backend.app.config import (
    PROJECT_ROOT,
    _validate_release_cors_origins,
    load_settings,
    validate_release_settings,
)


def test_default_paths_are_rooted_at_project(monkeypatch) -> None:
    for name in [
        "DATA_DIR",
        "APP_ENV",
        "DEMO_MODE",
        "MODEL_ARTIFACT_PATH",
        "MODEL_PREPROCESSOR_PATH",
        "MODEL_META_PATH",
        "WAIT_SCORING_CAP_MIN",
        "ROUTING_TIMEOUT_S",
        "OSRM_BASE_URL",
        "RECOMMEND_MAX_DETOUR_MIN",
        "RECOMMEND_MAX_WAIT_MIN",
        "RECOMMEND_MAX_CHARGE_MIN",
        "RECOMMEND_MAX_CANDIDATES",
        "RECOMMEND_SOC_RISK_BUFFER",
        "CORS_ORIGINS",
        "GOONG_API_KEY",
        "REDIS_URL",
        "REDIS_CONNECT_TIMEOUT_S",
        "REDIS_COMMAND_TIMEOUT_S",
        "API_RATE_LIMIT_READ_PER_MIN",
        "API_RATE_LIMIT_WRITE_PER_MIN",
        "REALTIME_TELEMETRY_MAX_FUTURE_SKEW_S",
        "DATABASE_CONNECT_TIMEOUT_S",
        "DATABASE_STATEMENT_TIMEOUT_MS",
    ]:
        monkeypatch.delenv(name, raising=False)
    settings = load_settings()

    assert settings.data_dir == PROJECT_ROOT / "data"
    assert settings.demo_mode is True
    assert settings.model_artifact_path == (
        PROJECT_ROOT / "ml" / "artifacts" / "occupancy_model.joblib"
    )
    assert settings.model_preprocessor_path == (
        PROJECT_ROOT / "ml" / "artifacts" / "occupancy_preprocessor.joblib"
    )
    assert settings.model_meta_path == (
        PROJECT_ROOT / "ml" / "artifacts" / "occupancy_model_meta.json"
    )
    assert settings.wait_scoring_cap_min == 120
    assert settings.routing_timeout_s == 8
    assert settings.osrm_base_url == "https://router.project-osrm.org"
    assert settings.recommend_max_detour_min == 30
    assert settings.recommend_max_wait_min == 120
    assert settings.recommend_max_charge_min == 90
    assert settings.recommend_max_candidates == 50
    assert settings.recommend_soc_risk_buffer == 0.20
    assert settings.cors_origins == ("http://127.0.0.1:5173",)
    assert settings.goong_api_key is None
    assert settings.redis_url is None
    assert settings.redis_connect_timeout_s == 2
    assert settings.redis_command_timeout_s == 3
    assert settings.api_rate_limit_read_per_min == 120
    assert settings.api_rate_limit_write_per_min == 30
    assert settings.realtime_telemetry_max_future_skew_s == 60
    assert settings.database_connect_timeout_s == 5
    assert settings.database_statement_timeout_ms == 15000


@pytest.mark.parametrize("value", ["0", "501", "-2"])
def test_recommendation_candidate_limit_is_bounded(monkeypatch, value: str) -> None:
    monkeypatch.setenv("RECOMMEND_MAX_CANDIDATES", value)

    with pytest.raises(
        ValueError,
        match="RECOMMEND_MAX_CANDIDATES must be between 1 and 500",
    ):
        load_settings()


@pytest.mark.parametrize("app_env", ["production", "prod", "staging"])
def test_release_environment_defaults_demo_mode_off(monkeypatch, app_env: str) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    for name in (
        "CATALOG_STORAGE",
        "PLANNED_ARRIVALS_STORAGE",
        "REALTIME_TELEMETRY_STORAGE",
        "JOURNEY_STORAGE",
        "OCCUPANCY_HISTORY_STORAGE",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()
    assert settings.demo_mode is False
    with pytest.raises(ValueError, match="CATALOG_STORAGE"):
        validate_release_settings(settings)


@pytest.mark.parametrize("origin", ["http://journey.example.com", "http://192.0.2.20"])
def test_release_settings_reject_insecure_external_cors_origins(
    monkeypatch, origin: str
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("CORS_ORIGINS", origin)

    with pytest.raises(ValueError, match="CORS_ORIGINS must use HTTPS"):
        validate_release_settings(load_settings())


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:8080", "http://127.0.0.1:5173", "http://[::1]:3000", "https://journey.example.com"],
)
def test_release_cors_allows_https_and_loopback_origins(origin: str) -> None:
    _validate_release_cors_origins((origin,))


@pytest.mark.parametrize("app_env", ["production", "prod", "staging"])
def test_release_environment_rejects_explicit_demo_mode(monkeypatch, app_env: str) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DEMO_MODE", "true")

    with pytest.raises(ValueError, match="DEMO_MODE must be false"):
        validate_release_settings(load_settings())


@pytest.mark.parametrize("value", ["0", "-1", "inf", "nan"])
def test_future_telemetry_skew_must_be_finite_and_positive(monkeypatch, value: str) -> None:
    monkeypatch.setenv("REALTIME_TELEMETRY_MAX_FUTURE_SKEW_S", value)

    with pytest.raises(ValueError, match="REALTIME_TELEMETRY_MAX_FUTURE_SKEW_S"):
        load_settings()


@pytest.mark.parametrize(
    "name", ["REDIS_CONNECT_TIMEOUT_S", "REDIS_COMMAND_TIMEOUT_S"]
)
@pytest.mark.parametrize("value", ["0", "-1", "inf", "nan"])
def test_redis_timeouts_must_be_finite_and_positive(monkeypatch, name, value) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="must be positive"):
        load_settings()


def test_required_phase_data_exists() -> None:
    missing = [path for path in load_settings().required_data_paths() if not path.is_file()]

    assert missing == []


def test_release_requires_database_backed_operational_storage(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("TELEMETRY_INGEST_API_KEY", "t" * 48)
    monkeypatch.setenv("PLANNED_ARRIVAL_ADMIN_API_KEY", "p" * 48)
    monkeypatch.setenv("INCIDENT_REVIEW_API_KEY", "i" * 48)
    monkeypatch.setenv("JOURNEY_TOKEN_SIGNING_KEY", "j" * 48)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    for name in (
        "CATALOG_STORAGE",
        "PLANNED_ARRIVALS_STORAGE",
        "REALTIME_TELEMETRY_STORAGE",
        "JOURNEY_STORAGE",
        "OCCUPANCY_HISTORY_STORAGE",
    ):
        monkeypatch.setenv(name, "database")
    monkeypatch.setenv("JOURNEY_STORAGE", "memory")

    with pytest.raises(ValueError, match="JOURNEY_STORAGE"):
        validate_release_settings(load_settings())


def test_release_accepts_persistent_storage_and_telemetry_key(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("CATALOG_SOURCE_MAX_AGE_S", str(30 * 24 * 60 * 60))
    monkeypatch.setenv("TELEMETRY_INGEST_API_KEY", "t" * 48)
    monkeypatch.setenv("PLANNED_ARRIVAL_ADMIN_API_KEY", "p" * 48)
    monkeypatch.setenv("INCIDENT_REVIEW_API_KEY", "i" * 48)
    monkeypatch.setenv("JOURNEY_TOKEN_SIGNING_KEY", "j" * 48)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.delenv("GOONG_API_KEY", raising=False)
    monkeypatch.setenv("OIDC_ISSUER", "https://identity.example.com/")
    monkeypatch.setenv("OIDC_AUDIENCE", "smart-ev-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://identity.example.com/keys")
    monkeypatch.setenv("OSRM_BASE_URL", "https://router.project-osrm.org")
    for name in (
        "CATALOG_STORAGE",
        "PLANNED_ARRIVALS_STORAGE",
        "REALTIME_TELEMETRY_STORAGE",
        "JOURNEY_STORAGE",
        "OCCUPANCY_HISTORY_STORAGE",
    ):
        monkeypatch.setenv(name, "database")

    with pytest.raises(ValueError, match="operator-managed OSRM endpoint"):
        validate_release_settings(load_settings())

    monkeypatch.setenv("OSRM_BASE_URL", "https://routing.internal.test")
    with pytest.raises(ValueError, match="GOONG_API_KEY"):
        validate_release_settings(load_settings())

    monkeypatch.setenv("GOONG_API_KEY", "configured-goong-provider-key")
    validate_release_settings(load_settings())
    monkeypatch.delenv("CATALOG_SOURCE_MAX_AGE_S")
    with pytest.raises(ValueError, match="CATALOG_SOURCE_MAX_AGE_S"):
        validate_release_settings(load_settings())


def test_release_requires_approved_catalog_source_freshness_threshold(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("CATALOG_SOURCE_MAX_AGE_S", "0")

    with pytest.raises(ValueError, match="CATALOG_SOURCE_MAX_AGE_S"):
        load_settings()


def test_release_requires_planned_arrival_admin_key(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("TELEMETRY_INGEST_API_KEY", "t" * 48)
    monkeypatch.delenv("PLANNED_ARRIVAL_ADMIN_API_KEY", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    for name in (
        "CATALOG_STORAGE",
        "PLANNED_ARRIVALS_STORAGE",
        "REALTIME_TELEMETRY_STORAGE",
        "JOURNEY_STORAGE",
        "OCCUPANCY_HISTORY_STORAGE",
    ):
        monkeypatch.setenv(name, "database")

    with pytest.raises(ValueError, match="PLANNED_ARRIVAL_ADMIN_API_KEY"):
        validate_release_settings(load_settings())


def test_release_requires_redis(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("TELEMETRY_INGEST_API_KEY", "t" * 48)
    monkeypatch.setenv("PLANNED_ARRIVAL_ADMIN_API_KEY", "p" * 48)
    monkeypatch.setenv("INCIDENT_REVIEW_API_KEY", "i" * 48)
    monkeypatch.setenv("JOURNEY_TOKEN_SIGNING_KEY", "j" * 48)
    monkeypatch.delenv("REDIS_URL", raising=False)
    for name in (
        "CATALOG_STORAGE",
        "PLANNED_ARRIVALS_STORAGE",
        "REALTIME_TELEMETRY_STORAGE",
        "JOURNEY_STORAGE",
        "OCCUPANCY_HISTORY_STORAGE",
    ):
        monkeypatch.setenv(name, "database")

    with pytest.raises(ValueError, match="REDIS_URL"):
        validate_release_settings(load_settings())


def test_release_requires_strong_distinct_operator_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("TELEMETRY_INGEST_API_KEY", "t" * 48)
    monkeypatch.setenv("PLANNED_ARRIVAL_ADMIN_API_KEY", "p" * 48)
    monkeypatch.setenv("INCIDENT_REVIEW_API_KEY", "t" * 48)
    monkeypatch.setenv("JOURNEY_TOKEN_SIGNING_KEY", "j" * 48)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    for name in (
        "CATALOG_STORAGE",
        "PLANNED_ARRIVALS_STORAGE",
        "REALTIME_TELEMETRY_STORAGE",
        "JOURNEY_STORAGE",
        "OCCUPANCY_HISTORY_STORAGE",
    ):
        monkeypatch.setenv(name, "database")

    with pytest.raises(ValueError, match="distinct API keys"):
        validate_release_settings(load_settings())
