"""Add review metadata to operator-triaged station incidents.

Revision ID: 0014_incident_review
Revises: 0013_journey_idempotency
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014_incident_review"
down_revision: str | None = "0013_journey_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE station_incidents ADD COLUMN reviewed_at timestamptz")
    op.execute("ALTER TABLE station_incidents ADD COLUMN review_note text")
    op.execute(
        "ALTER TABLE station_incidents ADD CONSTRAINT ck_station_incidents_review_note "
        "CHECK (review_note IS NULL OR char_length(trim(review_note)) BETWEEN 3 AND 500)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE station_incidents DROP CONSTRAINT IF EXISTS "
        "ck_station_incidents_review_note"
    )
    op.execute("ALTER TABLE station_incidents DROP COLUMN IF EXISTS review_note")
    op.execute("ALTER TABLE station_incidents DROP COLUMN IF EXISTS reviewed_at")
