"""Bind planned arrivals created from the app to their journey owner.

Revision ID: 0012_arrival_journey_owner
Revises: 0011_journey_token_expiry
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012_arrival_journey_owner"
down_revision: str | None = "0011_journey_token_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE planned_arrivals ADD COLUMN journey_id uuid "
        "REFERENCES trips(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX ix_planned_arrivals_journey "
        "ON planned_arrivals (journey_id) WHERE journey_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_planned_arrivals_journey")
    op.execute("ALTER TABLE planned_arrivals DROP COLUMN IF EXISTS journey_id")
