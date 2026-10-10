"""Require planned arrivals to remain valid through their ETA window.

Revision ID: 0018_arrival_window_expiry
Revises: 0017_vehicle_usable_capacity
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_arrival_window_expiry"
down_revision: str | None = "0017_vehicle_usable_capacity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Older API versions allowed an expiry at or before the end of the ETA
    # window. Preserve those rows while making their persisted timeline satisfy
    # the stricter contract enforced by current API/domain validation.
    op.execute(
        "UPDATE planned_arrivals "
        "SET expires_at = eta_window_end + interval '1 microsecond' "
        "WHERE expires_at <= eta_window_end"
    )
    op.create_check_constraint(
        "ck_planned_arrivals_expiry_after_eta_window",
        "planned_arrivals",
        "expires_at > eta_window_end",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_planned_arrivals_expiry_after_eta_window",
        "planned_arrivals",
        type_="check",
    )
