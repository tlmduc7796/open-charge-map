"""Enforce unique nonblank provider IDs across active ports per station.

Revision ID: 0019_port_external_id_unique
Revises: 0018_arrival_window_expiry
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "0019_port_external_id_unique"
down_revision: str | None = "0018_arrival_window_expiry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_ports_station_external_id_nonblank",
        "ports",
        ["station_id", text("btrim(external_id)")],
        unique=True,
        postgresql_where=text(
            "is_active IS TRUE AND external_id IS NOT NULL "
            "AND btrim(external_id) <> ''"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_ports_station_external_id_nonblank", table_name="ports")
