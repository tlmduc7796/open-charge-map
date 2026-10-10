"""Add hashed bearer credentials for trip access.

Revision ID: 0006_trip_tokens
Revises: 0005_planned_arrivals
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006_trip_tokens"
down_revision: str | None = "0005_planned_arrivals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trips ADD COLUMN auth_token_hash text")
    op.execute(
        "ALTER TABLE trips ADD CONSTRAINT ck_trips_auth_token_hash_nonempty "
        "CHECK (auth_token_hash IS NULL OR char_length(auth_token_hash) = 64)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE trips DROP COLUMN IF EXISTS auth_token_hash")
