"""Add database-backed planned arrivals and station arrival rates.

Revision ID: 0005_planned_arrivals
Revises: 0004_trips_config
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_planned_arrivals"
down_revision: str | None = "0004_trips_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE station_arrival_rates (
            station_id uuid PRIMARY KEY
                REFERENCES stations(id) ON DELETE CASCADE,
            baseline_arrival_rate_per_hour numeric(10, 4) NOT NULL,
            data_source text NOT NULL DEFAULT 'synthetic',
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_station_arrival_rates_nonnegative
                CHECK (baseline_arrival_rate_per_hour >= 0),
            CONSTRAINT ck_station_arrival_rates_source
                CHECK (data_source = 'synthetic')
        )
        """
    )
    op.execute(
        """
        CREATE TABLE planned_arrivals (
            arrival_id text PRIMARY KEY,
            station_id uuid NOT NULL
                REFERENCES stations(id) ON DELETE RESTRICT,
            vehicle_model_id uuid
                REFERENCES vehicle_models(id) ON DELETE SET NULL,
            route_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            eta_at timestamptz NOT NULL,
            eta_window_start timestamptz NOT NULL,
            eta_window_end timestamptz NOT NULL,
            expected_energy_kwh numeric(10, 3) NOT NULL,
            expected_charge_duration_min numeric(10, 3) NOT NULL,
            arrival_probability numeric(7, 6) NOT NULL,
            expires_at timestamptz NOT NULL,
            status text NOT NULL DEFAULT 'planned',
            data_source text NOT NULL,
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_planned_arrivals_id_nonempty
                CHECK (char_length(trim(arrival_id)) > 0),
            CONSTRAINT ck_planned_arrivals_route_id_nonempty
                CHECK (route_id IS NULL OR char_length(trim(route_id)) > 0),
            CONSTRAINT ck_planned_arrivals_energy_nonnegative
                CHECK (expected_energy_kwh >= 0),
            CONSTRAINT ck_planned_arrivals_charge_duration_positive
                CHECK (expected_charge_duration_min > 0),
            CONSTRAINT ck_planned_arrivals_probability
                CHECK (arrival_probability BETWEEN 0 AND 1),
            CONSTRAINT ck_planned_arrivals_status
                CHECK (status IN ('planned', 'arrived', 'cancelled', 'expired')),
            CONSTRAINT ck_planned_arrivals_source
                CHECK (data_source IN ('runtime', 'synthetic')),
            CONSTRAINT ck_planned_arrivals_eta_window
                CHECK (eta_window_start <= eta_at AND eta_at <= eta_window_end),
            CONSTRAINT ck_planned_arrivals_expiry
                CHECK (expires_at > created_at)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_planned_arrivals_station_eta_planned
        ON planned_arrivals (station_id, eta_at)
        WHERE status = 'planned'
        """
    )
    op.execute(
        """
        CREATE INDEX ix_planned_arrivals_expires_planned
        ON planned_arrivals (expires_at)
        WHERE status = 'planned'
        """
    )
    op.execute(
        "CREATE TRIGGER station_arrival_rates_set_updated_at "
        "BEFORE UPDATE ON station_arrival_rates FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER planned_arrivals_set_updated_at "
        "BEFORE UPDATE ON planned_arrivals FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS planned_arrivals")
    op.execute("DROP TABLE IF EXISTS station_arrival_rates")
