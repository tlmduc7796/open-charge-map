from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.clock import VIETNAM_TZ, DemoClock, parse_demo_time
from backend.app.search_store import SearchResultStore


class Wall:
    """A wall clock the test advances by hand."""

    def __init__(self, start: datetime) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


WALL_START = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)


def test_unset_clock_follows_the_wall_clock() -> None:
    wall = Wall(WALL_START)
    clock = DemoClock(wall=wall)

    assert clock.now() == WALL_START
    assert clock.is_shifted is False
    wall.advance(minutes=3)
    assert clock.now() == WALL_START + timedelta(minutes=3)


def test_set_moment_keeps_running_instead_of_freezing() -> None:
    wall = Wall(WALL_START)
    clock = DemoClock(wall=wall)
    target = datetime(2026, 9, 15, 8, 0, 30, tzinfo=VIETNAM_TZ)

    assert clock.set(target) == target
    assert clock.is_shifted is True
    wall.advance(seconds=90)

    assert clock.now() == target + timedelta(seconds=90)
    assert clock.now().tzinfo is not None


def test_reset_returns_to_the_wall_clock() -> None:
    wall = Wall(WALL_START)
    clock = DemoClock(datetime(2026, 9, 1, tzinfo=UTC), wall=wall)

    assert clock.reset() == WALL_START
    assert clock.is_shifted is False
    assert clock.offset == timedelta(0)


def test_initial_moment_is_applied_at_construction() -> None:
    wall = Wall(WALL_START)
    initial = datetime(2026, 10, 11, 1, 0, tzinfo=UTC)

    assert DemoClock(initial, wall=wall).now() == initial


def test_naive_demo_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        DemoClock(wall=Wall(WALL_START)).set(datetime(2026, 9, 1, 8, 0))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-11 08:00", datetime(2026, 10, 11, 1, 0, tzinfo=UTC)),
        ("2026-10-11 08:00:45", datetime(2026, 10, 11, 1, 0, 45, tzinfo=UTC)),
        ("2026-10-11T08:00:00+07:00", datetime(2026, 10, 11, 1, 0, tzinfo=UTC)),
        ("2026-10-11T01:00:00Z", datetime(2026, 10, 11, 1, 0, tzinfo=UTC)),
    ],
)
def test_parse_demo_time(value: str, expected: datetime) -> None:
    assert parse_demo_time(value) == expected


@pytest.mark.parametrize("value", ["", "   ", "yesterday"])
def test_parse_demo_time_rejects_garbage(value: str) -> None:
    with pytest.raises(ValueError):
        parse_demo_time(value)


def test_search_result_expiry_uses_the_demo_clock() -> None:
    """A demo time in the past must not expire a result created a moment ago on the same clock."""
    wall = Wall(WALL_START)
    clock = DemoClock(datetime(2026, 9, 1, 8, 0, tzinfo=UTC), wall=wall)
    store = SearchResultStore(ttl=timedelta(minutes=10), clock=clock.now)

    search_id = store.put({"ok": True})
    wall.advance(minutes=9)
    assert store.get(search_id) == {"ok": True}

    wall.advance(minutes=2)
    with pytest.raises(KeyError):
        store.get(search_id)


def test_search_result_survives_moving_the_clock_backwards() -> None:
    wall = Wall(WALL_START)
    clock = DemoClock(wall=wall)
    store = SearchResultStore(ttl=timedelta(minutes=10), clock=clock.now)
    search_id = store.put("result")

    clock.set(datetime(2026, 9, 1, tzinfo=UTC))

    # Created at a later demo time than "now": still within the ttl window, so it is readable.
    assert store.get(search_id) == "result"
