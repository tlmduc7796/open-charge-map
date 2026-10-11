"""Database readiness checks shared by startup and the health endpoint."""

from __future__ import annotations

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

# Tables and views the backend reads or writes; created by database/schema/*.sql.
REQUIRED_RELATIONS = (
    "app_config",
    "connector_types",
    "port_status",
    "port_status_history",
    "ports",
    "station_status_current",
    "stations",
    "trip_events",
    "trip_positions",
    "trips",
    "vehicle_connectors",
    "vehicle_models",
)


def validate_database(engine: Engine) -> str:
    """Fail fast when the database is unreachable or the schema has not been created."""
    try:
        with engine.connect() as connection:
            for relation in REQUIRED_RELATIONS:
                connection.execute(text(f"SELECT 1 FROM {relation} LIMIT 0"))
    except SQLAlchemyError as exc:
        raise RuntimeError(f"database is unavailable or not initialized: {exc}") from exc
    return "ready"
