"""Resolve the data-platform PostgreSQL URL without printing credentials."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.engine import URL


def release_database_url(env_file: Path) -> str:
    configured_url = os.environ.get("DATA_PLATFORM_DATABASE_URL")
    if configured_url:
        return configured_url
    if not env_file.is_file():
        raise FileNotFoundError(f"release environment file not found: {env_file}")

    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip("\"'")
    password = values.get("POSTGRES_PASSWORD")
    if not password:
        raise ValueError("POSTGRES_PASSWORD must be set in the release env file")
    raw_port = values.get("POSTGRES_HOST_PORT", "5433")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("POSTGRES_HOST_PORT must be an integer from 1 to 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("POSTGRES_HOST_PORT must be an integer from 1 to 65535")
    return URL.create(
        "postgresql+psycopg",
        username="smart_ev",
        password=password,
        host="127.0.0.1",
        port=port,
        database="smart_ev_data",
    ).render_as_string(hide_password=False)
