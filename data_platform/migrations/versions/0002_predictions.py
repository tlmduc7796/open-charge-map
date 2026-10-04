"""Add station prediction storage and session-duration metric.

Revision ID: 0002_predictions
Revises: 0001_initial_schema
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_predictions"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE prediction_source AS ENUM ('persistence', 'model')")
    op.execute(
        "ALTER TABLE station_live_metrics "
        "ADD COLUMN avg_session_duration_min numeric(8, 2)"
    )
    op.execute(
        "ALTER TABLE station_live_metrics "
        "ADD CONSTRAINT ck_station_live_metrics_session_positive "
        "CHECK (avg_session_duration_min IS NULL OR avg_session_duration_min > 0)"
    )
    op.execute(
        """
        CREATE TABLE predictions (
            station_id uuid NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
            run_at timestamptz NOT NULL,
            horizon_min smallint NOT NULL,
            predicted_occupancy_ratio numeric(7, 6),
            operational_ports_at_run smallint NOT NULL,
            wait_probability numeric(7, 6),
            mean_wait_minutes numeric(8, 2),
            p90_wait_minutes numeric(8, 2),
            prediction_source prediction_source NOT NULL,
            model_version text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_predictions PRIMARY KEY (station_id, run_at, horizon_min),
            CONSTRAINT ck_predictions_supported_horizon
                CHECK (horizon_min IN (5, 10, 15, 20, 25, 30)),
            CONSTRAINT ck_predictions_operational_nonnegative
                CHECK (operational_ports_at_run >= 0),
            CONSTRAINT ck_predictions_occupancy_ratio
                CHECK (predicted_occupancy_ratio IS NULL
                    OR predicted_occupancy_ratio BETWEEN 0 AND 1),
            CONSTRAINT ck_predictions_ratio_matches_capacity CHECK (
                (operational_ports_at_run = 0 AND predicted_occupancy_ratio IS NULL)
                OR (operational_ports_at_run > 0 AND predicted_occupancy_ratio IS NOT NULL)
            ),
            CONSTRAINT ck_predictions_wait_probability
                CHECK (wait_probability IS NULL OR wait_probability BETWEEN 0 AND 1),
            CONSTRAINT ck_predictions_mean_wait_nonnegative
                CHECK (mean_wait_minutes IS NULL OR mean_wait_minutes >= 0),
            CONSTRAINT ck_predictions_p90_wait_nonnegative
                CHECK (p90_wait_minutes IS NULL OR p90_wait_minutes >= 0),
            CONSTRAINT ck_predictions_p90_after_mean CHECK (
                mean_wait_minutes IS NULL OR p90_wait_minutes IS NULL
                OR p90_wait_minutes >= mean_wait_minutes
            ),
            CONSTRAINT ck_predictions_model_version_nonempty
                CHECK (char_length(trim(model_version)) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_predictions_station_run "
        "ON predictions (station_id, run_at DESC)"
    )
    op.execute(
        """
        CREATE VIEW station_predictions_latest AS
        WITH latest_runs AS (
            SELECT station_id, max(run_at) AS run_at
            FROM predictions
            GROUP BY station_id
        )
        SELECT
            p.station_id,
            s.code AS station_code,
            p.run_at,
            p.horizon_min,
            p.run_at + p.horizon_min * interval '1 minute' AS target_at,
            p.predicted_occupancy_ratio,
            p.operational_ports_at_run,
            p.operational_ports_at_run * (1 - p.predicted_occupancy_ratio)
                AS predicted_available_ports,
            p.wait_probability,
            p.mean_wait_minutes,
            p.p90_wait_minutes,
            p.prediction_source,
            p.model_version
        FROM predictions p
        JOIN latest_runs lr
            ON lr.station_id = p.station_id
           AND lr.run_at = p.run_at
        JOIN stations s ON s.id = p.station_id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS station_predictions_latest")
    op.execute("DROP TABLE IF EXISTS predictions")
    op.execute(
        "ALTER TABLE station_live_metrics "
        "DROP CONSTRAINT IF EXISTS ck_station_live_metrics_session_positive"
    )
    op.execute(
        "ALTER TABLE station_live_metrics "
        "DROP COLUMN IF EXISTS avg_session_duration_min"
    )
    op.execute("DROP TYPE IF EXISTS prediction_source")
