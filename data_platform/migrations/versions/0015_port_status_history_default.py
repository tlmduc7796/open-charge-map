"""Keep port-status history inserts available outside pre-created monthly partitions.

Revision ID: 0015_port_status_history_default
Revises: 0014_incident_review
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015_port_status_history_default"
down_revision: str | None = "0014_incident_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE port_status_history_default "
        "PARTITION OF port_status_history DEFAULT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE port_status_history DETACH PARTITION port_status_history_default")
