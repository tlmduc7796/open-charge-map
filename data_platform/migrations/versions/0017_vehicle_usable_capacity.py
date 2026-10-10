"""Preserve vehicle nominal and usable battery capacities separately.

Revision ID: 0017_vehicle_usable_capacity
Revises: 0016_observation_retention
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_vehicle_usable_capacity"
down_revision: str | None = "0016_observation_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vehicle_models",
        sa.Column("usable_battery_kwh", sa.Numeric(8, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_vehicle_models_usable_battery_range",
        "vehicle_models",
        "usable_battery_kwh IS NULL OR (usable_battery_kwh > 0 AND "
        "(battery_kwh IS NULL OR usable_battery_kwh <= battery_kwh))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_vehicle_models_usable_battery_range",
        "vehicle_models",
        type_="check",
    )
    op.drop_column("vehicle_models", "usable_battery_kwh")
