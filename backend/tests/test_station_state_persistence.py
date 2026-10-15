from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text

from backend.app.catalog_repository import (
    DatabaseStationRepository,
    DatabaseStationStatusRepository,
)
from backend.app.domain.runtime import RuntimeStateStore
from backend.app.main import app
from backend.app.station_state_repository import (
    DatabaseStationStateRepository,
    occupancy_bucket,
)

TEST_DATABASE_URL = os.getenv("BACKEND_TEST_DATABASE_URL")
STATION = "ST_VF_NGO_QUYEN"
HEADERS = {"X-API-Key": "integration-test-key"}


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def _use_database(engine, *, stale_after_s: float = 900) -> dict:
    """Point the shared app at the test database; returns the originals for restoring."""
    original = {
        key: getattr(app.state, key)
        for key in (
            "settings", "station_repository", "station_status_repository",
            "station_state_repository", "runtime_state",
        )
    }
    statuses = DatabaseStationStatusRepository(engine, stale_after_s=stale_after_s)
    app.state.settings = replace(app.state.settings, internal_api_key="integration-test-key")
    app.state.station_repository = DatabaseStationRepository(engine)
    app.state.station_status_repository = statuses
    app.state.station_state_repository = DatabaseStationStateRepository(engine)
    app.state.runtime_state = RuntimeStateStore(statuses)
    return original


