from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from backend.app.database import create_database_engine
from backend.app.main import app, database_unavailable_handler


def test_database_engine_bounds_pool_and_postgres_waits(monkeypatch) -> None:
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr("backend.app.database.create_engine", fake_create_engine)

    engine = create_database_engine(
        "postgresql+psycopg://example/db",
        connect_timeout_s=4,
        statement_timeout_ms=9000,
    )

    assert engine is not None
    assert captured["pool_pre_ping"] is True
    assert captured["pool_timeout"] == 5
    assert captured["connect_args"] == {
        "connect_timeout": 4,
        "options": "-c statement_timeout=9000",
    }


@pytest.mark.parametrize(
    ("url", "connect_timeout_s", "statement_timeout_ms", "message"),
    [
        ("sqlite:///test.db", 5, 15000, "PostgreSQL"),
        ("postgresql+psycopg://example/db", 0, 15000, "positive"),
        ("postgresql+psycopg://example/db", 5, 0, "positive"),
    ],
)
def test_database_engine_rejects_unbounded_or_unsupported_settings(
    url: str, connect_timeout_s: int, statement_timeout_ms: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        create_database_engine(
            url,
            connect_timeout_s=connect_timeout_s,
            statement_timeout_ms=statement_timeout_ms,
        )


@pytest.mark.parametrize(
    "exception",
    [
        OperationalError("SELECT 1", {}, Exception("internal database detail")),
        SQLAlchemyTimeoutError("connection pool timeout"),
    ],
)
def test_database_unavailability_returns_generic_503(exception: Exception) -> None:
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-test"))
    response = asyncio.run(database_unavailable_handler(request, exception))

    assert response.status_code == 503
    assert response.body == (
        b'{"detail":"database operation unavailable",'
        b'"error_code":"DEPENDENCY_UNAVAILABLE"}'
    )
    assert type(exception) in app.exception_handlers
