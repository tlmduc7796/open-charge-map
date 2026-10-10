"""PostgreSQL history store for validated station telemetry snapshots."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine, text

from backend.app.domain.realtime import StationTelemetrySnapshot


class DatabaseRealtimeTelemetryStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _decode(value: Any) -> StationTelemetrySnapshot:
        if isinstance(value, str):
            value = json.loads(value)
        return StationTelemetrySnapshot.model_validate(value)

    def upsert(
        self, snapshot: StationTelemetrySnapshot
    ) -> StationTelemetrySnapshot:
        return self.upsert_with_change(snapshot)[0]

    def upsert_with_change(
        self, snapshot: StationTelemetrySnapshot
    ) -> tuple[StationTelemetrySnapshot, bool]:
        with self._engine.begin() as connection:
            station = connection.execute(
                text("SELECT id FROM stations WHERE code=:code FOR UPDATE"),
                {"code": snapshot.station_id},
            ).scalar_one_or_none()
            if station is None:
                raise KeyError(snapshot.station_id)

            existing = connection.execute(
                text(
                    "SELECT snapshot FROM station_telemetry_snapshots "
                    "WHERE station_id=:station_id AND observed_at=:observed_at"
                ),
                {"station_id": station, "observed_at": snapshot.observed_at},
            ).scalar_one_or_none()
            if existing is not None:
                if self._decode(existing) != snapshot:
                    raise ValueError(
                        "a different telemetry snapshot already exists at this timestamp"
                    )
                return snapshot, False

            latest = connection.execute(
                text(
                    "SELECT observed_at FROM station_telemetry_snapshots "
                    "WHERE station_id=:station_id "
                    "ORDER BY observed_at DESC LIMIT 1"
                ),
                {"station_id": station},
            ).scalar_one_or_none()
            if latest is not None and snapshot.observed_at < latest:
                raise ValueError("telemetry snapshot is older than the stored snapshot")

            inserted = connection.execute(
                text(
                    "INSERT INTO station_telemetry_snapshots "
                    "(station_id, observed_at, data_source, snapshot) "
                    "VALUES (:station_id, :observed_at, :data_source, CAST(:snapshot AS jsonb)) "
                    "ON CONFLICT (station_id, observed_at) DO NOTHING "
                    "RETURNING observed_at"
                ),
                {
                    "station_id": station,
                    "observed_at": snapshot.observed_at,
                    "data_source": snapshot.data_source,
                    "snapshot": snapshot.model_dump_json(),
                },
            ).scalar_one_or_none()
            changed = inserted is not None
            if inserted is None:
                existing = connection.execute(
                    text(
                        "SELECT snapshot FROM station_telemetry_snapshots "
                        "WHERE station_id=:station_id AND observed_at=:observed_at"
                    ),
                    {"station_id": station, "observed_at": snapshot.observed_at},
                ).scalar_one()
                if self._decode(existing) != snapshot:
                    raise ValueError(
                        "a different telemetry snapshot already exists at this timestamp"
                    )
            operational_ports = sum(port.is_operational for port in snapshot.ports)
            occupied_ports = sum(port.state == "charging" for port in snapshot.ports)
            connection.execute(
                text(
                    "INSERT INTO station_occupancy_5m "
                    "(station_id, bucket_at, total_ports, operational_ports, "
                    "occupied_ports, queue_length, data_origin) VALUES ("
                    ":station_id, date_bin(interval '5 minutes', :observed_at, "
                    "timestamptz '2000-01-01 00:00:00+00'), :total_ports, "
                    ":operational_ports, :occupied_ports, :queue_length, "
                    "CAST(:data_origin AS data_origin)) "
                    "ON CONFLICT (station_id, bucket_at, simulation_run_id) DO UPDATE SET "
                    "total_ports=EXCLUDED.total_ports, "
                    "operational_ports=EXCLUDED.operational_ports, "
                    "occupied_ports=EXCLUDED.occupied_ports, "
                    "queue_length=EXCLUDED.queue_length, "
                    "data_origin=EXCLUDED.data_origin "
                    "WHERE station_occupancy_5m.data_origin <> 'observed' "
                    "OR EXCLUDED.data_origin='observed'"
                ),
                {
                    "station_id": station,
                    "observed_at": snapshot.observed_at,
                    "total_ports": len(snapshot.ports),
                    "operational_ports": operational_ports,
                    "occupied_ports": occupied_ports,
                    "queue_length": (
                        len(snapshot.queue) if snapshot.queue is not None else None
                    ),
                    "data_origin": (
                        "synthetic" if snapshot.data_source == "simulated" else "observed"
                    ),
                },
            )
        return snapshot, changed

    def get(self, station_id: str) -> StationTelemetrySnapshot:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT sts.snapshot FROM station_telemetry_snapshots sts "
                    "JOIN stations s ON s.id=sts.station_id "
                    "WHERE s.code=:station_id "
                    "ORDER BY sts.observed_at DESC LIMIT 1"
                ),
                {"station_id": station_id},
            ).scalar_one_or_none()
        if row is None:
            raise KeyError(station_id)
        return self._decode(row)

    def all(self) -> tuple[StationTelemetrySnapshot, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT DISTINCT ON (s.code) sts.snapshot "
                    "FROM station_telemetry_snapshots sts "
                    "JOIN stations s ON s.id=sts.station_id "
                    "ORDER BY s.code, sts.observed_at DESC"
                )
            ).scalars()
            return tuple(self._decode(row) for row in rows)

    def get_many(self, station_ids: tuple[str, ...]) -> tuple[StationTelemetrySnapshot, ...]:
        if not station_ids:
            return ()
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT DISTINCT ON (s.code) sts.snapshot "
                    "FROM station_telemetry_snapshots sts "
                    "JOIN stations s ON s.id=sts.station_id "
                    "WHERE s.code = ANY(:station_ids) "
                    "ORDER BY s.code, sts.observed_at DESC"
                ),
                {"station_ids": list(station_ids)},
            ).scalars()
            return tuple(self._decode(row) for row in rows)

    def reset(self) -> None:
        """Clear demo-generated snapshots while retaining operator observations."""
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM station_telemetry_snapshots "
                    "WHERE data_source='simulated'"
                )
            )
