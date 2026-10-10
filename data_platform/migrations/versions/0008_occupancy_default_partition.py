"""Add a default partition for ongoing occupancy observations.

Revision ID: 0008_occupancy_default_partition
Revises: 0007_journey_recommendations
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_occupancy_default_partition"
down_revision: str | None = "0007_journey_recommendations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE station_occupancy_5m_default "
        "PARTITION OF station_occupancy_5m DEFAULT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE station_occupancy_5m "
        "DETACH PARTITION station_occupancy_5m_default"
    )
