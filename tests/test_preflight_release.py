import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.preflight_release import (
    PreflightError,
    check_compose,
    effective_proxy_settings,
    parse_env_file,
    validate_alert_webhook_file,
    validate_environment,
    validate_grafana_password_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _valid_environment() -> dict[str, str]:
    return {
        "POSTGRES_PASSWORD": "a" * 64,
        "REDIS_PASSWORD": "b" * 64,
        "TELEMETRY_INGEST_API_KEY": "telemetry-" + "c" * 54,
        "PLANNED_ARRIVAL_ADMIN_API_KEY": "planned-" + "d" * 56,
        "INCIDENT_REVIEW_API_KEY": "incident-" + "f" * 54,
        "JOURNEY_TOKEN_SIGNING_KEY": "journey-signing-" + "e" * 48,
        "ALERTMANAGER_WEBHOOK_URL_FILE": ".secrets/alertmanager-webhook-url",
        "GRAFANA_ADMIN_PASSWORD_FILE": ".secrets/grafana-admin-password",
        "OIDC_ISSUER": "https://identity.test/",
        "OIDC_AUDIENCE": "smart-ev-api",
        "OIDC_JWKS_URL": "https://identity.test/.well-known/jwks.json",
        "OIDC_CLIENT_ID": "smart-ev-web",
        "GOONG_API_KEY": "goong-provider-key-for-tests",
        "OSRM_BASE_URL": "https://routing.test",
        "CATALOG_SOURCE_MAX_AGE_S": str(30 * 24 * 60 * 60),
        "OBSERVATION_RETENTION_DAYS": "90",
        "CORS_ORIGINS": "https://journey.example.com,https://admin.example.com",
        "RELEASE_DOCKER_SUBNET": "172.31.250.0/24",
        "RELEASE_DOCKER_IP_RANGE": "172.31.250.128/25",
        "RELEASE_WEB_PROXY_IP": "172.31.250.2",
        "FORWARDED_ALLOW_IPS": "172.31.250.2",
        "RELEASE_WEB_HOST_BIND": "127.0.0.1",
        "POSTGRES_HOST_PORT": "5433",
    }


def test_parse_env_file_handles_comments_quotes_and_export(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.release"
    env_file.write_text(
        "# comment\nexport API_KEY='quoted-value'\nPORT=8080 # inline comment\n",
        encoding="utf-8",
    )

    assert parse_env_file(env_file) == {"API_KEY": "quoted-value", "PORT": "8080"}


def test_parse_env_file_rejects_duplicate_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.release"
    env_file.write_text("API_KEY=first\nAPI_KEY=second\n", encoding="utf-8")

    with pytest.raises(PreflightError, match="duplicate"):
        parse_env_file(env_file)


def test_release_environment_requires_distinct_strong_secrets_and_explicit_origins() -> None:
    validate_environment(_valid_environment())

    invalid = _valid_environment()
    invalid["REDIS_PASSWORD"] = invalid["POSTGRES_PASSWORD"]
    with pytest.raises(PreflightError, match="distinct"):
        validate_environment(invalid)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REDIS_CONNECT_TIMEOUT_S", "0"),
        ("REDIS_COMMAND_TIMEOUT_S", "nan"),
        ("DATABASE_CONNECT_TIMEOUT_S", "inf"),
        ("DATABASE_STATEMENT_TIMEOUT_MS", "-1"),
        ("DATABASE_STATEMENT_TIMEOUT_MS", "1.5"),
        ("REDIS_COMMAND_TIMEOUT_S", "not-a-number"),
    ],
)
def test_release_environment_rejects_invalid_dependency_timeouts(
    name: str, value: str
) -> None:
    invalid = _valid_environment()
    invalid[name] = value

    with pytest.raises(PreflightError, match=name):
        validate_environment(invalid)


def test_release_environment_accepts_default_dependency_timeouts() -> None:
    validate_environment(_valid_environment())


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RELEASE_DOCKER_SUBNET", "8.8.8.0/24"),
        ("RELEASE_DOCKER_SUBNET", "172.31.250.1/24"),
        ("RELEASE_DOCKER_SUBNET", "172.31.250.0/29"),
        ("RELEASE_DOCKER_IP_RANGE", "172.31.250.0/25"),
        ("RELEASE_DOCKER_IP_RANGE", "172.31.251.0/24"),
        ("RELEASE_WEB_PROXY_IP", "172.31.250.3"),
        ("FORWARDED_ALLOW_IPS", "*"),
        ("FORWARDED_ALLOW_IPS", "172.31.250.3"),
        ("RELEASE_WEB_HOST_BIND", "0.0.0.0"),
        ("RELEASE_WEB_HOST_BIND", "192.168.1.20"),
        ("RELEASE_WEB_HOST_BIND", "not-an-ip"),
    ],
)
def test_release_environment_rejects_invalid_proxy_network_configuration(
    name: str, value: str
) -> None:
    values = _valid_environment()
    values[name] = value

    with pytest.raises(PreflightError, match=name):
        validate_environment(values)


