"""Transactional writes and port-level reads for live station state."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text

from backend.app.api_v1_models import PortStatusUpdate


class DatabaseStationStateRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
                            reported_at, ingested_at, data_origin
                        ) VALUES (
                            :port_id, CAST(:status AS port_status_value), :session_started_at,
                            :estimated_finish_at, :reported_at, :ingested_at, 'observed'
                        )
                        ON CONFLICT (port_id) DO UPDATE SET
                            status=EXCLUDED.status,
                            session_started_at=EXCLUDED.session_started_at,
                            estimated_finish_at=EXCLUDED.estimated_finish_at,
                            reported_at=EXCLUDED.reported_at,
                            ingested_at=EXCLUDED.ingested_at,
                            data_origin=EXCLUDED.data_origin
                        """
                    ),
                    parameters,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO port_status_history (
                            port_id, status, changed_at, ingested_at, data_origin
                        ) VALUES (
                            :port_id, CAST(:status AS port_status_value),
                            :reported_at, :ingested_at, 'observed'
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
                            estimated_finish_at=NULL, ingested_at=:changed_at,
                            data_origin='inferred'
                        WHERE reported_at < :stale_before
                          AND status <> 'unknown'
                          AND data_origin <> 'synthetic'
                        RETURNING port_id
                    )
                    INSERT INTO port_status_history (
                        port_id, status, changed_at, ingested_at, data_origin
                    )
                    SELECT port_id, 'unknown', :changed_at, :changed_at, 'inferred'
                    FROM stale
                    RETURNING port_id
                    """
                ),
                {"stale_before": stale_before, "changed_at": changed_at},
            ).scalars().all()
            return len(rows)

    def ports(self, station_id: str) -> tuple[dict[str, Any], ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT p.id::text AS id, p.label, p.connector_code,
                           COALESCE(ps.status::text, 'unknown') AS status,
                           ps.estimated_finish_at,
                           COALESCE(ps.reported_at, p.updated_at) AS updated_at
                    FROM stations s
                    JOIN ports p ON p.station_id=s.id AND p.is_active
                    LEFT JOIN port_status ps ON ps.port_id=p.id
                    WHERE s.code=:station_id AND s.is_active
                    ORDER BY p.label
                    """
                ),
                {"station_id": station_id},
            ).mappings().all()
        if not rows:
            raise KeyError(station_id)
        return tuple(dict(row) for row in rows)
