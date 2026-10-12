"""Reading occupancy "as of" a moment, on a real PostgreSQL.

Buckets are written in 2030, far from any loaded CSV month, so the tests neither depend on nor
disturb seeded history.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

from backend.app.api_v1_models import StationOccupancyUpdate
from backend.app.catalog_repository import DatabaseStationStatusRepository
from backend.app.clock import DemoClock
from backend.app.occupancy_history_repository import (
    DatabaseOccupancyHistoryRepository,
    DatabaseOccupancyRange,
)
from backend.app.profile_repository import DatabaseOccupancyProfileRepository
from backend.app.station_state_repository import DatabaseStationStateRepository

TEST_DATABASE_URL = os.getenv("BACKEND_TEST_DATABASE_URL")
STATION = "ST_VF_NGO_QUYEN"
T0 = datetime(2030, 3, 12, 3, 0, tzinfo=UTC)  # a Tuesday, 10:00 Vietnam time
REQUIRES_DATABASE = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="PostgreSQL test database required"
)


def _report(engine, occupied: list[int]) -> list[datetime]:
    """One bucket per entry, five minutes apart from T0; returns the bucket times."""
    buckets = [T0 + timedelta(minutes=5 * index) for index in range(len(occupied))]
    DatabaseStationStateRepository(engine).record_occupancy(
        tuple(
            StationOccupancyUpdate(
                station_id=STATION,
                reported_at=bucket,
                operational_ports=4,
                total_ports=4,
                occupied_ports=count,
            )
            for bucket, count in zip(buckets, occupied, strict=True)
        )
    )
    return buckets


def _cleanup(engine, buckets: list[datetime]) -> None:
    with engine.begin() as connection:
        params = {"buckets": buckets, "code": STATION}
        connection.execute(
            text(
                "DELETE FROM station_occupancy_5m WHERE bucket_at = ANY(:buckets) "
                "AND station_id = (SELECT id FROM stations WHERE code = :code)"
            ),
            params,
        )
        connection.execute(
            text(
                "DELETE FROM station_occupancy_profile "
                "WHERE station_id = (SELECT id FROM stations WHERE code = :code)"
            ),
            params,
        )


@REQUIRES_DATABASE
def test_status_is_the_newest_bucket_at_or_before_the_clock() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    buckets = _report(engine, [1, 2, 3])
    try:
        clock = DemoClock(T0 + timedelta(minutes=7, seconds=30))
        repository = DatabaseStationStatusRepository(
            engine, stale_after_s=900, clock=clock.now
        )

        mid = repository.get(STATION)
        assert mid.occupied_ports == 2  # the 03:05 bucket; 03:10 is still in the future
        assert mid.timestamp == buckets[1]
        assert mid.data_source == "database"

        clock.set(T0 + timedelta(minutes=12))
        assert repository.get(STATION).occupied_ports == 3
        assert next(s for s in repository.all() if s.station_id == STATION).occupied_ports == 3

        # The clock keeps running: nothing newer exists, so the reading ages into "unknown".
        clock.set(T0 + timedelta(minutes=10) + timedelta(seconds=901))
        assert repository.get(STATION).data_source == "unknown"

        # Before the first bucket there is nothing to report.
        clock.set(T0 - timedelta(days=400))
        assert repository.get(STATION).unknown_ports == repository.get(STATION).total_ports
    finally:
        _cleanup(engine, buckets)


@REQUIRES_DATABASE
def test_history_window_ends_at_the_requested_moment() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    buckets = _report(engine, [1] * 10 + [2] * 6)
    try:
        history = DatabaseOccupancyHistoryRepository(engine)

        newest = history.window(STATION)
        assert newest is not None and newest.t_last == buckets[-1]

        earlier = history.window(STATION, as_of=buckets[13])
        assert earlier is not None
        assert earlier.t_last == buckets[13]
        # Buckets 13..2 newest first: the model never sees values recorded after the moment.
        assert earlier.lags == (0.5,) * 4 + (0.25,) * 8

        # Fewer than 12 buckets up to the moment: no usable window.
        assert history.window(STATION, as_of=buckets[5]) is None
    finally:
        _cleanup(engine, buckets)


@REQUIRES_DATABASE
def test_profile_only_averages_buckets_up_to_the_moment() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    buckets = _report(engine, [2] * 12 + [4])
    profile = DatabaseOccupancyProfileRepository(engine)
    last = buckets[-1]  # T0 + 60 min, the only bucket with 4/4
    try:
        profile.refresh(as_of=last - timedelta(minutes=5))
        assert profile.ratio_at(STATION, buckets[3]) is not None
        assert profile.ratio_at(STATION, last) is None  # recorded after the moment

        profile.refresh(as_of=last)
        assert profile.ratio_at(STATION, last) is not None
    finally:
        _cleanup(engine, buckets)


@REQUIRES_DATABASE
def test_data_range_reports_loaded_buckets() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    buckets = _report(engine, [1, 1])
    try:
        first, last = DatabaseOccupancyRange(engine, ttl_s=0)()

        assert first is not None and last is not None
        assert first <= buckets[0] and last >= buckets[-1]
    finally:
        _cleanup(engine, buckets)
