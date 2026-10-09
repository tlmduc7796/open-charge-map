"""Database readiness checks shared by startup and the health endpoint."""

from __future__ import annotations

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

REQUIRED_DATABASE_REVISION = "0005_planned_arrivals"


def validate_database(engine: Engine) -> str:
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            connection.execute(text("SELECT 1 FROM station_status_current LIMIT 1"))
    except SQLAlchemyError as exc:
        raise RuntimeError(f"database is unavailable or not initialized: {exc}") from exc
    if revision != REQUIRED_DATABASE_REVISION:
        raise RuntimeError(
            "database schema revision mismatch: "
            f"expected {REQUIRED_DATABASE_REVISION}, got {revision or 'none'}"
        )
    return revision
