from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType


class AccessLevel(str, enum.Enum):
    PUBLIC = "public"
    CUSTOMERS = "customers"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class CurrentType(str, enum.Enum):
    AC = "AC"
    DC = "DC"


class PortStatusValue(str, enum.Enum):
    AVAILABLE = "available"
    CHARGING = "charging"
    OUT_OF_SERVICE = "out_of_service"
    UNKNOWN = "unknown"


class DataOrigin(str, enum.Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    SYNTHETIC = "synthetic"


class PredictionSource(str, enum.Enum):
    PERSISTENCE = "persistence"
    MODEL = "model"


class GeographyPoint(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "geography(Point,4326)"


class GeographyLineString(UserDefinedType):
    cache_ok = True

    def get_col_spec(self, **_: Any) -> str:
        return "geography(LineString,4326)"


class Base(DeclarativeBase):
    pass


access_level_enum = Enum(
    AccessLevel,
    name="access_level",
    values_callable=lambda enum: [item.value for item in enum],
)
current_type_enum = Enum(
    CurrentType,
    name="current_type",
    values_callable=lambda enum: [item.value for item in enum],
)
port_status_enum = Enum(
    PortStatusValue,
    name="port_status_value",
    values_callable=lambda enum: [item.value for item in enum],
)
data_origin_enum = Enum(
    DataOrigin,
    name="data_origin",
    values_callable=lambda enum: [item.value for item in enum],
)
prediction_source_enum = Enum(
    PredictionSource,
    name="prediction_source",
    values_callable=lambda enum: [item.value for item in enum],
)


class Station(Base):
    __tablename__ = "stations"
    __table_args__ = (
        CheckConstraint("char_length(trim(code)) > 0", name="ck_stations_code_nonempty"),
        CheckConstraint("char_length(trim(name)) > 0", name="ck_stations_name_nonempty"),
        Index("ix_stations_location_gist", "location", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    operator_name: Mapped[str | None] = mapped_column(Text)
    location: Mapped[Any] = mapped_column(GeographyPoint(), nullable=False)
    opening_hours: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    access_level: Mapped[AccessLevel] = mapped_column(access_level_enum, nullable=False)
    access_note: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
class StationExternalRef(Base):
    __tablename__ = "station_external_refs"
    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_station_external_refs_provider_id"),
        Index("ix_station_external_refs_station_id", "station_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class ConnectorType(Base):
    __tablename__ = "connector_types"

    code: Mapped[str] = mapped_column(String, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    current_type: Mapped[CurrentType] = mapped_column(current_type_enum, nullable=False)


class Port(Base):
    __tablename__ = "ports"
    __table_args__ = (
        UniqueConstraint("station_id", "label", name="uq_ports_station_label"),
        CheckConstraint("max_power_kw > 0", name="ck_ports_positive_power"),
        Index("ix_ports_station_id", "station_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    connector_code: Mapped[str] = mapped_column(
        ForeignKey("connector_types.code"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    max_power_kw: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    data_origin: Mapped[DataOrigin] = mapped_column(data_origin_enum, nullable=False)
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
class PortStatus(Base):
    __tablename__ = "port_status"

    port_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ports.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[PortStatusValue] = mapped_column(port_status_enum, nullable=False)
    session_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_finish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    data_origin: Mapped[DataOrigin] = mapped_column(data_origin_enum, nullable=False)


class StationLiveMetrics(Base):
    __tablename__ = "station_live_metrics"
    __table_args__ = (
        CheckConstraint("queue_length >= 0", name="ck_station_live_metrics_queue_nonnegative"),
        CheckConstraint(
            "avg_session_duration_min IS NULL OR avg_session_duration_min > 0",
            name="ck_station_live_metrics_session_positive",
        ),
    )

    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), primary_key=True
    )
    queue_length: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_session_duration_min: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    data_origin: Mapped[DataOrigin] = mapped_column(data_origin_enum, nullable=False)


class PortStatusHistory(Base):
    __tablename__ = "port_status_history"
    __table_args__ = (
        PrimaryKeyConstraint("id", "changed_at", name="pk_port_status_history"),
        UniqueConstraint(
            "port_id",
            "changed_at",
            "simulation_run_id",
            name="uq_port_status_history_port_time_run",
            postgresql_nulls_not_distinct=True,
        ),
        {"postgresql_partition_by": "RANGE (changed_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, server_default=text("gen_random_uuid()")
    )
    port_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ports.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[PortStatusValue] = mapped_column(port_status_enum, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    data_origin: Mapped[DataOrigin] = mapped_column(data_origin_enum, nullable=False)
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class StationOccupancy5m(Base):
    __tablename__ = "station_occupancy_5m"
    __table_args__ = (
        PrimaryKeyConstraint("id", "bucket_at", name="pk_station_occupancy_5m"),
        UniqueConstraint(
            "station_id",
            "bucket_at",
            "simulation_run_id",
            name="uq_occupancy_station_bucket_run",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("total_ports > 0", name="ck_occupancy_total_positive"),
        CheckConstraint("operational_ports >= 0", name="ck_occupancy_operational_nonnegative"),
        CheckConstraint("occupied_ports >= 0", name="ck_occupancy_occupied_nonnegative"),
        CheckConstraint(
            "operational_ports <= total_ports", name="ck_occupancy_operational_within_total"
        ),
        CheckConstraint(
            "occupied_ports <= operational_ports", name="ck_occupancy_occupied_within_operational"
        ),
        CheckConstraint("queue_length IS NULL OR queue_length >= 0", name="ck_occupancy_queue"),
        Index("ix_station_occupancy_5m_station_bucket", "station_id", "bucket_at"),
        {"postgresql_partition_by": "RANGE (bucket_at)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, nullable=False, server_default=text("gen_random_uuid()")
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    bucket_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_ports: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    operational_ports: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    occupied_ports: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    queue_length: Mapped[int | None] = mapped_column(Integer)
    data_origin: Mapped[DataOrigin] = mapped_column(data_origin_enum, nullable=False)
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class Prediction(Base):
    __tablename__ = "predictions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "station_id", "run_at", "horizon_min", name="pk_predictions"
        ),
        CheckConstraint(
            "horizon_min IN (5, 10, 15, 20, 25, 30)",
            name="ck_predictions_supported_horizon",
        ),
        CheckConstraint(
            "operational_ports_at_run >= 0",
            name="ck_predictions_operational_nonnegative",
        ),
        CheckConstraint(
            "predicted_occupancy_ratio IS NULL OR "
            "predicted_occupancy_ratio BETWEEN 0 AND 1",
            name="ck_predictions_occupancy_ratio",
        ),
        CheckConstraint(
            "(operational_ports_at_run = 0 AND predicted_occupancy_ratio IS NULL) OR "
            "(operational_ports_at_run > 0 AND predicted_occupancy_ratio IS NOT NULL)",
            name="ck_predictions_ratio_matches_capacity",
        ),
        CheckConstraint(
            "wait_probability IS NULL OR wait_probability BETWEEN 0 AND 1",
            name="ck_predictions_wait_probability",
        ),
        CheckConstraint(
            "mean_wait_minutes IS NULL OR mean_wait_minutes >= 0",
            name="ck_predictions_mean_wait_nonnegative",
        ),
        CheckConstraint(
            "p90_wait_minutes IS NULL OR p90_wait_minutes >= 0",
            name="ck_predictions_p90_wait_nonnegative",
        ),
        CheckConstraint(
            "mean_wait_minutes IS NULL OR p90_wait_minutes IS NULL "
            "OR p90_wait_minutes >= mean_wait_minutes",
            name="ck_predictions_p90_after_mean",
        ),
        CheckConstraint(
            "char_length(trim(model_version)) > 0",
            name="ck_predictions_model_version_nonempty",
        ),
        Index("ix_predictions_station_run", "station_id", text("run_at DESC")),
    )

    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_min: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    predicted_occupancy_ratio: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    operational_ports_at_run: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    wait_probability: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    mean_wait_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    p90_wait_minutes: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    prediction_source: Mapped[PredictionSource] = mapped_column(
        prediction_source_enum, nullable=False
    )
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class StationAmenity(Base):
    __tablename__ = "station_amenities"
    __table_args__ = (
        UniqueConstraint("station_id", "amenity_code", name="uq_station_amenities_station_code"),
        CheckConstraint(
            "char_length(trim(amenity_code)) > 0",
            name="ck_station_amenities_code_nonempty",
        ),
        Index("ix_station_amenities_station_id", "station_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    station_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("stations.id", ondelete="CASCADE"), nullable=False
    )
    amenity_code: Mapped[str] = mapped_column(Text, nullable=False)
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    source_url: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class VehicleModel(Base):
    __tablename__ = "vehicle_models"
    __table_args__ = (
        CheckConstraint("char_length(trim(code)) > 0", name="ck_vehicle_models_code_nonempty"),
        CheckConstraint("char_length(trim(brand)) > 0", name="ck_vehicle_models_brand_nonempty"),
        CheckConstraint("char_length(trim(model)) > 0", name="ck_vehicle_models_model_nonempty"),
        CheckConstraint("char_length(trim(market)) > 0", name="ck_vehicle_models_market_nonempty"),
        CheckConstraint(
            "model_year IS NULL OR model_year BETWEEN 2000 AND 2200",
            name="ck_vehicle_models_year",
        ),
        CheckConstraint(
            "battery_kwh IS NULL OR battery_kwh > 0",
            name="ck_vehicle_models_battery_positive",
        ),
        CheckConstraint(
            "consumption_kwh_per_100km IS NULL OR consumption_kwh_per_100km > 0",
            name="ck_vehicle_models_consumption_positive",
        ),
        CheckConstraint(
            "max_ac_kw IS NULL OR max_ac_kw > 0",
            name="ck_vehicle_models_ac_positive",
        ),
        CheckConstraint(
            "max_dc_kw IS NULL OR max_dc_kw > 0",
            name="ck_vehicle_models_dc_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    brand: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    variant: Mapped[str | None] = mapped_column(Text)
    model_year: Mapped[int | None] = mapped_column(SmallInteger)
    market: Mapped[str] = mapped_column(Text, nullable=False)
    battery_kwh: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    consumption_kwh_per_100km: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    max_ac_kw: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    max_dc_kw: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    provenance: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class VehicleConnector(Base):
    __tablename__ = "vehicle_connectors"

    vehicle_model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vehicle_models.id", ondelete="CASCADE"), primary_key=True
    )
    connector_code: Mapped[str] = mapped_column(
        ForeignKey("connector_types.code"), primary_key=True
    )


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('find_station', 'route')",
            name="ck_trips_mode",
        ),
        CheckConstraint(
            "phase IN ('to_station', 'at_station', 'to_destination', 'arrived', 'cancelled')",
            name="ck_trips_phase",
        ),
        CheckConstraint(
            "start_battery_pct BETWEEN 0 AND 100",
            name="ck_trips_start_battery",
        ),
        CheckConstraint("route_version >= 0", name="ck_trips_route_version"),
        CheckConstraint(
            "(mode = 'find_station' AND destination IS NULL) "
            "OR (mode = 'route' AND destination IS NOT NULL)",
            name="ck_trips_destination_matches_mode",
        ),
        CheckConstraint(
            "ended_at IS NULL OR ended_at >= created_at",
            name="ck_trips_end_after_create",
        ),
        Index("ix_trips_vehicle_created", "vehicle_model_id", "created_at"),
        Index("ix_trips_station_created", "station_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    vehicle_model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vehicle_models.id"), nullable=False
    )
    origin: Mapped[Any] = mapped_column(GeographyPoint(), nullable=False)
    destination: Mapped[Any | None] = mapped_column(GeographyPoint())
    start_battery_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    station_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stations.id", ondelete="SET NULL")
    )
    route: Mapped[Any | None] = mapped_column(GeographyLineString())
    route_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    phase: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'to_station'"))
    planned: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    last_reroute_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_station_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(Uuid), nullable=False, server_default=text("'{}'::uuid[]")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TripPosition(Base):
    __tablename__ = "trip_positions"
    __table_args__ = (
        CheckConstraint(
            "speed_kmh IS NULL OR speed_kmh >= 0",
            name="ck_trip_positions_speed_nonnegative",
        ),
        CheckConstraint(
            "heading IS NULL OR heading >= 0 AND heading < 360",
            name="ck_trip_positions_heading",
        ),
        CheckConstraint(
            "battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100",
            name="ck_trip_positions_battery",
        ),
        CheckConstraint(
            "distance_km IS NULL OR distance_km >= 0",
            name="ck_trip_positions_distance_nonnegative",
        ),
    )

    trip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    location: Mapped[Any] = mapped_column(GeographyPoint(), nullable=False)
    speed_kmh: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    heading: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    battery_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))


class TripEvent(Base):
    __tablename__ = "trip_events"
    __table_args__ = (
        CheckConstraint(
            "type IN ('reroute', 'station_suggested', 'station_accepted', "
            "'station_declined', 'battery_corrected', 'arrived_station', "
            "'arrived', 'cancelled')",
            name="ck_trip_events_type",
        ),
        Index("ix_trip_events_trip_created", "trip_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    trip_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AppConfig(Base):
    __tablename__ = "app_config"
    __table_args__ = (
        CheckConstraint("char_length(trim(key)) > 0", name="ck_app_config_key_nonempty"),
    )

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
