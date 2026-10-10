"""Add trip history, positions, events and application configuration.

Revision ID: 0004_trips_config
Revises: 0003_context_vehicles
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_trips_config"
down_revision: str | None = "0003_context_vehicles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE trips (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            mode text NOT NULL,
            vehicle_model_id uuid NOT NULL REFERENCES vehicle_models(id),
            origin geography(Point, 4326) NOT NULL,
            destination geography(Point, 4326),
            start_battery_pct numeric(5, 2) NOT NULL,
            station_id uuid REFERENCES stations(id) ON DELETE SET NULL,
            route geography(LineString, 4326),
            route_version integer NOT NULL DEFAULT 0,
            phase text NOT NULL DEFAULT 'to_station',
            planned jsonb NOT NULL DEFAULT '{}'::jsonb,
            last_reroute_at timestamptz,
            declined_station_ids uuid[] NOT NULL DEFAULT '{}'::uuid[],
            created_at timestamptz NOT NULL DEFAULT now(),
            ended_at timestamptz,
            CONSTRAINT ck_trips_mode CHECK (mode IN ('find_station', 'route')),
            CONSTRAINT ck_trips_phase CHECK (
                phase IN ('to_station', 'at_station', 'to_destination', 'arrived', 'cancelled')
            ),
            CONSTRAINT ck_trips_start_battery
                CHECK (start_battery_pct BETWEEN 0 AND 100),
            CONSTRAINT ck_trips_route_version CHECK (route_version >= 0),
            CONSTRAINT ck_trips_destination_matches_mode CHECK (
                (mode = 'find_station' AND destination IS NULL)
                OR (mode = 'route' AND destination IS NOT NULL)
            ),
            CONSTRAINT ck_trips_end_after_create
                CHECK (ended_at IS NULL OR ended_at >= created_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_trips_vehicle_created ON trips (vehicle_model_id, created_at)"
    )
    op.execute("CREATE INDEX ix_trips_station_created ON trips (station_id, created_at)")
    op.execute(
        """
        CREATE TABLE trip_positions (
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            recorded_at timestamptz NOT NULL,
            location geography(Point, 4326) NOT NULL,
            speed_kmh numeric(8, 2),
            heading numeric(6, 2),
            battery_pct numeric(5, 2),
            distance_km numeric(10, 3),
            CONSTRAINT pk_trip_positions PRIMARY KEY (trip_id, recorded_at),
            CONSTRAINT ck_trip_positions_speed_nonnegative
                CHECK (speed_kmh IS NULL OR speed_kmh >= 0),
            CONSTRAINT ck_trip_positions_heading
                CHECK (heading IS NULL OR (heading >= 0 AND heading < 360)),
            CONSTRAINT ck_trip_positions_battery
                CHECK (battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100),
            CONSTRAINT ck_trip_positions_distance_nonnegative
                CHECK (distance_km IS NULL OR distance_km >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE trip_events (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trip_id uuid NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
            type text NOT NULL,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_trip_events_type CHECK (
                type IN ('reroute', 'station_suggested', 'station_accepted',
                    'station_declined', 'battery_corrected', 'arrived_station',
                    'arrived', 'cancelled')
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_trip_events_trip_created ON trip_events (trip_id, created_at)"
    )
    op.execute(
        """
        CREATE TABLE app_config (
            key text PRIMARY KEY,
            value jsonb NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_app_config_key_nonempty CHECK (char_length(trim(key)) > 0)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_config")
    op.execute("DROP TABLE IF EXISTS trip_events")
    op.execute("DROP TABLE IF EXISTS trip_positions")
    op.execute("DROP TABLE IF EXISTS trips")
