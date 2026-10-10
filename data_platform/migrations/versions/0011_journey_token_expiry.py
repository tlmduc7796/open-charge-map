"""Add expiry to journey capability tokens.

Revision ID: 0011_journey_token_expiry
Revises: 0010_station_incidents
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011_journey_token_expiry"
down_revision: str | None = "0010_station_incidents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trips ADD COLUMN access_token_expires_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE trips DROP COLUMN IF EXISTS access_token_expires_at")
