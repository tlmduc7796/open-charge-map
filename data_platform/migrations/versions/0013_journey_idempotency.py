"""Persist idempotency keys for journey creation retries.

Revision ID: 0013_journey_idempotency
Revises: 0012_arrival_journey_owner
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013_journey_idempotency"
down_revision: str | None = "0012_arrival_journey_owner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE journey_idempotency (
            key_hash char(64) PRIMARY KEY,
            request_hash char(64) NOT NULL,
            journey_id uuid NOT NULL UNIQUE REFERENCES trips(id) ON DELETE CASCADE,
            capability_revoked boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_journey_idempotency_hashes CHECK (
                key_hash ~ '^[0-9a-f]{64}$' AND request_hash ~ '^[0-9a-f]{64}$'
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS journey_idempotency")
