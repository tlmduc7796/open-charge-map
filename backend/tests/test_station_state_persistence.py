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
from backend.app.station_state_repository import DatabaseStationStateRepository

TEST_DATABASE_URL = os.getenv("BACKEND_TEST_DATABASE_URL")


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_port_update_history_stale_and_availability() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    port_id = str(uuid4())
    label = f"integration-{port_id[:8]}"
    with engine.begin() as connection:
        station_id = connection.scalar(
            text("SELECT id FROM stations WHERE code='ST_EVO_LAVIDA_Q7'")
        )
        connection.execute(
            text(
                """
                INSERT INTO ports (id, station_id, connector_code, label,
                                   max_power_kw, data_origin)
                VALUES (:port_id, :station_id, 'CCS2', :label, 50, 'synthetic')
                """
            ),
            {"port_id": port_id, "station_id": station_id, "label": label},
        )

    original = {
        key: getattr(app.state, key)
        for key in (
            "settings", "station_repository", "station_status_repository",
            "station_state_repository", "runtime_state",
        )
    }
    statuses = DatabaseStationStatusRepository(engine)
    app.state.settings = replace(
        app.state.settings,
        internal_api_key="integration-test-key",
        station_status_stale_after_s=120,
    )
    app.state.station_repository = DatabaseStationRepository(engine)
    app.state.station_status_repository = statuses
    app.state.station_state_repository = DatabaseStationStateRepository(engine)
    app.state.runtime_state = RuntimeStateStore(statuses, app.state.domain_data.demo_events)
    reported_at = datetime.now(UTC) - timedelta(minutes=3)
    payload = {
        "updates": [
            {
                "portId": port_id,
                "status": "available",
                "reportedAt": reported_at.isoformat(),
            }
        ]
    }
    headers = {"X-API-Key": "integration-test-key"}
    try:
        before = asyncio.run(
            _request("GET", "/api/v1/stations/availability?offset=0")
        )
        created = asyncio.run(
            _request("POST", "/api/v1/internal/port-status", json=payload, headers=headers)
        )
        after = asyncio.run(
            _request("GET", "/api/v1/stations/availability?offset=0")
        )
        repeated = asyncio.run(
            _request("POST", "/api/v1/internal/port-status", json=payload, headers=headers)
        )
        older = asyncio.run(
            _request(
                "POST", "/api/v1/internal/port-status",
                json={
                    "updates": [
                        {
                            **payload["updates"][0],
                            "status": "charging",
                            "reportedAt": (
                                reported_at - timedelta(seconds=1)
                            ).isoformat(),
                        }
                    ]
                },
                headers=headers,
            )
        )
        stale = asyncio.run(
            _request("POST", "/api/v1/internal/port-status/mark-stale", headers=headers)
        )
        ports = asyncio.run(
            _request("GET", "/api/v1/stations/ST_EVO_LAVIDA_Q7/ports")
        )
        with engine.connect() as connection:
            history = connection.execute(
                text(
                    "SELECT status::text FROM port_status_history "
                    "WHERE port_id=CAST(:port_id AS uuid) ORDER BY changed_at"
                ),
                {"port_id": port_id},
            ).scalars().all()
        station_before = next(
            item for item in before.json()["items"]
            if item["stationId"] == "ST_EVO_LAVIDA_Q7"
        )
        station_after = next(
            item for item in after.json()["items"]
            if item["stationId"] == "ST_EVO_LAVIDA_Q7"
        )
        assert created.status_code == 200 and created.json()["updated"] == 1
        assert station_after["availablePorts"] == station_before["availablePorts"] + 1
        assert repeated.json()["ignored"] == 1
        assert older.json()["ignored"] == 1
        assert stale.status_code == 200 and stale.json()["markedUnknown"] >= 1
        assert next(item for item in ports.json() if item["id"] == port_id)["status"] == "unknown"
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
