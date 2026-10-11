"""PostgreSQL-backed repositories for the operational station and vehicle catalog."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, text

from backend.app.domain.models import (
    Connector,
    PointGeometry,
    Station,
    StationProperties,
    StationStatus,
    Vehicle,
)

_STATION_SELECT = """
    SELECT
        s.code,
        s.name,
        s.address,
        s.operator_name,
        ST_X(s.location::geometry) AS longitude,
        ST_Y(s.location::geometry) AS latitude,
        s.opening_hours,
        s.access_level::text AS access_level,
        s.access_note,
        s.updated_at,
        NULL::text AS provider_station_id,
        COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'type', grouped.connector_code,
                        'current', grouped.current_type,
                        'max_power_kw', grouped.max_power_kw,
                        'count', grouped.port_count,
                        'source', grouped.source
                    )
                    ORDER BY grouped.connector_code
                )
                FROM (
                    SELECT
                        p.connector_code,
                        ct.current_type::text AS current_type,
                        max(p.max_power_kw) AS max_power_kw,
                        count(*)::integer AS port_count,
                        'database' AS source
                    FROM ports p
                    JOIN connector_types ct ON ct.code = p.connector_code
                    WHERE p.station_id = s.id AND p.is_active
                    GROUP BY p.connector_code, ct.current_type
                ) grouped
            ),
            '[]'::jsonb
        ) AS connectors,
        '[]'::jsonb AS amenities
    FROM stations s
    WHERE s.is_active
"""


_VEHICLE_SELECT = """
    SELECT
        vm.code,
        vm.brand,
        vm.model,
        vm.variant,
        vm.battery_kwh,
        vm.consumption_kwh_per_100km,
        vm.max_ac_kw,
        vm.max_dc_kw,
        vm.market,
        jsonb_agg(
            jsonb_build_object(
                'code', vc.connector_code,
                'current', ct.current_type::text
            )
            ORDER BY vc.connector_code
        ) AS connectors
    FROM vehicle_models vm
    JOIN vehicle_connectors vc ON vc.vehicle_model_id = vm.id
    JOIN connector_types ct ON ct.code = vc.connector_code
    WHERE vm.is_active
      AND vm.battery_kwh IS NOT NULL
      AND vm.consumption_kwh_per_100km IS NOT NULL
      AND (COALESCE(vm.max_ac_kw, 0) > 0 OR COALESCE(vm.max_dc_kw, 0) > 0)
    GROUP BY vm.id
    ORDER BY vm.brand, vm.model, vm.variant NULLS FIRST, vm.code
"""


_STATUS_SELECT = """
    SELECT
        s.code,
        COALESCE(ssc.reported_at, s.updated_at) AS reported_at,
        ssc.total_ports,
        ssc.operational_ports,
        ssc.occupied_ports,
        ssc.available_ports,
        ssc.offline_ports,
        ssc.unknown_ports,
        ssc.occupancy_ratio,
        ssc.queue_length,
        NULL::numeric AS avg_session_duration_min,
        NULL::text AS metrics_origin
    FROM stations s
    JOIN station_status_current ssc ON ssc.station_id = s.id
    WHERE s.is_active
