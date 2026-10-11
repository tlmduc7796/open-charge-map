"""Historical average occupancy per station, day of week and five-minute slot."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import Engine, text

from backend.app.domain.far_horizon import smooth_profile

logger = logging.getLogger("smart_ev.profile")

# Ho Chi Minh City has no daylight saving time, so a fixed offset matches `Asia/Ho_Chi_Minh`.
LOCAL_TZ = timezone(timedelta(hours=7))
STEP_MINUTES = 5


def profile_cell(at: datetime) -> tuple[int, int]:
    """(day_of_week with Monday = 0, step 0..287) of `at` in local time."""
    if at.tzinfo is None:
        raise ValueError("at must include a timezone")
    local = at.astimezone(LOCAL_TZ)
    return local.weekday(), (local.hour * 60 + local.minute) // STEP_MINUTES


class DatabaseOccupancyProfileRepository:
    """In-memory copy of `station_occupancy_profile`, keyed by station code."""

    def __init__(self, engine: Engine, *, smoothing_strength: float = 2.0) -> None:
        self._engine = engine
        self._smoothing_strength = smoothing_strength
        self._cells: dict[tuple[str, int, int], float] = {}

    def __len__(self) -> int:
        return len(self._cells)

    def load(self) -> int:
        """Replace the cached cells with the table content; returns the number of cells."""
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT s.code, p.day_of_week, p.step_time, p.sample_count,
                           p.mean_ratio, p.station_mean_ratio
                    FROM station_occupancy_profile p
                    JOIN stations s ON s.id = p.station_id
                    """
                )
            ).mappings().all()
        self._cells = {
            (row["code"], int(row["day_of_week"]), int(row["step_time"])): smooth_profile(
                float(row["mean_ratio"]),
                int(row["sample_count"]),
                float(row["station_mean_ratio"]),
                strength=self._smoothing_strength,
            )
            for row in rows
        }
        return len(self._cells)

    def refresh(self, *, days: int = 30) -> int:
        """Recompute the table from `station_occupancy_5m` and reload the cache."""
        with self._engine.begin() as connection:
            connection.execute(
                text("SELECT public.refresh_station_occupancy_profile(:days)"),
                {"days": days},
            )
        return self.load()

    def ratio_at(self, station_id: str, at: datetime) -> float | None:
        day, step = profile_cell(at)
        return self._cells.get((station_id, day, step))


def load_or_refresh(repository: DatabaseOccupancyProfileRepository) -> int:
    """Load the profile at startup; build it from history when the table is still empty."""
    try:
        count = repository.load()
        if count == 0:
            count = repository.refresh()
    except Exception:
        logger.exception("occupancy_profile_unavailable")
        return 0
    logger.info("occupancy_profile_loaded cells=%d at=%s", count, datetime.now(UTC).isoformat())
    return count
