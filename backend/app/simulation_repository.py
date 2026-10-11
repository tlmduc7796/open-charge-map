"""Periodic demo updates for station occupancy (random busy ports, demo only)."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from sqlalchemy import Engine, text

from backend.app.station_state_repository import (
    ensure_occupancy_partition,
    occupancy_bucket,
)


class DatabaseSimulationRepository:
    """Write simulated occupancy to PostgreSQL; forecasts are written by `PredictionWriter`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def update_tick(self, *, changed_at: datetime | None = None) -> int:
        """Draw a random number of busy ports per station; returns stations updated.

        Like the real feed, only the count of ports in use is written (one
        `station_occupancy_5m` bucket per station); no per-port state exists.
        """
        tick_at = occupancy_bucket(changed_at or datetime.now(UTC))
        with self._engine.begin() as connection:
            stations = connection.execute(
                text(
                    """
                    SELECT s.id, count(p.id)::smallint AS operational_ports
                    FROM stations s
                    LEFT JOIN ports p ON p.station_id=s.id AND p.is_active
                    WHERE s.is_active
                    GROUP BY s.id
                    """
                )
            ).mappings().all()

            ensure_occupancy_partition(connection, tick_at.date().replace(day=1))
            stations_updated = 0
            for station in stations:
                total_ports = int(station["operational_ports"])
                if total_ports == 0:
                    continue
                connection.execute(
                    text(
                        """
                        INSERT INTO station_occupancy_5m (
                            station_id, bucket_at, total_ports, operational_ports,
                            occupied_ports
                        ) VALUES (
                            :station_id, :tick_at, :total_ports, :total_ports,
                            :occupied_ports
                        )
                        ON CONFLICT (station_id, bucket_at) DO UPDATE SET
                            total_ports=EXCLUDED.total_ports,
                            operational_ports=EXCLUDED.operational_ports,
                            occupied_ports=EXCLUDED.occupied_ports
                        """
                    ),
                    {
                        "station_id": station["id"],
                        "tick_at": tick_at,
                        "total_ports": total_ports,
                        "occupied_ports": random.randint(0, total_ports),
                    },
                )
                stations_updated += 1
        return stations_updated
