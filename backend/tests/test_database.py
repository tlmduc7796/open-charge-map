from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from backend.app.database import REQUIRED_RELATIONS, validate_database


def _engine_with(relations: tuple[str, ...]):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for relation in relations:
            connection.execute(text(f"CREATE TABLE {relation} (id integer)"))
    return engine


def test_validate_database_accepts_complete_schema() -> None:
    engine = _engine_with(REQUIRED_RELATIONS)
    try:
        assert validate_database(engine) == "ready"
    finally:
        engine.dispose()


def test_validate_database_rejects_missing_relation() -> None:
    engine = _engine_with(tuple(name for name in REQUIRED_RELATIONS if name != "trips"))
    try:
        with pytest.raises(RuntimeError, match="unavailable or not initialized"):
            validate_database(engine)
    finally:
        engine.dispose()


def test_validate_database_reports_unavailable_database() -> None:
    class UnavailableEngine:
        def connect(self):
            raise OperationalError("connect", {}, RuntimeError("database is down"))

    with pytest.raises(RuntimeError, match="unavailable or not initialized"):
        validate_database(UnavailableEngine())  # type: ignore[arg-type]
