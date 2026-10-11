"""Periodic demo updates for station occupancy and default station forecasts."""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime

from sqlalchemy import Engine, text

from backend.app.station_state_repository import (
    ensure_occupancy_partition,
    occupancy_bucket,
)

DEFAULT_OCCUPANCY_RATIO = 0.5
PREDICTION_HORIZONS_MIN = (5, 10, 15, 20, 25, 30)
logger = logging.getLogger(__name__)


class DatabaseSimulationRepository:
    """Write simulated occupancy and fixed default forecasts to PostgreSQL."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def update_tick(self, *, changed_at: datetime | None = None) -> tuple[int, int]:
        """Draw a random number of busy ports per station and refresh default predictions.

        Like the real feed, only the count of ports in use is written (one
        `station_occupancy_5m` bucket per station); no per-port state exists.
        """
        tick_at = occupancy_bucket(changed_at or datetime.now(UTC))
        with self._engine.begin() as connection:
            supports_default_source = connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM pg_enum
                        WHERE enumtypid = 'public.prediction_source'::regtype
                          AND enumlabel = 'default'
                    )
                    """
                )
            ).scalar_one()
            prediction_source = "default" if supports_default_source else None
            if not supports_default_source:
                logger.warning(
                    "prediction_source_default_missing; storing default occupancy "
                    "without a source label until the database enum is updated"
                )

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

            for station in stations:
                for horizon_min in PREDICTION_HORIZONS_MIN:
                    connection.execute(
                        text(
                            """
                            INSERT INTO predictions (
                                station_id, horizon_min, run_at,
                                predicted_occupancy_ratio, operational_ports_at_run,
                                prediction_source, model_version
                            ) VALUES (
                                :station_id, :horizon_min, :tick_at,
                                CASE WHEN :operational_ports > 0
                                    THEN :occupancy_ratio ELSE NULL END,
                                :operational_ports,
                                CAST(:prediction_source AS prediction_source),
                                'fixed-default-v1'
                            )
                            ON CONFLICT (station_id, horizon_min) DO UPDATE SET
                                run_at=EXCLUDED.run_at,
                                predicted_occupancy_ratio=EXCLUDED.predicted_occupancy_ratio,
                                operational_ports_at_run=EXCLUDED.operational_ports_at_run,
                                prediction_source=EXCLUDED.prediction_source,
                                model_version=EXCLUDED.model_version
                            """
                        ),
                        {
                            "station_id": station["id"],
                            "horizon_min": horizon_min,
                            "tick_at": tick_at,
                            "operational_ports": station["operational_ports"],
                            "occupancy_ratio": DEFAULT_OCCUPANCY_RATIO,
                            "prediction_source": prediction_source,
                        },
                    )
        return stations_updated, len(stations) * len(PREDICTION_HORIZONS_MIN)
