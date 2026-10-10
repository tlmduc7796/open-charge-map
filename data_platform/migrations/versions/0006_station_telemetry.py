"""Persist per-port station telemetry snapshots.

Revision ID: 0006_station_telemetry
Revises: 0005_planned_arrivals
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_station_telemetry"
down_revision: str | None = "0005_planned_arrivals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE station_telemetry_snapshots (
            station_id uuid NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
            observed_at timestamptz NOT NULL,
            data_source text NOT NULL,
            snapshot jsonb NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (station_id, observed_at),
            CONSTRAINT ck_station_telemetry_source
                CHECK (data_source IN ('simulated', 'station_api', 'camera_vision', 'combined')),
            CONSTRAINT ck_station_telemetry_snapshot_object
                CHECK (jsonb_typeof(snapshot) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_station_telemetry_latest "
        "ON station_telemetry_snapshots (station_id, observed_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS station_telemetry_snapshots")
