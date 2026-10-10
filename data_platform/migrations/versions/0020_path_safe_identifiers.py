"""Constrain identifiers used in URL path segments.

Revision ID: 0020_path_safe_ids
Revises: 0019_port_external_id_unique
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020_path_safe_ids"
down_revision: str | None = "0019_port_external_id_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_stations_code_path_segment",
        "stations",
        "code ~ '^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$'",
    )
    op.create_check_constraint(
        "ck_planned_arrivals_id_path_segment",
        "planned_arrivals",
        "arrival_id ~ '^[A-Za-z0-9][A-Za-z0-9._~-]{0,127}$'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_planned_arrivals_id_path_segment",
        "planned_arrivals",
        type_="check",
    )
    op.drop_constraint(
        "ck_stations_code_path_segment",
        "stations",
        type_="check",
    )
