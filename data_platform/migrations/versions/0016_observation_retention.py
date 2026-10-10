"""Add time indexes for bounded observation-history retention scans.

Revision ID: 0016_observation_retention
Revises: 0015_port_status_history_default
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016_observation_retention"
down_revision: str | None = "0015_port_status_history_default"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX ix_station_occupancy_5m_bucket ON station_occupancy_5m (bucket_at)")
    op.execute(
        "CREATE INDEX ix_station_telemetry_snapshots_observed_at "
        "ON station_telemetry_snapshots (observed_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_station_telemetry_snapshots_observed_at")
    op.execute("DROP INDEX ix_station_occupancy_5m_bucket")