def test_release_environment_accepts_exact_web_proxy_trust() -> None:
    values = _valid_environment()

    validate_environment(values)


def test_preflight_validates_shell_overrides_used_by_compose() -> None:
    values = _valid_environment()
    effective = effective_proxy_settings(values, {"FORWARDED_ALLOW_IPS": "*"})

    with pytest.raises(PreflightError, match="FORWARDED_ALLOW_IPS"):
        validate_environment(effective)


def test_preflight_validates_non_proxy_shell_overrides_used_by_compose() -> None:
    values = _valid_environment()
    effective = effective_proxy_settings(
        values,
        {
            "OIDC_ISSUER": "http://identity.test/",
            "TELEMETRY_INGEST_API_KEY": "shell-value-not-used-for-compose-interpolation",
        },
    )

    with pytest.raises(PreflightError, match="OIDC_ISSUER"):
        validate_environment(effective)
    assert effective["TELEMETRY_INGEST_API_KEY"] == values["TELEMETRY_INGEST_API_KEY"]


def test_preflight_validates_postgres_port_shell_override_used_by_compose() -> None:
    values = _valid_environment()
    effective = effective_proxy_settings(
        values, {"POSTGRES_HOST_PORT": "not-a-port"}
    )

    with pytest.raises(PreflightError, match="POSTGRES_HOST_PORT"):
        validate_environment(effective)


@pytest.mark.parametrize("value", ["0", "501", "-2", "1.5", "not-a-number"])
def test_release_environment_rejects_invalid_recommendation_candidate_limit(
    value: str,
) -> None:
    invalid = _valid_environment()
    invalid["RECOMMEND_MAX_CANDIDATES"] = value

    with pytest.raises(PreflightError, match="RECOMMEND_MAX_CANDIDATES"):
        validate_environment(invalid)


def test_release_environment_accepts_configured_recommendation_candidate_limit() -> None:
    values = _valid_environment()
    values["RECOMMEND_MAX_CANDIDATES"] = "250"

    validate_environment(values)


@pytest.mark.parametrize("value", ["0", "65536", "1.5", "not-a-port"])
def test_release_environment_rejects_invalid_postgres_host_port(value: str) -> None:
    invalid = _valid_environment()
    invalid["POSTGRES_HOST_PORT"] = value

    with pytest.raises(PreflightError, match="POSTGRES_HOST_PORT"):
        validate_environment(invalid)


def test_release_environment_accepts_configured_postgres_host_port() -> None:
    values = _valid_environment()
    values["POSTGRES_HOST_PORT"] = "5543"

    validate_environment(values)


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://example.com/path",
        "ftp://example.com",
        "https://example.com?x=1",
        "https://user:pass@example.com",
        "http://journey.example.com",
    ],
)
def test_release_environment_rejects_non_origin_cors_values(origin: str) -> None:
    invalid = _valid_environment()
    invalid["CORS_ORIGINS"] = origin

    with pytest.raises(PreflightError, match="CORS_ORIGINS"):
        validate_environment(invalid)


@pytest.mark.parametrize("origin", ["http://localhost:8080", "http://127.0.0.1:5173", "http://[::1]"])
def test_release_preflight_allows_loopback_cors_origins(origin: str) -> None:
    values = _valid_environment()
    values["CORS_ORIGINS"] = origin

    validate_environment(values)


def test_release_preflight_rejects_duplicate_cors_origins() -> None:
    values = _valid_environment()
    values["CORS_ORIGINS"] = "https://journey.example.com,https://journey.example.com"

    with pytest.raises(PreflightError, match="duplicate origins"):
        validate_environment(values)


def test_release_environment_rejects_short_or_sample_secrets() -> None:
    invalid = _valid_environment()
    invalid["POSTGRES_PASSWORD"] = "this-is-a-sample-password-please-replace"

    with pytest.raises(PreflightError, match="placeholder"):
        validate_environment(invalid)


