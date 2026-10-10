#!/usr/bin/env python3
"""Validate release secrets and render the Docker Compose configuration safely."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import shutil
import subprocess
import sys
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SECRETS = (
    "POSTGRES_PASSWORD",
    "REDIS_PASSWORD",
    "TELEMETRY_INGEST_API_KEY",
    "PLANNED_ARRIVAL_ADMIN_API_KEY",
    "INCIDENT_REVIEW_API_KEY",
    "JOURNEY_TOKEN_SIGNING_KEY",
)
REQUIRED_SETTINGS = (
    "ALERTMANAGER_WEBHOOK_URL_FILE",
    "GRAFANA_ADMIN_PASSWORD_FILE",
    "OIDC_ISSUER",
    "OIDC_AUDIENCE",
    "OIDC_JWKS_URL",
    "OIDC_CLIENT_ID",
    "CATALOG_SOURCE_MAX_AGE_S",
    "GOONG_API_KEY",
    "OSRM_BASE_URL",
    "OBSERVATION_RETENTION_DAYS",
    "RELEASE_WEB_HOST_BIND",
)
PASSWORDS = {"POSTGRES_PASSWORD", "REDIS_PASSWORD"}
KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
URL_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
COMPOSE_VARIABLE_PATTERN = re.compile(
    r"(?<!\$)\$(?:\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}|([A-Za-z_][A-Za-z0-9_]*))"
)
POSITIVE_FLOAT_SETTINGS = {
    "REDIS_CONNECT_TIMEOUT_S": 2,
    "REDIS_COMMAND_TIMEOUT_S": 3,
    "REALTIME_TELEMETRY_MAX_AGE_S": 300,
    "REALTIME_TELEMETRY_MAX_FUTURE_SKEW_S": 60,
    "REALTIME_POLL_INTERVAL_S": 15,
    "REPLAN_DEVIATION_THRESHOLD_M": 500,
    "REPLAN_MIN_INTERVAL_MIN": 10,
    "WAIT_SCORING_CAP_MIN": 120,
    "ROUTING_TIMEOUT_S": 8,
    "RECOMMEND_MAX_DETOUR_MIN": 30,
    "RECOMMEND_MAX_WAIT_MIN": 120,
    "RECOMMEND_MAX_CHARGE_MIN": 90,
    "RECOMMEND_SOC_RISK_BUFFER": 0.20,
    "RECOMMEND_CANDIDATE_CORRIDOR_M": 5_000,
}
POSITIVE_INT_SETTINGS = {
    "API_RATE_LIMIT_READ_PER_MIN": 120,
    "API_RATE_LIMIT_WRITE_PER_MIN": 30,
    "DATABASE_CONNECT_TIMEOUT_S": 5,
    "DATABASE_STATEMENT_TIMEOUT_MS": 15_000,
    "OCCUPANCY_FORECAST_CACHE_TTL_S": 300,
    "JOURNEY_TOKEN_TTL_DAYS": 30,
}
BOUNDED_INT_SETTINGS = {
    "POSTGRES_HOST_PORT": (5433, 1, 65535),
    "RECOMMEND_MAX_CANDIDATES": (50, 1, 500),
}


class PreflightError(ValueError):
    """A release environment file is invalid without exposing its values."""


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise PreflightError(f"invalid environment syntax at line {line_number}")
        name, value = line.split("=", 1)
        name = name.strip()
        if not KEY_PATTERN.fullmatch(name):
            raise PreflightError(f"invalid environment key at line {line_number}")
        if name in values:
            raise PreflightError(f"duplicate environment key: {name}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[name] = value
    return values


def effective_proxy_settings(
    values: dict[str, str],
    environment: dict[str, str] | None = None,
    compose_file: Path | None = None,
) -> dict[str, str]:
    """Include shell overrides only for variables Compose interpolates from YAML."""
    effective = dict(values)
    process_environment = os.environ if environment is None else environment
    config_path = compose_file or PROJECT_ROOT / "compose.release.yaml"
    compose_text = config_path.read_text(encoding="utf-8")
    interpolated_names = {
        braced_name or bare_name
        for braced_name, bare_name in COMPOSE_VARIABLE_PATTERN.findall(compose_text)
    }
    effective.update(
        {
            name: process_environment[name]
            for name in values
            if name in interpolated_names and name in process_environment
        }
    )
    return effective


def validate_environment(values: dict[str, str]) -> None:
    missing = [name for name in REQUIRED_SECRETS if not values.get(name, "").strip()]
    if missing:
        raise PreflightError("missing required secrets: " + ", ".join(missing))

    normalized: dict[str, str] = {}
    for name in REQUIRED_SECRETS:
        value = values[name].strip()
        if len(value) < 32 or any(character.isspace() for character in value):
            raise PreflightError(f"{name} must contain at least 32 non-whitespace characters")
        lowered = value.lower()
        if any(marker in lowered for marker in ("replace", "example", "change_me", "<", ">")):
            raise PreflightError(f"{name} still contains a sample placeholder")
        if name in PASSWORDS and not URL_SAFE_PATTERN.fullmatch(value):
            raise PreflightError(f"{name} must use URL-safe characters")
        normalized[name] = value
    if len(set(normalized.values())) != len(normalized):
        raise PreflightError("required secrets must be distinct")

    try:
        release_subnet = ipaddress.ip_network(
            values.get("RELEASE_DOCKER_SUBNET", "172.31.250.0/24"), strict=True
        )
        dynamic_range = ipaddress.ip_network(
            values.get("RELEASE_DOCKER_IP_RANGE", "172.31.250.128/25"), strict=True
        )
    except ValueError as exc:
        raise PreflightError(
            "RELEASE_DOCKER_SUBNET and RELEASE_DOCKER_IP_RANGE must be canonical subnets"
        ) from exc
    if (
        not isinstance(release_subnet, ipaddress.IPv4Network)
        or not release_subnet.is_private
        or release_subnet.is_loopback
        or release_subnet.prefixlen > 28
    ):
        raise PreflightError(
            "RELEASE_DOCKER_SUBNET must be a private IPv4 subnet with at least 16 addresses"
        )
    expected_proxy_ip = str(release_subnet.network_address + 2)
    if (
        not isinstance(dynamic_range, ipaddress.IPv4Network)
        or not dynamic_range.is_private
        or not dynamic_range.subnet_of(release_subnet)
    ):
        raise PreflightError(
            "RELEASE_DOCKER_IP_RANGE must be a private range inside RELEASE_DOCKER_SUBNET"
        )
    try:
        web_proxy_ip = ipaddress.ip_address(
            values.get("RELEASE_WEB_PROXY_IP", expected_proxy_ip)
        )
        forwarded_allow_ip = ipaddress.ip_address(
            values.get("FORWARDED_ALLOW_IPS", expected_proxy_ip)
        )
    except ValueError as exc:
        raise PreflightError(
            "RELEASE_WEB_PROXY_IP and FORWARDED_ALLOW_IPS must be IP addresses"
        ) from exc
    if str(web_proxy_ip) != expected_proxy_ip:
        raise PreflightError(
            "RELEASE_WEB_PROXY_IP must be the second usable address in RELEASE_DOCKER_SUBNET"
        )
    if web_proxy_ip in dynamic_range:
        raise PreflightError(
            "RELEASE_WEB_PROXY_IP must be outside RELEASE_DOCKER_IP_RANGE"
        )
    if forwarded_allow_ip != web_proxy_ip:
        raise PreflightError(
            "FORWARDED_ALLOW_IPS must exactly match RELEASE_WEB_PROXY_IP"
        )
    try:
        web_host_bind = ipaddress.ip_address(values["RELEASE_WEB_HOST_BIND"])
    except ValueError as exc:
        raise PreflightError(
            "RELEASE_WEB_HOST_BIND must be the loopback address 127.0.0.1"
        ) from exc
    if web_host_bind != ipaddress.ip_address("127.0.0.1"):
        raise PreflightError("RELEASE_WEB_HOST_BIND must be 127.0.0.1")

    for name, default in POSITIVE_FLOAT_SETTINGS.items():
        try:
            value = float(values.get(name, str(default)))
        except ValueError as exc:
            raise PreflightError(f"{name} must be a finite positive number") from exc
        if not isfinite(value) or value <= 0:
            raise PreflightError(f"{name} must be a finite positive number")
    for name, default in POSITIVE_INT_SETTINGS.items():
        try:
            value = int(values.get(name, str(default)))
        except ValueError as exc:
            raise PreflightError(f"{name} must be a positive integer") from exc
        if value <= 0:
            raise PreflightError(f"{name} must be a positive integer")
    for name, (default, minimum, maximum) in BOUNDED_INT_SETTINGS.items():
        try:
            value = int(values.get(name, str(default)))
        except ValueError as exc:
            raise PreflightError(
                f"{name} must be an integer between {minimum} and {maximum}"
            ) from exc
        if not minimum <= value <= maximum:
            raise PreflightError(f"{name} must be between {minimum} and {maximum}")

    missing_settings = [
        name for name in REQUIRED_SETTINGS if not values.get(name, "").strip()
    ]
    if missing_settings:
        raise PreflightError("missing required settings: " + ", ".join(missing_settings))

    try:
        catalog_source_max_age_s = float(values["CATALOG_SOURCE_MAX_AGE_S"])
    except ValueError as exc:
        raise PreflightError("CATALOG_SOURCE_MAX_AGE_S must be a finite positive number") from exc
    if not isfinite(catalog_source_max_age_s) or catalog_source_max_age_s <= 0:
        raise PreflightError("CATALOG_SOURCE_MAX_AGE_S must be a finite positive number")

    goong_key = values["GOONG_API_KEY"].strip()
    if any(character.isspace() for character in goong_key) or any(
        marker in goong_key.lower()
        for marker in ("example", "placeholder", "replace", "<", ">")
    ):
        raise PreflightError("GOONG_API_KEY must be a configured provider key")

    for name in ("OIDC_ISSUER", "OIDC_JWKS_URL", "OSRM_BASE_URL"):
        url = values[name].strip()
        try:
            parsed = urlsplit(url)
            _ = parsed.port
        except ValueError as exc:
            raise PreflightError(f"{name} must be an HTTPS URL") from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise PreflightError(f"{name} must be an HTTPS URL")
        if any(
            marker in url.lower()
            for marker in ("example.com", "example.net", "placeholder", "replace_me")
        ):
            raise PreflightError(f"{name} still contains an example placeholder")
    if any(character.isspace() for character in values["OIDC_AUDIENCE"].strip()):
        raise PreflightError("OIDC_AUDIENCE must not contain whitespace")
    oidc_scope = values.get("OIDC_SCOPE", "").strip() or (
        "openid profile email offline_access"
    )
    oidc_scope_values = oidc_scope.split()
    if not {"openid", "offline_access"}.issubset(oidc_scope_values):
        raise PreflightError("OIDC_SCOPE must include openid and offline_access")
    if len(oidc_scope_values) != len(set(oidc_scope_values)):
        raise PreflightError("OIDC_SCOPE must not contain duplicate scopes")
    if any(
        marker in values[name].lower()
        for name in ("OIDC_AUDIENCE", "OIDC_CLIENT_ID")
        for marker in ("example", "placeholder", "replace_me", "<", ">")
    ):
        raise PreflightError("OIDC_AUDIENCE and OIDC_CLIENT_ID must not contain placeholders")
    try:
        retention_days = int(values["OBSERVATION_RETENTION_DAYS"])
    except ValueError as exc:
        raise PreflightError("OBSERVATION_RETENTION_DAYS must be an integer") from exc
    if not 1 <= retention_days <= 36_500:
        raise PreflightError("OBSERVATION_RETENTION_DAYS must be between 1 and 36500")

    cors_origins = [origin.strip() for origin in values.get("CORS_ORIGINS", "").split(",")]
    if not cors_origins or any(not origin for origin in cors_origins):
        raise PreflightError("CORS_ORIGINS must contain at least one explicit origin")
    if len(set(cors_origins)) != len(cors_origins):
        raise PreflightError("CORS_ORIGINS must not contain duplicate origins")
    for origin in cors_origins:
        try:
            parsed = urlsplit(origin)
            _ = parsed.port
        except ValueError as exc:
            raise PreflightError(
                "CORS_ORIGINS must contain valid HTTP(S) origins"
            ) from exc
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
            raise PreflightError("CORS_ORIGINS must contain explicit HTTP(S) origins only")
        try:
            is_loopback = hostname.lower() == "localhost" or ipaddress.ip_address(
                hostname
            ).is_loopback
        except ValueError:
            is_loopback = hostname.lower() == "localhost"
        if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
            raise PreflightError(
                "CORS_ORIGINS must use HTTPS except for loopback origins"
            )


def validate_alert_webhook_file(values: dict[str, str], project_root: Path) -> None:
    configured_path = Path(values["ALERTMANAGER_WEBHOOK_URL_FILE"])
    webhook_path = (
        configured_path if configured_path.is_absolute() else project_root / configured_path
    )
    try:
        webhook_url = webhook_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise PreflightError("ALERTMANAGER_WEBHOOK_URL_FILE is missing or unreadable") from exc
    try:
        parsed = urlsplit(webhook_url)
        hostname = parsed.hostname
        _ = parsed.port  # Validate that a supplied port is numeric and within range.
    except ValueError as exc:
        raise PreflightError("alert notification webhook file must contain one HTTPS URL") from exc
    if (
        not webhook_url
        or any(character.isspace() for character in webhook_url)
        or parsed.scheme != "https"
        or not parsed.netloc
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise PreflightError("alert notification webhook file must contain one HTTPS URL")


def validate_grafana_password_file(values: dict[str, str], project_root: Path) -> None:
    configured_path = Path(values["GRAFANA_ADMIN_PASSWORD_FILE"])
    password_path = (
        configured_path if configured_path.is_absolute() else project_root / configured_path
    )
    try:
        password = password_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise PreflightError("GRAFANA_ADMIN_PASSWORD_FILE is missing or unreadable") from exc
    lowered = password.lower()
    if (
        len(password) < 32
        or any(character.isspace() for character in password)
        or any(marker in lowered for marker in ("replace", "example", "change_me", "<", ">"))
    ):
        raise PreflightError(
            "Grafana admin password file must contain at least 32 non-whitespace characters"
        )
    if password in {value.strip() for name, value in values.items() if name in REQUIRED_SECRETS}:
        raise PreflightError("Grafana admin password must be distinct from application secrets")


def check_compose(env_file: Path) -> bool:
    if shutil.which("docker") is None:
        return False
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(PROJECT_ROOT / "compose.release.yaml"),
        "config",
        "--quiet",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env.release",
        help="release environment file (values are never printed)",
    )
    args = parser.parse_args()
    env_file = args.env_file.resolve()
    try:
        values = effective_proxy_settings(
            parse_env_file(env_file), compose_file=PROJECT_ROOT / "compose.release.yaml"
        )
        validate_environment(values)
        validate_alert_webhook_file(values, PROJECT_ROOT)
        validate_grafana_password_file(values, PROJECT_ROOT)
    except (OSError, PreflightError) as exc:
        print(f"[FAIL] release_environment: {exc}")
        return 1
    print(
        "[PASS] release_environment: required secrets, explicit CORS origins, "
        "alert webhook, and Grafana credential are configured"
    )
    if not check_compose(env_file):
        print(
            "[FAIL] compose_config: Docker Compose is unavailable or rejected "
            "the release configuration"
        )
        return 1
    print("[PASS] compose_config: release configuration rendered successfully")
    print("\nRELEASE PREFLIGHT PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
