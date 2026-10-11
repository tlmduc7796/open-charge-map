"""Transactional writes for live station state (station occupancy and per-port status)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api_v1_models import PortStatusUpdate, StationOccupancyUpdate

OCCUPANCY_BUCKET_MINUTES = 5


def occupancy_bucket(reported_at: datetime) -> datetime:
    """Start (UTC) of the five-minute bucket that contains `reported_at`."""
    moment = reported_at.astimezone(UTC)
    return moment.replace(
        minute=(moment.minute // OCCUPANCY_BUCKET_MINUTES) * OCCUPANCY_BUCKET_MINUTES,
        second=0,
        microsecond=0,
    )


def ensure_occupancy_partition(connection: Any, month: date) -> None:
    """Create the month partition of `station_occupancy_5m` so rows do not land in DEFAULT.

    Best effort: if the DEFAULT partition already holds rows of that month the creation fails
    (inside a savepoint, so the caller's transaction survives) and rows go to DEFAULT as before.
    """
    try:
        with connection.begin_nested():
            connection.execute(
                text(
                    "SELECT public.ensure_month_partition("
                    "'public.station_occupancy_5m'::regclass, CAST(:month AS date))"
                ),
                {"month": month},
            )
    except SQLAlchemyError:
        pass


class DatabaseStationStateRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._partition_months: set[date] = set()

    def record_occupancy(self, updates: tuple[StationOccupancyUpdate, ...]) -> int:
        """Upsert the number of ports in use per station into its 5-minute bucket.

        The latest bucket of a station is its current status (view `station_status_current`).
        A later report in the same bucket overwrites it. Raises `KeyError` for an unknown or
        inactive station and `ValueError` when the counts do not fit the station's ports.
        """
        with self._engine.begin() as connection:
            for item in updates:
                station = connection.execute(
                    text(
                        "SELECT s.id::text AS id, count(p.id)::integer AS active_ports "
                        "FROM stations s "
                        "LEFT JOIN ports p ON p.station_id=s.id AND p.is_active "
                        "WHERE s.code=:station_id AND s.is_active "
                        "GROUP BY s.id"
                    ),
                    {"station_id": item.station_id},
                ).mappings().one_or_none()
                if station is None:
                    raise KeyError(item.station_id)
                total_ports = item.total_ports or station["active_ports"]
                if total_ports <= 0 or item.operational_ports > total_ports:
                    raise ValueError(
                        f"operationalPorts exceeds the {total_ports} ports of {item.station_id}"
                    )
                bucket_at = occupancy_bucket(item.reported_at)
                self._ensure_partition(connection, bucket_at)
                connection.execute(
                    text(
                        """
                        INSERT INTO station_occupancy_5m (
                            station_id, bucket_at, total_ports, operational_ports,
                            occupied_ports, queue_length
                        ) VALUES (
                            CAST(:station_id AS uuid), :bucket_at, :total_ports,
                            :operational_ports, :occupied_ports, :queue_length
                        )
                        ON CONFLICT (station_id, bucket_at) DO UPDATE SET
                            total_ports=EXCLUDED.total_ports,
                            operational_ports=EXCLUDED.operational_ports,
                            occupied_ports=EXCLUDED.occupied_ports,
                            queue_length=EXCLUDED.queue_length
                        """
                    ),
                    {
                        "station_id": station["id"],
                        "bucket_at": bucket_at,
                        "total_ports": total_ports,
                        "operational_ports": item.operational_ports,
                        "occupied_ports": item.occupied_ports,
                        "queue_length": item.queue_length,
                    },
                )
        return len(updates)

    def _ensure_partition(self, connection: Any, bucket_at: datetime) -> None:
        month = bucket_at.date().replace(day=1)
        if month not in self._partition_months:
            ensure_occupancy_partition(connection, month)
            self._partition_months.add(month)

    def update_batch(
        self, updates: tuple[PortStatusUpdate, ...], *, ingested_at: datetime
    ) -> tuple[int, int]:
        updated = 0
        ignored = 0
        with self._engine.begin() as connection:
            for item in updates:
                current = connection.execute(
                    text(
                        "SELECT ps.reported_at FROM ports p "
                        "LEFT JOIN port_status ps ON ps.port_id=p.id "
                        "WHERE p.id=:port_id AND p.is_active FOR UPDATE OF p"
                    ),
                    {"port_id": item.port_id},
                ).mappings().one_or_none()
                if current is None:
                    raise KeyError(item.port_id)
                if (
                    current["reported_at"] is not None
                    and current["reported_at"] >= item.reported_at
                ):
                    ignored += 1
                    continue
                parameters = {
                    "port_id": item.port_id,
                    "status": item.status,
                    "session_started_at": item.session_started_at,
                    "estimated_finish_at": item.estimated_finish_at,
                    "reported_at": item.reported_at,
                    "ingested_at": ingested_at,
                }
                connection.execute(
                    text(
                        """
                        INSERT INTO port_status (
                            port_id, status, session_started_at, estimated_finish_at,
                            reported_at, ingested_at
                        ) VALUES (
                            :port_id, CAST(:status AS port_status_value), :session_started_at,
                            :estimated_finish_at, :reported_at, :ingested_at
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
                            :port_id, CAST(:status AS port_status_value),
                            :reported_at, :ingested_at
                        )
                        """
                    ),
                    parameters,
                )
                updated += 1
        return updated, ignored

    def mark_stale(self, *, stale_before: datetime, changed_at: datetime) -> int:
        with self._engine.begin() as connection:
            rows = connection.execute(
                text(
                    """
                    WITH stale AS (
                        UPDATE port_status
                        SET status='unknown', session_started_at=NULL,
                            estimated_finish_at=NULL, ingested_at=:changed_at
                        WHERE reported_at < :stale_before
                          AND status <> 'unknown'
                        RETURNING port_id
                    )
                    INSERT INTO port_status_history (
                        port_id, status, changed_at, ingested_at
                    )
                    SELECT port_id, 'unknown', :changed_at, :changed_at
                    FROM stale
                    RETURNING port_id
                    """
                ),
                {"stale_before": stale_before, "changed_at": changed_at},
            ).scalars().all()
            return len(rows)