def test_release_environment_requires_https_oidc_endpoints() -> None:
    invalid = _valid_environment()
    invalid["OIDC_JWKS_URL"] = "http://identity.example.com/keys"
    with pytest.raises(PreflightError, match="OIDC_JWKS_URL"):
        validate_environment(invalid)

    invalid = _valid_environment()
    invalid["OIDC_ISSUER"] = "https://identity.example.com/"
    with pytest.raises(PreflightError, match="placeholder"):
        validate_environment(invalid)


@pytest.mark.parametrize(
    "scope",
    ["profile email offline_access", "openid profile email", "openid openid offline_access"],
)
def test_release_environment_requires_valid_oidc_scopes(scope: str) -> None:
    invalid = _valid_environment()
    invalid["OIDC_SCOPE"] = scope

    with pytest.raises(PreflightError, match="OIDC_SCOPE"):
        validate_environment(invalid)


def test_release_environment_requires_explicit_https_osrm_endpoint() -> None:
    invalid = _valid_environment()
    invalid["OSRM_BASE_URL"] = "http://routing.internal.test"
    with pytest.raises(PreflightError, match="OSRM_BASE_URL"):
        validate_environment(invalid)

    invalid["OSRM_BASE_URL"] = "https://routing.example.net"
    with pytest.raises(PreflightError, match="placeholder"):
        validate_environment(invalid)


def test_release_environment_requires_configured_goong_key() -> None:
    invalid = _valid_environment()
    invalid["GOONG_API_KEY"] = "replace-me-with-the-real-key"

    with pytest.raises(PreflightError, match="GOONG_API_KEY"):
        validate_environment(invalid)


@pytest.mark.parametrize("days", ["0", "36501", "unknown"])
def test_release_environment_requires_explicit_valid_retention_period(days: str) -> None:
    invalid = _valid_environment()
    invalid["OBSERVATION_RETENTION_DAYS"] = days

    with pytest.raises(PreflightError, match="OBSERVATION_RETENTION_DAYS"):
        validate_environment(invalid)


@pytest.mark.parametrize("max_age", ["0", "-1", "inf", "unknown"])
def test_release_environment_requires_approved_catalog_max_age(max_age: str) -> None:
    invalid = _valid_environment()
    invalid["CATALOG_SOURCE_MAX_AGE_S"] = max_age

    with pytest.raises(PreflightError, match="CATALOG_SOURCE_MAX_AGE_S"):
        validate_environment(invalid)


def test_alert_webhook_file_requires_https_and_does_not_print_its_value(
    tmp_path: Path, capsys
) -> None:
    webhook_file = tmp_path / "webhook.secret"
    webhook_file.write_text("https://alerts.example.com/secret-token\n", encoding="utf-8")
    values = {"ALERTMANAGER_WEBHOOK_URL_FILE": str(webhook_file)}

    validate_alert_webhook_file(values, tmp_path)
    assert capsys.readouterr().out == ""

    webhook_file.write_text("http://alerts.example.com/secret-token\n", encoding="utf-8")
    with pytest.raises(PreflightError, match="one HTTPS URL"):
        validate_alert_webhook_file(values, tmp_path)


def test_grafana_password_file_requires_long_secret_without_printing_value(
    tmp_path: Path, capsys
) -> None:
    password_file = tmp_path / "grafana-admin.secret"
    password_file.write_text("g" * 48 + "\n", encoding="utf-8")
    values = {"GRAFANA_ADMIN_PASSWORD_FILE": str(password_file)}

    validate_grafana_password_file(values, tmp_path)
    assert capsys.readouterr().out == ""

    password_file.write_text("short\n", encoding="utf-8")
    with pytest.raises(PreflightError, match="Grafana admin password file"):
        validate_grafana_password_file(values, tmp_path)

    password_file.write_text("a" * 64, encoding="utf-8")
    with pytest.raises(PreflightError, match="distinct"):
        validate_grafana_password_file(
            {**values, "POSTGRES_PASSWORD": "a" * 64}, tmp_path
        )


