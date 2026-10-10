"""Persist immutable journey recommendation responses.

Revision ID: 0007_journey_recommendations
Revises: 0006_station_telemetry
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_journey_recommendations"
down_revision: str | None = "0006_station_telemetry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE journey_recommendations (
            recommendation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            journey_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            generated_at timestamptz NOT NULL,
            ranking_policy_version text NOT NULL,
            scoring_method text NOT NULL,
            outcome text NOT NULL,
            request jsonb NOT NULL,
            response jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_journey_recommendations_policy
                CHECK (char_length(trim(ranking_policy_version)) > 0),
            CONSTRAINT ck_journey_recommendations_outcome
                CHECK (outcome IN ('direct_no_charge', 'charging_stops', 'no_reachable_station')),
            CONSTRAINT ck_journey_recommendations_payloads
                CHECK (jsonb_typeof(request) = 'object' AND jsonb_typeof(response) = 'object')
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_journey_recommendations_journey_created "
        "ON journey_recommendations (journey_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS journey_recommendations")
