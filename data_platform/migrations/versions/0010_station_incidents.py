"""Persist authenticated, idempotent station incident reports.

Revision ID: 0010_station_incidents
Revises: 0009_journey_access_tokens
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010_station_incidents"
down_revision: str | None = "0009_journey_access_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE station_incidents (
            incident_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            journey_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            station_id uuid NOT NULL REFERENCES stations(id) ON DELETE RESTRICT,
            idempotency_key text NOT NULL,
            incident_type text NOT NULL,
            description text NOT NULL,
            status text NOT NULL DEFAULT 'open',
            data_source text NOT NULL DEFAULT 'user_report',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_station_incidents_journey_idempotency
                UNIQUE (journey_id, idempotency_key),
            CONSTRAINT ck_station_incidents_key_nonempty
                CHECK (char_length(trim(idempotency_key)) BETWEEN 16 AND 100),
            CONSTRAINT ck_station_incidents_type CHECK (incident_type IN (
                'port_unavailable', 'queue_inaccurate', 'access_problem',
                'safety_concern', 'other'
            )),
            CONSTRAINT ck_station_incidents_description
                CHECK (char_length(trim(description)) BETWEEN 3 AND 500),
            CONSTRAINT ck_station_incidents_status
                CHECK (status IN ('open', 'triaged', 'resolved', 'rejected')),
            CONSTRAINT ck_station_incidents_source
                CHECK (data_source = 'user_report')
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_station_incidents_station_created "
        "ON station_incidents (station_id, created_at DESC)"
    )
    op.execute(
        "CREATE TRIGGER station_incidents_set_updated_at "
        "BEFORE UPDATE ON station_incidents FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS station_incidents")
