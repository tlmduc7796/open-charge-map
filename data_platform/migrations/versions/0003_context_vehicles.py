"""Add verified station amenities and vehicle compatibility tables.

Revision ID: 0003_context_vehicles
Revises: 0002_predictions
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_context_vehicles"
down_revision: str | None = "0002_predictions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE station_amenities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            station_id uuid NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
            amenity_code text NOT NULL,
            is_available boolean,
            source_url text,
            verified_at timestamptz,
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_station_amenities_station_code
                UNIQUE (station_id, amenity_code),
            CONSTRAINT ck_station_amenities_code_nonempty
                CHECK (char_length(trim(amenity_code)) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_station_amenities_station_id ON station_amenities (station_id)"
    )
    op.execute(
        """
        CREATE TABLE vehicle_models (
            id uuid PRIMARY KEY,
            code text NOT NULL UNIQUE,
            brand text NOT NULL,
            model text NOT NULL,
            variant text,
            model_year smallint,
            market text NOT NULL,
            battery_kwh numeric(8, 2),
            consumption_kwh_per_100km numeric(8, 3),
            max_ac_kw numeric(8, 2),
            max_dc_kw numeric(8, 2),
            is_active boolean NOT NULL DEFAULT true,
            provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_vehicle_models_code_nonempty
                CHECK (char_length(trim(code)) > 0),
            CONSTRAINT ck_vehicle_models_brand_nonempty
                CHECK (char_length(trim(brand)) > 0),
            CONSTRAINT ck_vehicle_models_model_nonempty
                CHECK (char_length(trim(model)) > 0),
            CONSTRAINT ck_vehicle_models_market_nonempty
                CHECK (char_length(trim(market)) > 0),
            CONSTRAINT ck_vehicle_models_year
                CHECK (model_year IS NULL OR model_year BETWEEN 2000 AND 2200),
            CONSTRAINT ck_vehicle_models_battery_positive
                CHECK (battery_kwh IS NULL OR battery_kwh > 0),
            CONSTRAINT ck_vehicle_models_consumption_positive
                CHECK (consumption_kwh_per_100km IS NULL
                    OR consumption_kwh_per_100km > 0),
            CONSTRAINT ck_vehicle_models_ac_positive
                CHECK (max_ac_kw IS NULL OR max_ac_kw > 0),
            CONSTRAINT ck_vehicle_models_dc_positive
                CHECK (max_dc_kw IS NULL OR max_dc_kw > 0)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE vehicle_connectors (
            vehicle_model_id uuid NOT NULL
                REFERENCES vehicle_models(id) ON DELETE CASCADE,
            connector_code text NOT NULL REFERENCES connector_types(code),
            CONSTRAINT pk_vehicle_connectors
                PRIMARY KEY (vehicle_model_id, connector_code)
        )
        """
    )
    op.execute(
        "CREATE TRIGGER station_amenities_set_updated_at "
        "BEFORE UPDATE ON station_amenities FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER vehicle_models_set_updated_at "
        "BEFORE UPDATE ON vehicle_models FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vehicle_connectors")
    op.execute("DROP TABLE IF EXISTS vehicle_models")
    op.execute("DROP TABLE IF EXISTS station_amenities")
