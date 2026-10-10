"""Add hashed per-journey access capabilities.

Revision ID: 0009_journey_access_tokens
Revises: 0008_occupancy_default_partition
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009_journey_access_tokens"
down_revision: str | None = "0008_occupancy_default_partition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trips ADD COLUMN access_token_hash text")
    op.execute(
        "CREATE INDEX ix_trips_access_token_hash "
        "ON trips (access_token_hash) WHERE access_token_hash IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_trips_access_token_hash")
    op.execute("ALTER TABLE trips DROP COLUMN IF EXISTS access_token_hash")
