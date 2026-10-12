"""Demo clock: a settable "now" that keeps running from the moment it was set.

Every part of the backend that needs the current time takes `DemoClock.now` (a callable), so one
process-wide offset moves status, forecasts, searches and trips together.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from threading import RLock

# Ho Chi Minh City has no daylight saving time, so a fixed offset matches `Asia/Ho_Chi_Minh`.
VIETNAM_TZ = timezone(timedelta(hours=7))


def parse_demo_time(value: str) -> datetime:
    """Parse `DEMO_NOW`: ISO-8601 with an offset, or "YYYY-MM-DD HH:MM[:SS]" in Vietnam time."""
    text = value.strip()
    if not text:
        raise ValueError("demo time must not be empty")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"demo time is not an ISO-8601 date-time: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=VIETNAM_TZ)
    return parsed.astimezone(UTC)


class DemoClock:
    """`now() = wall() + offset`; `set(at)` re-anchors so that now() == at at that instant."""

    def __init__(
        self,
        initial: datetime | None = None,
        *,
        wall: Callable[[], datetime] | None = None,
    ) -> None:
        self._wall = wall or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._offset = timedelta(0)
        if initial is not None:
            self.set(initial)

    def now(self) -> datetime:
        with self._lock:
            return self._wall() + self._offset

    def wall_now(self) -> datetime:
        return self._wall()

    @property
    def offset(self) -> timedelta:
        with self._lock:
            return self._offset

    @property
    def is_shifted(self) -> bool:
        return self.offset != timedelta(0)

    def set(self, at: datetime) -> datetime:
        """Make `now()` read `at` right now (and keep running); returns the new `now()`."""
        if at.tzinfo is None:
            raise ValueError("demo time must include a timezone")
        with self._lock:
            self._offset = at.astimezone(UTC) - self._wall()
            return self._wall() + self._offset

    def reset(self) -> datetime:
        """Follow the wall clock again."""
        with self._lock:
            self._offset = timedelta(0)
            return self._wall()
