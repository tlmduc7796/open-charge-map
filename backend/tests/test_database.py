from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from backend.app.database import REQUIRED_DATABASE_REVISION, validate_database


def _ready_engine(revision: str):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num text)"))
        connection.execute(
            text("INSERT INTO alembic_version VALUES (:revision)"),
            {"revision": revision},
        )
        connection.execute(text("CREATE TABLE station_status_source (id integer)"))
        connection.execute(
            text("CREATE VIEW station_status_current AS SELECT id FROM station_status_source")
        )
    return engine


def test_validate_database_accepts_required_revision() -> None:
    engine = _ready_engine(REQUIRED_DATABASE_REVISION)
    try:
        assert validate_database(engine) == REQUIRED_DATABASE_REVISION
    finally:
        engine.dispose()


def test_validate_database_rejects_stale_revision() -> None:
    engine = _ready_engine("0004_trips_config")
    try:
        with pytest.raises(RuntimeError, match="schema revision mismatch"):
            validate_database(engine)
    finally:
        engine.dispose()


def test_validate_database_reports_unavailable_database() -> None:
    class UnavailableEngine:
        def connect(self):
            raise OperationalError("connect", {}, RuntimeError("database is down"))

    with pytest.raises(RuntimeError, match="unavailable or not initialized"):
        validate_database(UnavailableEngine())  # type: ignore[arg-type]
