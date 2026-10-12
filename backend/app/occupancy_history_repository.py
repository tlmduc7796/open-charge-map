"""Reads the newest contiguous occupancy window of a station for the forecasting model."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text

from backend.app.domain.models import OccupancyWindow

LOOKBACK_STEPS = 12
BUCKET_MINUTES = 5


def build_window(
    station_id: str, rows: Sequence[Any], *, lookback: int = LOOKBACK_STEPS
) -> OccupancyWindow | None:
    """Window from bucket rows ordered newest first, or None when it is not usable.

    Mirrors `ml.features.valid_window_starts`: the buckets must be exactly five minutes apart
    and every one needs operational ports (otherwise its ratio is undefined).
    """
    if len(rows) < lookback:
        return None
    newest_first = list(rows[:lookback])
    step = timedelta(minutes=BUCKET_MINUTES)
    for newer, older in zip(newest_first, newest_first[1:], strict=False):
        if newer["bucket_at"] - older["bucket_at"] != step:
            return None
    lags: list[float] = []
    for row in newest_first:
        operational = int(row["operational_ports"])
        if operational <= 0:
            return None
        occupied = int(row["occupied_ports"])
        if not 0 <= occupied <= operational:
            return None
        lags.append(occupied / operational)
    newest = newest_first[0]
    return OccupancyWindow(
        station_id=station_id,
        lags=tuple(lags),
        t_last=newest["bucket_at"],
        total_ports=int(newest["total_ports"]),
    )


class DatabaseOccupancyRange:
    """Oldest and newest loaded occupancy bucket, re-read at most every `ttl_s` seconds."""

    def __init__(
        self,
        engine: Engine,
        ttl_s: float = 60.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._ttl_s = ttl_s
        self._monotonic = monotonic
        self._cached: tuple[datetime | None, datetime | None] = (None, None)
        self._read_at: float | None = None

    def __call__(self) -> tuple[datetime | None, datetime | None]:
        now = self._monotonic()
        if self._read_at is not None and now - self._read_at < self._ttl_s:
            return self._cached
        try:
            with self._engine.connect() as connection:
                row = connection.execute(
                    text("SELECT min(bucket_at) AS first, max(bucket_at) AS last "
                         "FROM station_occupancy_5m")
                ).mappings().one()
        except Exception:  # The range is informational; a failed read keeps the last value.
            return self._cached
        self._cached = (row["first"], row["last"])
        self._read_at = now
        return self._cached


class DatabaseOccupancyHistoryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def window(
        self, station_id: str, as_of: datetime | None = None
    ) -> OccupancyWindow | None:
        """The last 12 five-minute buckets of station `station_id` at or before `as_of`.

        `as_of` None means the newest buckets; passing a moment keeps later buckets out, which is
        what makes a forecast made "at T" independent of data recorded after T.
        """
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT o.bucket_at, o.total_ports, o.operational_ports, o.occupied_ports
                    FROM station_occupancy_5m o
                    JOIN stations s ON s.id = o.station_id
                    WHERE s.code = :code
                      AND (CAST(:as_of AS timestamptz) IS NULL OR o.bucket_at <= :as_of)
                    ORDER BY o.bucket_at DESC
                    LIMIT :limit
                    """
                ),
                {"code": station_id, "as_of": as_of, "limit": LOOKBACK_STEPS},
            ).mappings().all()
        return build_window(station_id, rows)
