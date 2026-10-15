from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta

import httpx
import pytest

from backend.app.main import app


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def _call(method: str, path: str, **kwargs) -> httpx.Response:
    return asyncio.run(_request(method, path, **kwargs))


@pytest.fixture(autouse=True)
def restore_clock() -> Iterator[None]:
    app.state.clock.reset()
    yield
    app.state.clock.reset()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_get_reports_the_demo_clock() -> None:
    response = _call("GET", "/api/v1/demo-clock")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "demoNow", "wallNow", "offsetS", "isShifted", "dataStart", "dataEnd", "writable",
    }
    assert body["isShifted"] is False
    assert body["writable"] is True
    assert abs((_parse(body["demoNow"]) - _parse(body["wallNow"])).total_seconds()) < 5


def test_put_moves_the_clock_and_it_keeps_running() -> None:
    response = _call(
        "PUT", "/api/v1/demo-clock", json={"demoNow": "2026-09-15T08:00:30+07:00"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["isShifted"] is True
    assert body["demoNow"].startswith("2026-09-15T01:00:3")
    # The app's own readers see the same moment: health and the clock agree.
    health = _call("GET", "/health").json()["serverTime"]
    assert 0 <= (_parse(health) - datetime.fromisoformat("2026-09-15T01:00:30+00:00")
                 ).total_seconds() < 5


def test_put_reset_returns_to_real_time() -> None:
    _call("PUT", "/api/v1/demo-clock", json={"demoNow": "2026-09-15T08:00:00+07:00"})

    body = _call("PUT", "/api/v1/demo-clock", json={"reset": True}).json()

    assert body["isShifted"] is False
    assert body["offsetS"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"reset": False},
        {"demoNow": "2026-09-15T08:00:00+07:00", "reset": True},
        {"demoNow": "2026-09-15T08:00:00"},
        {"demoNow": "not a time"},
    ],
)
def test_put_rejects_invalid_requests(payload: dict) -> None:
    response = _call("PUT", "/api/v1/demo-clock", json=payload)

    assert response.status_code in {400, 422}
    assert app.state.clock.is_shifted is False


def test_put_is_forbidden_when_the_clock_is_locked() -> None:
    original = app.state.settings
    app.state.settings = replace(original, demo_clock_writable=False)
    try:
        response = _call(
            "PUT", "/api/v1/demo-clock", json={"demoNow": "2026-09-15T08:00:00+07:00"}
        )
        reported = _call("GET", "/api/v1/demo-clock").json()["writable"]
    finally:
        app.state.settings = original

    assert response.status_code == 403
    assert reported is False
    assert app.state.clock.is_shifted is False


def test_availability_generated_at_follows_the_demo_clock() -> None:
    _call("PUT", "/api/v1/demo-clock", json={"demoNow": "2026-09-15T08:00:00+07:00"})

    body = _call("GET", "/api/v1/stations/availability?offset=0").json()

    generated = _parse(body["generatedAt"])
    expected = datetime.fromisoformat("2026-09-15T01:00:00+00:00")
    assert timedelta(0) <= generated - expected < timedelta(seconds=10)
