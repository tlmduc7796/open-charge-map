"""Integration coverage for the Redis commands used by release workers."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from redis import Redis as SyncRedis
from redis.asyncio import Redis

from backend.app.api import station_status_events, upsert_station_telemetry
from backend.app.domain.models import OccupancyForecastResult, StationStatus
from backend.app.domain.realtime import ChargingPortTelemetry, StationTelemetrySnapshot
from backend.app.occupancy_forecast_cache import RedisOccupancyForecastCache
from backend.app.rate_limit import consume_request

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REDIS_INTEGRATION") != "1",
    reason="set RUN_REDIS_INTEGRATION=1 to test against a live Redis service",
)


def test_fixed_window_quota_is_shared_and_rolls_over() -> None:
    async def exercise() -> None:
        redis_url = os.environ["REDIS_URL"]
        first_worker = Redis.from_url(redis_url, decode_responses=False)
        second_worker = Redis.from_url(redis_url, decode_responses=False)
        identity = f"integration-{uuid.uuid4()}"
        try:
            first = await consume_request(
                first_worker, identity, "read", 2, now=1_800_000_000
            )
            second = await consume_request(
                second_worker, identity, "read", 2, now=1_800_000_001
            )
            limited = await consume_request(
                first_worker, identity, "read", 2, now=1_800_000_002
            )
            next_window = await consume_request(
                second_worker, identity, "read", 2, now=1_800_000_060
            )

            assert first[0:2] == (True, 1)
            assert 1 <= first[2] <= 60
            assert second[0:2] == (True, 0)
            assert limited[0:2] == (False, 0)
            assert next_window[0:2] == (True, 1)
        finally:
            await first_worker.aclose()
            await second_worker.aclose()

    asyncio.run(exercise())


def test_forecast_cache_round_trips_json_with_expiry() -> None:
    redis_url = os.environ["REDIS_URL"]
    client = SyncRedis.from_url(redis_url, decode_responses=True)
    cache_key = f"integration-occupancy-{uuid.uuid4()}"
    cache = RedisOccupancyForecastCache(client)
    result = OccupancyForecastResult(
        station_id="integration-station",
        requested_horizon_min=5,
        used_horizon_min=5,
        predicted_occupancy_ratio=0.5,
        predicted_occupied_ports=1.0,
        operational_ports=2,
        prediction_source="model",
        flags=(),
    )
    try:
        assert cache.get(cache_key) is None
        cache.set(cache_key, result, ttl_s=30)
        assert cache.get(cache_key) == result
        assert 1 <= client.ttl(cache_key) <= 30
    finally:
        client.delete(cache_key)
        client.close()


def test_sse_publishes_status_after_telemetry_notification() -> None:
    async def exercise() -> None:
        redis_url = os.environ["REDIS_URL"]
        subscriber = Redis.from_url(redis_url, decode_responses=True)
        publisher = SyncRedis.from_url(redis_url, decode_responses=True)
        station_id = f"redis-sse-{uuid.uuid4()}"

        class MutableRuntime:
            def __init__(self) -> None:
                self.status = _status(station_id, occupied_ports=0)

            def refresh(self) -> None:
                return None

            def all(self) -> tuple[StationStatus, ...]:
                return (self.status,)

        runtime_state = MutableRuntime()
        station = SimpleNamespace(
            station_id=station_id,
            properties=SimpleNamespace(
                total_ports=1,
                connectors=(SimpleNamespace(type="CCS2", count=1),),
            ),
        )

        class TelemetryStore:
            def upsert(self, snapshot: StationTelemetrySnapshot) -> StationTelemetrySnapshot:
                occupied = sum(port.state == "charging" for port in snapshot.ports)
                runtime_state.status = _status(station_id, occupied_ports=occupied)
                return snapshot

        settings = SimpleNamespace(
            demo_mode=True,
            telemetry_ingest_api_key=None,
            realtime_poll_interval_s=0.1,
            realtime_telemetry_max_age_s=300,
            realtime_telemetry_max_future_skew_s=60,
        )
        app = SimpleNamespace(
            state=SimpleNamespace(
                redis_client=subscriber,
                redis_sync_client=publisher,
                runtime_state=runtime_state,
                station_repository=SimpleNamespace(
                    all=lambda: (station,),
                    get=lambda _station_id: station,
                    filter_ids=lambda station_ids, **_kwargs: station_ids,
                ),
                realtime_telemetry_store=TelemetryStore(),
                settings=settings,
            )
        )

        async def connected() -> bool:
            return False

        request = SimpleNamespace(app=app, is_disconnected=connected)
        stream = await station_status_events(request, station_ids=[station_id])
        events = stream.body_iterator
        try:
            initial = await asyncio.wait_for(events.__anext__(), timeout=2)
            assert '"occupied_ports":0' in initial

            payload = StationTelemetrySnapshot(
                station_id=station_id,
                observed_at=datetime.now(UTC),
                ports=(
                    ChargingPortTelemetry(
                        port_id="port-1",
                        connector_types=("CCS2",),
                        state="charging",
                        session_id="session-1",
                    ),
                ),
                data_source="station_api",
            )
            await asyncio.to_thread(upsert_station_telemetry, station_id, payload, request)
            update = await asyncio.wait_for(events.__anext__(), timeout=2)
            assert '"occupied_ports":1' in update
        finally:
            await events.aclose()
            await subscriber.aclose()
            publisher.close()

    asyncio.run(exercise())


def _status(station_id: str, *, occupied_ports: int) -> StationStatus:
    return StationStatus(
        station_id=station_id,
        timestamp=datetime.now(UTC),
        total_ports=1,
        operational_ports=1,
        occupied_ports=occupied_ports,
        available_ports=1 - occupied_ports,
        offline_ports=0,
        occupancy_ratio=float(occupied_ports),
        queue_length=0,
        data_source="station_api",
    )
