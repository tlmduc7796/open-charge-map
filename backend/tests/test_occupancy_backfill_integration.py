"""PostgreSQL integration coverage for telemetry occupancy backfill."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from data_platform.backfill import backfill_occupancy_from_telemetry
from sqlalchemy import create_engine, text

from backend.app.config import load_settings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION") != "1",
    reason="requires a migrated PostgreSQL/PostGIS integration database",
)


def test_backfill_uses_latest_operational_snapshot_and_preserves_observed_bucket() -> None:
    engine = create_engine(load_settings().database_url, pool_pre_ping=True)
    station_id = uuid4()
    station_code = f"BACKFILL_TEST_{station_id.hex}"
    start_at = datetime(2001, 1, 1, 12, 0, tzinfo=UTC)
    snapshots = (
        (
            datetime(2001, 1, 1, 12, 1, tzinfo=UTC),
            "station_api",
            ["available", "available"],
            0,
        ),
        (
            datetime(2001, 1, 1, 12, 4, tzinfo=UTC),
            "station_api",
            ["available", "charging", "offline"],
            2,
        ),
        (
            datetime(2001, 1, 1, 12, 4, 30, tzinfo=UTC),
            "simulated",
            ["charging", "charging", "charging"],
            3,
        ),
        (
            datetime(2001, 1, 1, 12, 6, tzinfo=UTC),
            "camera_vision",
            ["charging", "offline"],
            0,
        ),
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO stations (id, code, name, address, location, access_level) "
                    "VALUES (:id, :code, 'Backfill test', 'Test', "
                    "ST_SetSRID(ST_MakePoint(0,0),4326)::geography, 'public')"
                ),
                {"id": station_id, "code": station_code},
            )
            for observed_at, source, states, queue_length in snapshots:
                payload = {
                    "ports": [{"state": state} for state in states],
                    "queue": [{} for _ in range(queue_length)],
                }
                connection.execute(
                    text(
                        "INSERT INTO station_telemetry_snapshots "
                        "(station_id, observed_at, data_source, snapshot) "
                        "VALUES (:station_id, :observed_at, :source, CAST(:snapshot AS jsonb))"
                    ),
                    {
                        "station_id": station_id,
                        "observed_at": observed_at,
                        "source": source,
                        "snapshot": json.dumps(payload),
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO station_occupancy_5m "
                    "(station_id, bucket_at, total_ports, operational_ports, "
                    "occupied_ports, queue_length, data_origin) "
                    "VALUES (:station_id, :bucket_at, 1, 1, 1, 9, 'synthetic')"
                ),
                {"station_id": station_id, "bucket_at": start_at},
            )
            connection.execute(
                text(
                    "INSERT INTO station_occupancy_5m "
                    "(station_id, bucket_at, total_ports, operational_ports, "
                    "occupied_ports, queue_length, data_origin) "
                    "VALUES (:station_id, :bucket_at, 2, 2, 0, 4, 'observed')"
                ),
                {
                    "station_id": station_id,
                    "bucket_at": datetime(2001, 1, 1, 12, 5, tzinfo=UTC),
                },
            )

        common = {
            "start_at": start_at,
            "end_at": datetime(2001, 1, 1, 12, 10, tzinfo=UTC),
            "station_code": station_code,
        }
        preview = backfill_occupancy_from_telemetry(engine, **common)
        assert preview == {"eligible": 2, "upserted": 0, "batches": 1}
        applied = backfill_occupancy_from_telemetry(engine, **common, apply=True)
        assert applied == {"eligible": 2, "upserted": 1, "batches": 1}

        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT bucket_at, total_ports, operational_ports, occupied_ports, "
                    "queue_length, data_origin FROM station_occupancy_5m "
                    "WHERE station_id=:station_id ORDER BY bucket_at"
                ),
                {"station_id": station_id},
            ).mappings().all()
        assert [
            (
                row["bucket_at"],
                row["total_ports"],
                row["operational_ports"],
                row["occupied_ports"],
                row["queue_length"],
                row["data_origin"],
            )
            for row in rows
        ] == [
            (start_at, 3, 2, 1, 2, "observed"),
            (datetime(2001, 1, 1, 12, 5, tzinfo=UTC), 2, 2, 0, 4, "observed"),
        ]
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM stations WHERE id=:id"), {"id": station_id})
        engine.dispose()
