"""Reads the newest contiguous occupancy window of a station for the forecasting model."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, text

from backend.app.domain.models import OccupancyWindow

if TYPE_CHECKING:
    import pandas as pd

LOOKBACK_STEPS = 12
BUCKET_MINUTES = 5


def build_window(
    station_id: str,
    rows: Sequence[Any],
    *,
    geo_features: Sequence[float],
    nearest_station_occupancy: float,
    lookback: int = LOOKBACK_STEPS,
) -> OccupancyWindow | None:
    """Window from bucket rows ordered newest first, or None when it is not usable.

    Mirrors `ml.features.valid_window_starts`: the buckets must be exactly five minutes apart
    and every one needs operational ports (otherwise its ratio is undefined). `geo_features`
    and `nearest_station_occupancy` are the caller's responsibility (see
    `DatabaseOccupancyHistoryRepository.window`) — this function only validates the lag window.
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
        geo_features=tuple(geo_features),
        nearest_station_occupancy=nearest_station_occupancy,
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
    """`geo_table`: `ml.geo_features.build_station_geo_table()` output (indexed by
    `stations.code`, same scheme as every domain `station_id`). A station missing from it has
    no static geo features to serve, so its window is unavailable (same as missing history).
    """

    def __init__(self, engine: Engine, geo_table: pd.DataFrame) -> None:
        # Lazy: keeps this module importable without pandas/numpy when geo features are unused.
        from ml.geo_features import GEO_COLUMNS, NEAREST_STATION_ID_COLUMN

        self._engine = engine
        self._geo_table = geo_table
        self._geo_columns = GEO_COLUMNS
        self._nearest_station_id_column = NEAREST_STATION_ID_COLUMN

    def window(
        self, station_id: str, as_of: datetime | None = None
    ) -> OccupancyWindow | None:
        """The last 12 five-minute buckets of station `station_id` at or before `as_of`.

        `as_of` None means the newest buckets; passing a moment keeps later buckets out, which is
        what makes a forecast made "at T" independent of data recorded after T.
        """
        if station_id not in self._geo_table.index:
            return None
        rows = self._rows(station_id, as_of, limit=LOOKBACK_STEPS)
        if len(rows) < LOOKBACK_STEPS:
            return None
        newest = rows[0]
        own_operational = int(newest["operational_ports"])
        own_ratio = (
            int(newest["occupied_ports"]) / own_operational if own_operational > 0 else 0.0
        )
        geo_row = self._geo_table.loc[station_id]
        nearest_id = geo_row[self._nearest_station_id_column]
        nearest_occupancy = self._neighbor_occupancy(
            nearest_id, newest["bucket_at"], fallback=own_ratio
        )
        return build_window(
            station_id,
            rows,
            geo_features=tuple(float(geo_row[name]) for name in self._geo_columns),
            nearest_station_occupancy=nearest_occupancy,
        )

    def _neighbor_occupancy(
        self, nearest_id: str, bucket_at: datetime, *, fallback: float
    ) -> float:
        """The nearest station's occupancy ratio at this exact `bucket_at`, or `fallback`."""
        if nearest_id not in self._geo_table.index:
            return fallback
        rows = self._rows(nearest_id, bucket_at, limit=1)
        if not rows or rows[0]["bucket_at"] != bucket_at:
            return fallback
        operational = int(rows[0]["operational_ports"])
        if operational <= 0:
            return fallback
        occupied = int(rows[0]["occupied_ports"])
        if not 0 <= occupied <= operational:
            return fallback
        return occupied / operational

    def _rows(
        self, station_id: str, as_of: datetime | None, *, limit: int
    ) -> list[Any]:
        with self._engine.connect() as connection:
            return (
                connection.execute(
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
                    {"code": station_id, "as_of": as_of, "limit": limit},
                )
                .mappings()
                .all()
            )
