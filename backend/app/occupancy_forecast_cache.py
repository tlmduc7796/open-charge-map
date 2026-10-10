"""Redis adapter for bounded occupancy forecast memoization."""

from __future__ import annotations

from redis import Redis

from backend.app.domain.models import OccupancyForecastResult


class RedisOccupancyForecastCache:
    def __init__(self, client: Redis) -> None:
        self._client = client

    def get(self, key: str) -> OccupancyForecastResult | None:
        value = self._client.get(key)
        if value is None:
            return None
        return OccupancyForecastResult.model_validate_json(value)

    def set(self, key: str, result: OccupancyForecastResult, ttl_s: int) -> None:
        self._client.setex(key, ttl_s, result.model_dump_json())
