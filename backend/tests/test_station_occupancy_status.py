"""Station status from the station-level occupancy feed (no per-port state)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from backend.app.api_v1 import _apportion, infer_connector_statuses
from backend.app.api_v1_models import StationOccupancyUpdate
from backend.app.catalog_repository import _status_from_row
from backend.app.main import app
from backend.app.station_state_repository import occupancy_bucket

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


def _row(**overrides):
    row = {
        "code": "ST_TEST",
        "reported_at": NOW - timedelta(minutes=3),
        "observed_at": NOW - timedelta(minutes=3),
        "total_ports": 10,
        "operational_ports": 9,
        "occupied_ports": 4,
        "available_ports": 5,
        "offline_ports": 1,
        "unknown_ports": 0,
        "occupancy_ratio": 4 / 9,
        "queue_length": None,
        "avg_session_duration_min": None,
    }
    row.update(overrides)
    return row


def test_available_is_operational_minus_occupied() -> None:
    status = _status_from_row(_row(), stale_after_s=900, now=NOW)

    assert (status.operational_ports, status.occupied_ports, status.available_ports) == (9, 4, 5)
    assert status.offline_ports == 1
    assert status.unknown_ports == 0
    assert status.data_source == "database"


def test_station_without_a_bucket_is_unknown() -> None:
    status = _status_from_row(
        _row(
            observed_at=None,
            operational_ports=0,
            occupied_ports=0,
            available_ports=0,
            offline_ports=0,
            unknown_ports=10,
            occupancy_ratio=None,
        ),
        stale_after_s=900,
        now=NOW,
    )

    assert status.unknown_ports == status.total_ports == 10
    assert status.available_ports == 0
    assert status.data_source == "unknown"


def test_stale_bucket_makes_the_station_unknown() -> None:
    old = NOW - timedelta(seconds=901)
    stale = _status_from_row(_row(observed_at=old), stale_after_s=900, now=NOW)
    recent = _row(observed_at=NOW - timedelta(seconds=899))
    fresh = _status_from_row(recent, stale_after_s=900, now=NOW)
    unchecked = _status_from_row(_row(observed_at=old), stale_after_s=None, now=NOW)

    assert stale.unknown_ports == 10 and stale.available_ports == 0
    assert stale.data_source == "unknown"
    assert fresh.available_ports == 5
    assert unchecked.available_ports == 5


def test_apportion_keeps_totals_and_capacities() -> None:
    assert _apportion(6, [10, 2]) == [5, 1]
    assert _apportion(0, [3, 3]) == [0, 0]
    assert _apportion(99, [3, 3]) == [3, 3]
    for total in range(0, 13):
        parts = _apportion(total, [7, 3, 2])
        assert sum(parts) == total
        assert all(part <= size for part, size in zip(parts, [7, 3, 2], strict=True))


def test_inferred_ports_add_up_to_the_station_counts() -> None:
    result = infer_connector_statuses(
        [("CCS2", 10), ("TYPE2", 2)], occupied=6, offline=1, unknown=0
    )
    by_connector = {code: statuses for code, statuses in result}
    flat = [status for _, statuses in result for status in statuses]

    assert len(by_connector["CCS2"]) == 10 and len(by_connector["TYPE2"]) == 2
    assert flat.count("charging") == 6
    assert flat.count("out_of_service") == 1
    assert flat.count("available") == 5
    # Spread in proportion to size, not stacked on the first connector.
    assert by_connector["TYPE2"].count("charging") == 1


def test_small_groups_never_overflow() -> None:
    result = infer_connector_statuses([("A", 1), ("B", 1)], occupied=1, offline=1, unknown=0)

    assert sorted(len(statuses) for _, statuses in result) == [1, 1]
    flat = [status for _, statuses in result for status in statuses]
    assert sorted(flat) == ["charging", "out_of_service"]


def test_occupancy_update_validates_counts_and_timezone() -> None:
    ok = StationOccupancyUpdate.model_validate(
        {"stationId": "S", "reportedAt": "2026-10-12T09:03:00Z", "operationalPorts": 5,
         "occupiedPorts": 5}
    )
    assert ok.occupied_ports == 5

    for bad in (
        {"operationalPorts": 3, "occupiedPorts": 4},
        {"operationalPorts": 6, "occupiedPorts": 1, "totalPorts": 5},
        {"operationalPorts": 3, "occupiedPorts": 1, "reportedAt": "2026-10-12T09:03:00"},
    ):
        payload = {"stationId": "S", "reportedAt": "2026-10-12T09:03:00Z", **bad}
        with pytest.raises(ValidationError):
            StationOccupancyUpdate.model_validate(payload)


def test_occupancy_bucket_floors_to_five_minutes_in_utc() -> None:
    local = datetime.fromisoformat("2026-10-12T16:07:42+07:00")

    assert occupancy_bucket(local) == datetime(2026, 10, 12, 9, 5, tzinfo=UTC)


def test_internal_station_occupancy_requires_key_and_database() -> None:
    original = app.state.settings
    body = {
        "updates": [
            {
                "stationId": "ST_EVO_LAVIDA_Q7",
                "reportedAt": "2026-10-12T09:03:00Z",
                "operationalPorts": 2,
                "occupiedPorts": 1,
            }
        ]
    }

    async def post(headers):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/internal/station-occupancy", json=body, headers=headers
            )

    try:
        app.state.settings = replace(original, internal_api_key=None)
        unconfigured = asyncio.run(post({}))
        app.state.settings = replace(original, internal_api_key="test-secret")
        unauthorized = asyncio.run(post({"X-API-Key": "wrong"}))
        no_database = asyncio.run(post({"X-API-Key": "test-secret"}))
    finally:
        app.state.settings = original

    assert unconfigured.status_code == 503
    assert unauthorized.status_code == 401
    # Tests run in memory mode: there is no database to record into.
    assert no_database.status_code == 503