"""


def _station_from_row(row: Any) -> Station:
    connectors = tuple(Connector.model_validate(item) for item in row["connectors"])
    if not connectors:
        raise ValueError(f"active station has no active ports: {row['code']}")
    notes = (row["access_note"],) if row["access_note"] else ()
    return Station(
        type="Feature",
        geometry=PointGeometry(
            type="Point",
            coordinates=(float(row["longitude"]), float(row["latitude"])),
        ),
        properties=StationProperties(
            station_id=row["code"],
            provider_station_id=row["provider_station_id"],
            name=row["name"],
            address=row["address"],
            operator=row["operator_name"],
            total_ports=sum(connector.count for connector in connectors),
            connectors=connectors,
            amenities=tuple(row["amenities"]),
            opening_hours=row["opening_hours"],
            access=row["access_level"],
            notes=notes,
            source_provider="database",
            source_updated_at=row["updated_at"],
            synthetic_fields=(),
        ),
    )


# Planning assumptions applied to every catalog vehicle (the catalog no longer stores them).
ASSUMED_RESERVE_SOC = 0.1
ASSUMED_TARGET_SOC = 1.0
ASSUMED_CHARGING_EFFICIENCY = 0.9
ASSUMED_AC_POWER_KW = 3.3  # used only when the catalog has no AC maximum
ASSUMED_DC_POWER_KW = 50.0  # used only when the catalog has no DC maximum


def _vehicle_from_row(row: Any) -> Vehicle:
    connectors = row["connectors"]
    return Vehicle(
        vehicle_id=row["code"],
        make=row["brand"],
        model=row["model"],
        variant=row["variant"],
        battery_capacity_kwh=float(row["battery_kwh"]),
        usable_battery_kwh=None,
        max_ac_power_kw=float(row["max_ac_kw"] or ASSUMED_AC_POWER_KW),
        max_dc_power_kw=float(row["max_dc_kw"] or ASSUMED_DC_POWER_KW),
        ac_connectors=tuple(
            item["code"] for item in connectors if item["current"] == "AC"
        ),
        dc_connectors=tuple(
            item["code"] for item in connectors if item["current"] == "DC"
        ),
        consumption_wh_km=float(row["consumption_kwh_per_100km"]) * 10,
        reserve_soc=ASSUMED_RESERVE_SOC,
        default_target_soc=ASSUMED_TARGET_SOC,
        charging_efficiency=ASSUMED_CHARGING_EFFICIENCY,
        source="database",
        is_synthetic=row["market"] == "DEMO",
        synthetic_fields=(),
    )


def _status_from_row(row: Any) -> StationStatus:
    unknown_ports = int(row["unknown_ports"])
    total_ports = int(row["total_ports"])
    return StationStatus(
        station_id=row["code"],
        timestamp=row["reported_at"],
        total_ports=total_ports,
        operational_ports=int(row["operational_ports"]),
        occupied_ports=int(row["occupied_ports"]),
        available_ports=int(row["available_ports"]),
        offline_ports=int(row["offline_ports"]),
        unknown_ports=unknown_ports,
        occupancy_ratio=(
            float(row["occupancy_ratio"])
            if row["occupancy_ratio"] is not None
            else None
        ),
        queue_length=(
            int(row["queue_length"]) if row["queue_length"] is not None else None
        ),
        avg_session_duration_min=(
            float(row["avg_session_duration_min"])
            if row["avg_session_duration_min"] is not None
            else None
        ),
        data_source="unknown" if unknown_ports == total_ports else "database",
    )


class DatabaseStationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def all(self) -> tuple[Station, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(text(_STATION_SELECT + " ORDER BY s.code")).mappings()
            return tuple(_station_from_row(row) for row in rows)

    def get(self, station_id: str) -> Station:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(_STATION_SELECT + " AND s.code=:station_id"),
                {"station_id": station_id},
            ).mappings().one_or_none()
        if row is None:
            raise KeyError(station_id)
        return _station_from_row(row)

    def within_bbox(
        self, min_lon: float, min_lat: float, max_lon: float, max_lat: float
    ) -> tuple[Station, ...]:
        query = _STATION_SELECT + """
            AND ST_Intersects(
                s.location,
                ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)::geography
            )
            ORDER BY s.code
        """
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(query),
                {
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                },
            ).mappings()
            return tuple(_station_from_row(row) for row in rows)

    def nearby(
        self, longitude: float, latitude: float, radius_m: float
    ) -> tuple[Station, ...]:
        query = _STATION_SELECT + """
            AND ST_DWithin(
                s.location,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                :radius_m
            )
            ORDER BY ST_Distance(
                s.location,
                ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
            ), s.code
        """
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(query),
                {
                    "longitude": longitude,
                    "latitude": latitude,
                    "radius_m": radius_m,
                },
            ).mappings()
            return tuple(_station_from_row(row) for row in rows)

    def candidates(
        self,
        origin_lon: float,
        origin_lat: float,
        destination_lon: float,
        destination_lat: float,
        corridor_m: float,
    ) -> tuple[Station, ...]:
        query = _STATION_SELECT + """
            AND ST_DWithin(
                s.location,
                ST_MakeLine(
                    ST_SetSRID(ST_MakePoint(:origin_lon, :origin_lat), 4326),
                    ST_SetSRID(ST_MakePoint(:destination_lon, :destination_lat), 4326)
                )::geography,
                :corridor_m
            )
            ORDER BY ST_Distance(
                s.location,
                ST_MakeLine(
                    ST_SetSRID(ST_MakePoint(:origin_lon, :origin_lat), 4326),
                    ST_SetSRID(ST_MakePoint(:destination_lon, :destination_lat), 4326)
                )::geography
            ), s.code
        """
        parameters = {
            "origin_lon": origin_lon,
            "origin_lat": origin_lat,
            "destination_lon": destination_lon,
            "destination_lat": destination_lat,
            "corridor_m": corridor_m,
        }
        with self._engine.connect() as connection:
            rows = connection.execute(text(query), parameters).mappings()
            return tuple(_station_from_row(row) for row in rows)


class DatabaseVehicleRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def all(self) -> tuple[Vehicle, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(text(_VEHICLE_SELECT)).mappings()
            return tuple(_vehicle_from_row(row) for row in rows)

    def get(self, vehicle_id: str) -> Vehicle:
        for vehicle in self.all():
            if vehicle.vehicle_id == vehicle_id:
                return vehicle
        raise KeyError(vehicle_id)


class DatabaseStationStatusRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def all(self) -> tuple[StationStatus, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(text(_STATUS_SELECT + " ORDER BY s.code")).mappings()
            return tuple(_status_from_row(row) for row in rows)

    def get(self, station_id: str) -> StationStatus:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(_STATUS_SELECT + " AND s.code=:station_id"),
                {"station_id": station_id},
            ).mappings().one_or_none()
        if row is None:
            raise KeyError(station_id)
        return _status_from_row(row)