def test_compose_check_uses_quiet_config_without_printing_output(
    monkeypatch, tmp_path: Path
) -> None:
    env_file = tmp_path / ".env.release"
    env_file.write_text("POSTGRES_PASSWORD=secret-value", encoding="utf-8")
    invoked = {}

    def fake_run(command, **kwargs):
        invoked["command"] = command
        invoked["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("scripts.preflight_release.shutil.which", lambda _: "docker")
    monkeypatch.setattr("scripts.preflight_release.subprocess.run", fake_run)

    assert check_compose(env_file) is True
    assert invoked["command"][-2:] == ["config", "--quiet"]
    assert str(env_file) in invoked["command"]
    assert "secret-value" not in " ".join(invoked["command"])
    assert invoked["kwargs"]["capture_output"] is True


def test_release_migration_service_uses_alembic_project_directory() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "compose.release.yaml").read_text(encoding="utf-8")
    )

    assert compose["services"]["migrate"]["working_dir"] == "/app/data_platform"
    assert compose["services"]["migrate"]["command"][-1] == "head"
    assert compose["services"]["postgres"]["ports"] == [
        "127.0.0.1:${POSTGRES_HOST_PORT:-5433}:5432"
    ]
    assert compose["services"]["grafana"]["ports"] == [
        "127.0.0.1:${GRAFANA_HOST_PORT:-3000}:3000"
    ]
    assert compose["services"]["web"]["ports"] == [
        "${RELEASE_WEB_HOST_BIND:-127.0.0.1}:8080:8080"
    ]
    assert compose["services"]["api"]["environment"][
        "CATALOG_SOURCE_MAX_AGE_S"
    ].startswith("${")
    assert compose["services"]["api"]["environment"][
        "FORWARDED_ALLOW_IPS"
    ] == "${FORWARDED_ALLOW_IPS:-172.31.250.2}"
    assert compose["services"]["web"]["networks"]["default"][
        "ipv4_address"
    ] == "${RELEASE_WEB_PROXY_IP:-172.31.250.2}"
    assert compose["networks"]["default"]["ipam"]["config"][0][
        "subnet"
    ] == "${RELEASE_DOCKER_SUBNET:-172.31.250.0/24}"
    assert compose["networks"]["default"]["ipam"]["config"][0][
        "ip_range"
    ] == "${RELEASE_DOCKER_IP_RANGE:-172.31.250.128/25}"
    dockerfile = (PROJECT_ROOT / "Dockerfile.backend").read_text(encoding="utf-8")
    assert '"--forwarded-allow-ips", "*"' not in dockerfile


def test_nginx_bootstrap_exempts_only_authenticated_telemetry_ingest() -> None:
    nginx = (PROJECT_ROOT / "deploy" / "nginx.conf").read_text(encoding="utf-8")
    telemetry_start = nginx.index(
        "location ~ ^/api/realtime/stations/[^/]+/telemetry$"
    )
    general_api_start = nginx.index("location /api/", telemetry_start)
    telemetry_block = nginx[telemetry_start:general_api_start]
    general_api_block = nginx[general_api_start:nginx.index("location / {", general_api_start)]

    assert "rewrite ^/api(/.*)$ $1 break;" in telemetry_block
    assert "proxy_pass http://api:8000;" in telemetry_block
    assert "auth_request" not in telemetry_block
    assert "auth_request /_api_ready;" in general_api_block
    assert "proxy_intercept_errors on;" not in general_api_block
    assert "location = /api/metrics {\n        return 404;" in nginx
    assert "error_page 500 =503 @api_readiness_unavailable;" in nginx
    assert (
        "return 503 '{\"detail\":\"API is not ready\","
        "\"error_code\":\"DEPENDENCY_UNAVAILABLE\"}';" in nginx
    )


def test_release_retention_worker_waits_before_pruning_and_requires_policy() -> None:
    compose = yaml.safe_load(
        (PROJECT_ROOT / "compose.release.yaml").read_text(encoding="utf-8")
    )
    worker = compose["services"]["observation-retention"]

    assert "OBSERVATION_RETENTION_DAYS" in worker["environment"]
    assert worker["environment"]["OBSERVATION_RETENTION_DAYS"].startswith("${")
    assert "sleep 86400" in worker["command"][0]
    assert "--apply" in worker["command"][0]
    assert compose["services"]["grafana"]["environment"][
        "GF_SECURITY_ADMIN_PASSWORD__FILE"
    ] == "/run/secrets/grafana_admin_password"


def test_grafana_release_dashboard_is_valid_json_and_uses_bounded_metrics() -> None:
    import json

    dashboard = json.loads(
        (PROJECT_ROOT / "deploy/grafana/dashboards/smart-ev-release.json").read_text(
            encoding="utf-8"
        )
    )

    assert dashboard["uid"] == "smart-ev-release-ops"
    assert len(dashboard["panels"]) >= 6
    assert all(
        "station_id" not in target["expr"]
        for panel in dashboard["panels"]
        for target in panel["targets"]
    )
