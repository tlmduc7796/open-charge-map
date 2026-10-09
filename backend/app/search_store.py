"""Small TTL search-result store; Redis replaces this implementation in M5."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4

from backend.app.api_v1_models import (
    SearchRouteRequest,
    SearchRouteResponse,
    SearchStationsRequest,
    SearchStationsResponse,
)


@dataclass(frozen=True)
class SearchSnapshot:
    request: SearchRouteRequest | SearchStationsRequest
    response: SearchRouteResponse | SearchStationsResponse


class SearchResultStore:
    def __init__(self, ttl: timedelta = timedelta(minutes=10)) -> None:
        self._ttl = ttl
        self._items: dict[str, tuple[datetime, Any]] = {}
        self._lock = RLock()

    def put(self, result: Any, *, created_at: datetime | None = None) -> str:
        now = created_at or datetime.now(UTC)
        search_id = f"SRCH_{uuid4().hex[:16].upper()}"
        self.set(search_id, result, created_at=now)
        return search_id

    def set(
        self, search_id: str, result: Any, *, created_at: datetime | None = None
    ) -> None:
        now = created_at or datetime.now(UTC)
        with self._lock:
            self._items[search_id] = (now + self._ttl, result)

    def get(self, search_id: str, *, now: datetime | None = None) -> Any:
        evaluation_at = now or datetime.now(UTC)
        with self._lock:
            expires_at, result = self._items[search_id]
            if expires_at <= evaluation_at:
                del self._items[search_id]
                raise KeyError(search_id)
            return result


class SearchRateLimiter:
    def __init__(self, limit: int, window_s: float = 60) -> None:
        if limit <= 0 or window_s <= 0:
            raise ValueError("search rate limit and window must be positive")
        self._limit = limit
        self._window_s = window_s
        self._requests: dict[str, deque[float]] = {}
        self._lock = RLock()

    def allow(self, client_id: str, *, now: float | None = None) -> bool:
        evaluated_at = monotonic() if now is None else now
        with self._lock:
            recent = self._requests.setdefault(client_id, deque())
            while recent and recent[0] <= evaluated_at - self._window_s:
                recent.popleft()
            if len(recent) >= self._limit:
                return False
            recent.append(evaluated_at)
            return True
