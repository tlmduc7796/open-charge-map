import asyncio
from dataclasses import replace

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.app.main import app


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    async def eval(self, _script: str, _numkeys: int, key: str, _window: str) -> list[int]:
        self.values[key] = self.values.get(key, 0) + 1
        return [self.values[key], 60]


class UnavailableRedis:
    async def eval(self, _script: str, _numkeys: int, *_keys_and_args: str) -> list[int]:
        raise RedisConnectionError("redis unavailable")


def test_distributed_rate_limit_returns_429_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app.state,
        "settings",
        replace(app.state.settings, api_rate_limit_read_per_min=1),
    )
    monkeypatch.setattr(app.state, "redis_client", FakeRedis())

    async def request_twice() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/stations")
            second = await client.get("/stations")
            return first, second

    first, second = asyncio.run(request_twice())

    assert first.status_code == 200
    assert first.headers["x-ratelimit-remaining"] == "0"
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"


def test_health_probes_are_exempt_from_rate_limiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    monkeypatch.setattr(app.state, "redis_client", redis_client)

    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/live")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert redis_client.values == {}


def test_release_rate_limiter_fails_closed_when_redis_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app.state,
        "settings",
        replace(app.state.settings, demo_mode=False),
    )
    monkeypatch.setattr(app.state, "redis_client", UnavailableRedis())

    async def request_stations() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/stations")

    response = asyncio.run(request_stations())

    assert response.status_code == 503
    assert response.json()["detail"] == "distributed rate limiting is unavailable"
    assert response.json()["error_code"] == "DEPENDENCY_UNAVAILABLE"
