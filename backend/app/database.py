"""Database readiness checks shared by startup and the health endpoint."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

REQUIRED_DATABASE_REVISION = "0020_path_safe_ids"


def create_database_engine(
    database_url: str,
    *,
    connect_timeout_s: int = 5,
    statement_timeout_ms: int = 15000,
) -> Engine:
    """Create a bounded PostgreSQL pool for API request workers."""
    if connect_timeout_s <= 0 or statement_timeout_ms <= 0:
        raise ValueError("database timeouts must be positive")
    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise ValueError("release database URL must use PostgreSQL")
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={
            "connect_timeout": connect_timeout_s,
            "options": f"-c statement_timeout={statement_timeout_ms}",
        },
    )


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
