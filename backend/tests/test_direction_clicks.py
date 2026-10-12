from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine, text

from backend.app.api_v1_models import ApiPoint
from backend.app.main import app
from backend.app.search_store import SearchRateLimiter
from backend.app.trip_repository import DatabaseTripRepository

TEST_DATABASE_URL = os.getenv("BACKEND_TEST_DATABASE_URL")

ORIGIN = {"lat": 10.7075, "lng": 106.705}
DESTINATION = {"lat": 10.806, "lng": 106.687}


def _body(**overrides) -> dict:
    body = {
        "mode": "route",
        "vehicleId": "EV_VF5_PLUS",
        "origin": ORIGIN,
        "destination": DESTINATION,
        "batteryPct": 35,
        "recommendedStationId": "ST_VF_FGW_Q7",
        "actualStationId": "ST_VF_LANDMARK_81",
    }
    body.update(overrides)
    return body


async def _post(body: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/api/v1/direction-clicks", json=body)


class _FakeRepository:
    def __init__(self, *, unknown: str | None = None) -> None:
        self.calls: list[dict] = []
        self._unknown = unknown

    def log_direction_click(self, **kwargs) -> str:
        if self._unknown is not None:
            raise KeyError(self._unknown)
        self.calls.append(kwargs)
        return "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def repository():
    """Swap in a fake repository (and a roomy rate limiter) for the app."""
    old_repository = app.state.trip_repository
    old_limiter = app.state.search_rate_limiter
    app.state.search_rate_limiter = SearchRateLimiter(limit=1000)
    fake = _FakeRepository()
    app.state.trip_repository = fake
    try:
        yield fake
    finally:
        app.state.trip_repository = old_repository
        app.state.search_rate_limiter = old_limiter


def test_route_click_is_logged_with_both_stations(repository) -> None:
    response = asyncio.run(_post(_body()))

    assert response.status_code == 201, response.text
    assert response.json()["id"] == "00000000-0000-0000-0000-000000000001"
    (call,) = repository.calls
    assert call["mode"] == "route"
    assert call["destination"] == ApiPoint(lat=10.806, lng=106.687)
    assert call["origin"] == ApiPoint(lat=10.7075, lng=106.705)
    assert call["battery_pct"] == 35
    assert call["recommended_station_id"] == "ST_VF_FGW_Q7"
    assert call["actual_station_id"] == "ST_VF_LANDMARK_81"
    assert call["created_at"].tzinfo is not None


def test_find_station_click_has_no_destination(repository) -> None:
    response = asyncio.run(_post(_body(mode="find_station", destination=None)))

    assert response.status_code == 201, response.text
    assert repository.calls[0]["destination"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"destination": None},  # route needs a destination
        {"mode": "find_station"},  # find_station must not carry one
        {"batteryPct": 101},
        {"actualStationId": ""},
    ],
)
def test_invalid_click_is_rejected(repository, overrides) -> None:
    response = asyncio.run(_post(_body(**overrides)))

    assert response.status_code == 422
    assert repository.calls == []


def test_unknown_station_is_404(repository) -> None:
    app.state.trip_repository = _FakeRepository(unknown="ST_DOES_NOT_EXIST")

    response = asyncio.run(_post(_body()))

    assert response.status_code == 404


def test_click_without_database_is_503(repository) -> None:
    app.state.trip_repository = None

    response = asyncio.run(_post(_body()))

    assert response.status_code == 503


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
@pytest.mark.parametrize("mode", ["route", "find_station"])
def test_click_row_is_persisted(mode: str) -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    trip_id = DatabaseTripRepository(engine).log_direction_click(
        mode=mode,
        vehicle_id="EV_VF5_PLUS",
        origin=ApiPoint(**ORIGIN),
        destination=ApiPoint(**DESTINATION) if mode == "route" else None,
        battery_pct=42.5,
        recommended_station_id="ST_VF_FGW_Q7",
        actual_station_id="ST_VF_LANDMARK_81",
        created_at=datetime(2026, 10, 11, 8, 0, tzinfo=UTC),
    )
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT t.mode, t.start_battery_pct, t.created_at,
                           ST_X(t.origin::geometry) AS origin_lng,
                           ST_Y(t.destination::geometry) AS destination_lat,
                           (t.destination IS NULL) AS no_destination,
                           r.code AS recommended, a.code AS actual
                    FROM trips t
                    JOIN stations r ON r.id = t.recommended_station_id
                    JOIN stations a ON a.id = t.actual_station_id
                    WHERE t.id = CAST(:id AS uuid)
                    """
                ),
                {"id": trip_id},
            ).mappings().one()
        assert row["mode"] == mode
        assert float(row["start_battery_pct"]) == pytest.approx(42.5)
        assert row["created_at"] == datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
        assert row["origin_lng"] == pytest.approx(ORIGIN["lng"])
        assert row["no_destination"] is (mode == "find_station")
        if mode == "route":
            assert row["destination_lat"] == pytest.approx(DESTINATION["lat"])
        assert row["recommended"] == "ST_VF_FGW_Q7"
        assert row["actual"] == "ST_VF_LANDMARK_81"
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM trips WHERE id = CAST(:id AS uuid)"), {"id": trip_id}
            )


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_unknown_station_is_not_written() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with pytest.raises(KeyError):
        DatabaseTripRepository(engine).log_direction_click(
            mode="find_station",
            vehicle_id="EV_VF5_PLUS",
            origin=ApiPoint(**ORIGIN),
            destination=None,
            battery_pct=50,
            recommended_station_id="ST_VF_FGW_Q7",
            actual_station_id="ST_DOES_NOT_EXIST",
            created_at=datetime.now(UTC),
        )
