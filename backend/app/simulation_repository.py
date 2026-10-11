"""Periodic demo updates for port state and default station forecasts."""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text

DEFAULT_OCCUPANCY_RATIO = 0.5
PREDICTION_HORIZONS_MIN = (5, 10, 15, 20, 25, 30)
logger = logging.getLogger(__name__)


class DatabaseSimulationRepository:
    """Write simulated port state and fixed default forecasts to PostgreSQL."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def update_tick(self, *, changed_at: datetime | None = None) -> tuple[int, int]:
        """Randomize active ports and refresh each station's default predictions."""
        tick_at = changed_at or datetime.now(UTC)
        ports_updated = 0
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

            ports = connection.execute(
                text("SELECT id FROM ports WHERE is_active ORDER BY id FOR UPDATE")
            ).scalars().all()
            for port_id in ports:
                charging = random.choice((False, True))
                status = "charging" if charging else "available"
                session_started_at = tick_at - timedelta(
                    minutes=random.randint(1, 45)
                ) if charging else None
                estimated_finish_at = tick_at + timedelta(
                    minutes=random.randint(5, 60)
                ) if charging else None
                parameters = {
                    "port_id": port_id,
                    "status": status,
                    "session_started_at": session_started_at,
                    "estimated_finish_at": estimated_finish_at,
                    "tick_at": tick_at,
                }
                connection.execute(
                    text(
                        """
                        INSERT INTO port_status (
                            port_id, status, session_started_at, estimated_finish_at,
                            reported_at, ingested_at
                        ) VALUES (
                            :port_id, CAST(:status AS port_status_value),
                            :session_started_at, :estimated_finish_at, :tick_at, :tick_at
                        )
                        ON CONFLICT (port_id) DO UPDATE SET
                            status=EXCLUDED.status,
                            session_started_at=EXCLUDED.session_started_at,
                            estimated_finish_at=EXCLUDED.estimated_finish_at,
                            reported_at=EXCLUDED.reported_at,
                            ingested_at=EXCLUDED.ingested_at
                        """
                    ),
                    parameters,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO port_status_history (
                            port_id, status, changed_at, ingested_at
                        ) VALUES (
                            :port_id, CAST(:status AS port_status_value), :tick_at, :tick_at
                        )
                        """
                    ),
                    parameters,
                )
                ports_updated += 1

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
        return ports_updated, len(stations) * len(PREDICTION_HORIZONS_MIN)
