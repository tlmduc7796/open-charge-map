"""Create the initial static and runtime data schema.

Revision ID: 0001_initial_schema
Revises: None
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        "CREATE TYPE access_level AS ENUM ('public', 'customers', 'private', 'unknown')"
    )
    op.execute("CREATE TYPE current_type AS ENUM ('AC', 'DC')")
    op.execute(
        "CREATE TYPE port_status_value AS ENUM "
        "('available', 'charging', 'out_of_service', 'unknown')"
    )
    op.execute("CREATE TYPE data_origin AS ENUM ('observed', 'inferred', 'synthetic')")

    op.execute(
        """
        CREATE TABLE stations (
            id uuid PRIMARY KEY,
            code text NOT NULL UNIQUE,
            name text NOT NULL,
            address text NOT NULL,
            operator_name text,
            location geography(Point, 4326) NOT NULL,
            opening_hours jsonb,
            access_level access_level NOT NULL,
            access_note text,
            is_active boolean NOT NULL DEFAULT true,
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_stations_code_nonempty CHECK (char_length(trim(code)) > 0),
            CONSTRAINT ck_stations_name_nonempty CHECK (char_length(trim(name)) > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_stations_location_gist ON stations USING gist (location)")

    op.execute(
        """
        CREATE TABLE station_external_refs (
            id uuid PRIMARY KEY,
            station_id uuid NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
            provider text NOT NULL,
            external_id text NOT NULL,
            source_url text,
            retrieved_at timestamptz,
            is_primary boolean NOT NULL DEFAULT false,
            CONSTRAINT uq_station_external_refs_provider_id UNIQUE (provider, external_id),
            CONSTRAINT ck_station_external_refs_provider_nonempty
                CHECK (char_length(trim(provider)) > 0),
            CONSTRAINT ck_station_external_refs_id_nonempty
                CHECK (char_length(trim(external_id)) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_station_external_refs_station_id "
        "ON station_external_refs (station_id)"
    )

    op.execute(
        """
        CREATE TABLE connector_types (
            code text PRIMARY KEY,
            display_name text NOT NULL,
            current_type current_type NOT NULL,
            CONSTRAINT ck_connector_types_code_nonempty CHECK (char_length(trim(code)) > 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE ports (
            id uuid PRIMARY KEY,
            station_id uuid NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
            connector_code text NOT NULL REFERENCES connector_types(code),
            external_id text,
            label text NOT NULL,
            max_power_kw numeric(8, 2) NOT NULL,
            is_active boolean NOT NULL DEFAULT true,
            data_origin data_origin NOT NULL,
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_ports_station_label UNIQUE (station_id, label),
            CONSTRAINT ck_ports_positive_power CHECK (max_power_kw > 0),
            CONSTRAINT ck_ports_label_nonempty CHECK (char_length(trim(label)) > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_ports_station_id ON ports (station_id)")

    op.execute(
        """
        CREATE TABLE port_status (
            port_id uuid PRIMARY KEY REFERENCES ports(id) ON DELETE CASCADE,
            status port_status_value NOT NULL,
            session_started_at timestamptz,
            estimated_finish_at timestamptz,
            reported_at timestamptz NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            data_origin data_origin NOT NULL,
            CONSTRAINT ck_port_status_finish_after_start CHECK (
                session_started_at IS NULL OR estimated_finish_at IS NULL
                OR estimated_finish_at >= session_started_at
            )
        )
        """
    )

    op.execute(
        """
        CREATE TABLE station_live_metrics (
            station_id uuid PRIMARY KEY REFERENCES stations(id) ON DELETE CASCADE,
            queue_length integer NOT NULL,
            reported_at timestamptz NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            data_origin data_origin NOT NULL,
            CONSTRAINT ck_station_live_metrics_queue_nonnegative CHECK (queue_length >= 0)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE port_status_history (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            port_id uuid NOT NULL REFERENCES ports(id) ON DELETE CASCADE,
            status port_status_value NOT NULL,
            changed_at timestamptz NOT NULL,
            ingested_at timestamptz NOT NULL DEFAULT now(),
            data_origin data_origin NOT NULL,
            simulation_run_id uuid,
            CONSTRAINT pk_port_status_history PRIMARY KEY (id, changed_at),
            CONSTRAINT uq_port_status_history_port_time_run
                UNIQUE NULLS NOT DISTINCT (port_id, changed_at, simulation_run_id)
        ) PARTITION BY RANGE (changed_at)
        """
    )
    op.execute(
        "CREATE INDEX ix_port_status_history_changed_at ON port_status_history (changed_at)"
    )

    op.execute(
        """
        CREATE TABLE station_occupancy_5m (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            station_id uuid NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
            bucket_at timestamptz NOT NULL,
            total_ports smallint NOT NULL,
            operational_ports smallint NOT NULL,
            occupied_ports smallint NOT NULL,
            queue_length integer,
            data_origin data_origin NOT NULL,
            simulation_run_id uuid,
            CONSTRAINT pk_station_occupancy_5m PRIMARY KEY (id, bucket_at),
            CONSTRAINT uq_occupancy_station_bucket_run
                UNIQUE NULLS NOT DISTINCT (station_id, bucket_at, simulation_run_id),
            CONSTRAINT ck_occupancy_total_positive CHECK (total_ports > 0),
            CONSTRAINT ck_occupancy_operational_nonnegative CHECK (operational_ports >= 0),
            CONSTRAINT ck_occupancy_occupied_nonnegative CHECK (occupied_ports >= 0),
            CONSTRAINT ck_occupancy_operational_within_total
                CHECK (operational_ports <= total_ports),
            CONSTRAINT ck_occupancy_occupied_within_operational
                CHECK (occupied_ports <= operational_ports),
            CONSTRAINT ck_occupancy_queue CHECK (queue_length IS NULL OR queue_length >= 0),
            CONSTRAINT ck_occupancy_five_minute_bucket CHECK (
                EXTRACT(SECOND FROM bucket_at) = 0
                AND MOD(EXTRACT(MINUTE FROM bucket_at)::integer, 5) = 0
            )
        ) PARTITION BY RANGE (bucket_at)
        """
    )
    op.execute(
        "CREATE INDEX ix_station_occupancy_5m_station_bucket "
        "ON station_occupancy_5m (station_id, bucket_at)"
    )

    for table in ("port_status_history", "station_occupancy_5m"):
        for year, month, next_year, next_month in (
            (2026, 9, 2026, 10),
            (2026, 10, 2026, 11),
            (2026, 11, 2026, 12),
        ):
            op.execute(
                f"CREATE TABLE {table}_{year}_{month:02d} PARTITION OF {table} "
                f"FOR VALUES FROM ('{year}-{month:02d}-01 00:00:00+00') "
                f"TO ('{next_year}-{next_month:02d}-01 00:00:00+00')"
            )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER stations_set_updated_at BEFORE UPDATE ON stations "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER ports_set_updated_at BEFORE UPDATE ON ports "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    op.execute(
        """
        CREATE VIEW station_capacity AS
        WITH connector_capacity AS (
            SELECT
                p.station_id,
                p.connector_code,
                count(*)::integer AS port_count,
                max(p.max_power_kw) AS max_power_kw
            FROM ports p
            WHERE p.is_active
            GROUP BY p.station_id, p.connector_code
        ),
        totals AS (
            SELECT station_id, sum(port_count)::integer AS total_ports
            FROM connector_capacity
            GROUP BY station_id
        ),
        connector_json AS (
            SELECT
                station_id,
                jsonb_object_agg(
                    connector_code,
                    jsonb_build_object(
                        'count', port_count,
                        'max_power_kw', max_power_kw
                    )
                    ORDER BY connector_code
                ) AS connectors
            FROM connector_capacity
            GROUP BY station_id
        )
        SELECT
            s.id AS station_id,
            s.code AS station_code,
            COALESCE(t.total_ports, 0) AS total_ports,
            COALESCE(cj.connectors, '{}'::jsonb) AS connectors
        FROM stations s
        LEFT JOIN totals t ON t.station_id = s.id
        LEFT JOIN connector_json cj ON cj.station_id = s.id
        """
    )

    op.execute(
        """
        CREATE VIEW station_status_current AS
        WITH counts AS (
            SELECT
                p.station_id,
                count(*) FILTER (WHERE p.is_active)::integer AS total_ports,
                count(*) FILTER (
                    WHERE p.is_active AND ps.status IN ('available', 'charging')
                )::integer AS operational_ports,
                count(*) FILTER (
                    WHERE p.is_active AND ps.status = 'charging'
                )::integer AS occupied_ports,
                count(*) FILTER (
                    WHERE p.is_active AND ps.status = 'available'
                )::integer AS available_ports,
                count(*) FILTER (
                    WHERE p.is_active AND ps.status = 'out_of_service'
                )::integer AS offline_ports,
                count(*) FILTER (
                    WHERE p.is_active AND (ps.status = 'unknown' OR ps.port_id IS NULL)
                )::integer AS unknown_ports,
                max(ps.reported_at) AS port_status_reported_at
            FROM ports p
            LEFT JOIN port_status ps ON ps.port_id = p.id
            GROUP BY p.station_id
        )
        SELECT
            s.id AS station_id,
            s.code AS station_code,
            COALESCE(c.total_ports, 0) AS total_ports,
            COALESCE(c.operational_ports, 0) AS operational_ports,
            COALESCE(c.occupied_ports, 0) AS occupied_ports,
            COALESCE(c.available_ports, 0) AS available_ports,
            COALESCE(c.offline_ports, 0) AS offline_ports,
            COALESCE(c.unknown_ports, 0) AS unknown_ports,
            CASE
                WHEN COALESCE(c.operational_ports, 0) = 0 THEN NULL
                ELSE c.occupied_ports::numeric / c.operational_ports
            END AS occupancy_ratio,
            slm.queue_length,
            GREATEST(c.port_status_reported_at, slm.reported_at) AS reported_at
        FROM stations s
        LEFT JOIN counts c ON c.station_id = s.id
        LEFT JOIN station_live_metrics slm ON slm.station_id = s.id
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS station_status_current")
    op.execute("DROP VIEW IF EXISTS station_capacity")
    op.execute("DROP TRIGGER IF EXISTS ports_set_updated_at ON ports")
    op.execute("DROP TRIGGER IF EXISTS stations_set_updated_at ON stations")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP TABLE IF EXISTS station_occupancy_5m CASCADE")
    op.execute("DROP TABLE IF EXISTS port_status_history CASCADE")
    op.execute("DROP TABLE IF EXISTS station_live_metrics CASCADE")
    op.execute("DROP TABLE IF EXISTS port_status CASCADE")
    op.execute("DROP TABLE IF EXISTS ports CASCADE")
    op.execute("DROP TABLE IF EXISTS connector_types CASCADE")
    op.execute("DROP TABLE IF EXISTS station_external_refs CASCADE")
    op.execute("DROP TABLE IF EXISTS stations CASCADE")
    op.execute("DROP TYPE IF EXISTS data_origin")
    op.execute("DROP TYPE IF EXISTS port_status_value")
    op.execute("DROP TYPE IF EXISTS current_type")
    op.execute("DROP TYPE IF EXISTS access_level")