def _delete_buckets(engine, *buckets: datetime) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM station_occupancy_5m WHERE bucket_at = ANY(:buckets) "
                "AND station_id = (SELECT id FROM stations WHERE code = :code)"
            ),
            {"buckets": list(buckets), "code": STATION},
        )


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_station_occupancy_drives_availability_ports_and_staleness() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with engine.connect() as connection:
        total = connection.scalar(
            text(
                "SELECT count(*) FROM ports p JOIN stations s ON s.id = p.station_id "
                "WHERE s.code = :code AND p.is_active"
            ),
            {"code": STATION},
        )
    assert total >= 4
    now = datetime.now(UTC)
    old = now - timedelta(minutes=30)
    original = _use_database(engine)

    def report(reported_at: datetime, *, operational: int, occupied: int, station=STATION):
        return asyncio.run(
            _request(
                "POST",
                "/api/v1/internal/station-occupancy",
                json={
                    "updates": [
                        {
                            "stationId": station,
                            "reportedAt": reported_at.isoformat(),
                            "operationalPorts": operational,
                            "occupiedPorts": occupied,
                        }
                    ]
                },
                headers=HEADERS,
            )
        )

    def available() -> int:
        response = asyncio.run(_request("GET", "/api/v1/stations/availability?offset=0"))
        item = next(i for i in response.json()["items"] if i["stationId"] == STATION)
        return item["availablePorts"]

    try:
        created = report(now, operational=total - 1, occupied=2)
        first = available()
        # A later report in the same bucket overwrites the earlier one.
        overwritten = report(now, operational=total - 1, occupied=3)
        second = available()
        ports = asyncio.run(_request("GET", f"/api/v1/stations/{STATION}/ports"))
        detail = asyncio.run(_request("GET", f"/api/v1/stations/{STATION}"))
        unknown_station = report(now, operational=1, occupied=0, station="ST_DOES_NOT_EXIST")
        too_many = report(now, operational=total + 5, occupied=0)
        with engine.connect() as connection:
            buckets = connection.scalar(
                text(
                    "SELECT count(*) FROM station_occupancy_5m WHERE bucket_at = :bucket "
                    "AND station_id = (SELECT id FROM stations WHERE code = :code)"
                ),
                {"bucket": occupancy_bucket(now), "code": STATION},
            )

        assert created.status_code == 200 and created.json()["updated"] == 1
        assert overwritten.status_code == 200
        assert buckets == 1
        assert first == (total - 1) - 2
        assert second == (total - 1) - 3
        listed = ports.json()
        assert len(listed) == total
        assert sum(item["status"] == "charging" for item in listed) == 3
        assert sum(item["status"] == "out_of_service" for item in listed) == 1
        assert all(item["dataSource"] == "inferred" for item in listed)
        assert sum(g["now"]["charging"] for g in detail.json()["byConnector"]) == 3
        assert unknown_station.status_code == 404
        assert too_many.status_code == 422

        # Only a bucket older than the stale window remains: the station is unknown.
        _delete_buckets(engine, occupancy_bucket(now))
        report(old, operational=total, occupied=1)
        app.state.station_status_repository = DatabaseStationStatusRepository(
            engine, stale_after_s=900
        )
        assert available() == 0
        ports_after = asyncio.run(_request("GET", f"/api/v1/stations/{STATION}/ports"))
        assert {item["status"] for item in ports_after.json()} == {"unknown"}
    finally:
        for key, value in original.items():
            setattr(app.state, key, value)
        _delete_buckets(engine, occupancy_bucket(now), occupancy_bucket(old))
        engine.dispose()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_port_status_report_is_kept_but_does_not_change_availability() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    port_id = str(uuid4())
    label = f"integration-{port_id[:8]}"
    with engine.begin() as connection:
        station_id = connection.scalar(
            text("SELECT id FROM stations WHERE code=:code"), {"code": STATION}
        )
        connection.execute(
            text(
                """
                INSERT INTO ports (id, station_id, connector_code, label, max_power_kw)
                VALUES (:port_id, :station_id, 'CCS2', :label, 50)
                """
            ),
            {"port_id": port_id, "station_id": station_id, "label": label},
        )

    original = _use_database(engine)
    # Older than the default stale window (900 s) so mark-stale has something to turn unknown.
    reported_at = datetime.now(UTC) - timedelta(minutes=20)
    payload = {
        "updates": [
            {"portId": port_id, "status": "available", "reportedAt": reported_at.isoformat()}
        ]
    }
    try:
        before = asyncio.run(_request("GET", "/api/v1/stations/availability?offset=0"))
        created = asyncio.run(
            _request("POST", "/api/v1/internal/port-status", json=payload, headers=HEADERS)
        )
        after = asyncio.run(_request("GET", "/api/v1/stations/availability?offset=0"))
        repeated = asyncio.run(
            _request("POST", "/api/v1/internal/port-status", json=payload, headers=HEADERS)
        )
        older = asyncio.run(
            _request(
                "POST", "/api/v1/internal/port-status",
                json={
                    "updates": [
                        {
                            **payload["updates"][0],
                            "status": "charging",
                            "reportedAt": (reported_at - timedelta(seconds=1)).isoformat(),
                        }
                    ]
                },
                headers=HEADERS,
            )
        )
        stale = asyncio.run(
            _request("POST", "/api/v1/internal/port-status/mark-stale", headers=HEADERS)
        )
        with engine.connect() as connection:
            history = connection.execute(
                text(
                    "SELECT status::text FROM port_status_history "
                    "WHERE port_id=CAST(:port_id AS uuid) ORDER BY changed_at"
                ),
                {"port_id": port_id},
            ).scalars().all()

        def station_item(response):
            return next(
                item for item in response.json()["items"] if item["stationId"] == STATION
            )

        assert created.status_code == 200 and created.json()["updated"] == 1
        before_item, after_item = station_item(before), station_item(after)
        assert after_item["availablePorts"] == before_item["availablePorts"]
        assert after_item["color"] == before_item["color"]
        assert repeated.json()["ignored"] == 1
        assert older.json()["ignored"] == 1
        assert stale.status_code == 200 and stale.json()["markedUnknown"] >= 1
        assert history == ["available", "unknown"]
    finally:
        for key, value in original.items():
            setattr(app.state, key, value)
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ports WHERE id=CAST(:port_id AS uuid)"),
                {"port_id": port_id},
            )
        engine.dispose()
