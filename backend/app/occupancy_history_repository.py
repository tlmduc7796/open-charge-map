"""Reads the newest contiguous occupancy window of a station for the forecasting model."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
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


class DatabaseOccupancyHistoryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def window(self, station_id: str) -> OccupancyWindow | None:
        """The last 12 five-minute buckets of the station with code `station_id`."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT o.bucket_at, o.total_ports, o.operational_ports, o.occupied_ports
                    FROM station_occupancy_5m o
                    JOIN stations s ON s.id = o.station_id
                    WHERE s.code = :code
                    ORDER BY o.bucket_at DESC
                    LIMIT :limit
                    """
                ),
                {"code": station_id, "limit": LOOKBACK_STEPS},
            ).mappings().all()
        return build_window(station_id, rows)
