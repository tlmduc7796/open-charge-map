"""PostgreSQL-backed repositories for the operational station and vehicle catalog."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Engine, text

from backend.app.domain.models import (
    Connector,
    PointGeometry,
    PortRuntimeStatus,
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
        COALESCE(
            (s.provenance->'catalog_import'->>'source_updated_at')::timestamptz,
            (s.provenance->'name'->>'retrieved_at')::timestamptz,
            s.updated_at
        ) AS source_updated_at,
        CASE
            WHEN s.provenance->'catalog_import'->>'source_updated_at' IS NOT NULL
                OR s.provenance->'name'->>'retrieved_at' IS NOT NULL
                THEN 'source'
            WHEN s.updated_at IS NOT NULL THEN 'database_updated_at'
            ELSE 'missing'
        END AS source_updated_at_basis,
        s.provenance,
        (
            SELECT ser.external_id
            FROM station_external_refs ser
            WHERE ser.station_id = s.id
            ORDER BY ser.is_primary DESC, ser.provider, ser.external_id
            LIMIT 1
        ) AS provider_station_id,
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
                    ORDER BY grouped.connector_code, grouped.max_power_kw
                )
                FROM (
                    SELECT
                        p.connector_code,
                        ct.current_type::text AS current_type,
                        p.max_power_kw,
                        count(*)::integer AS port_count,
                        CASE
                            WHEN bool_or(p.data_origin::text = 'synthetic')
                                THEN 'database:synthetic'
                            ELSE 'database'
                        END AS source
                    FROM ports p
                    JOIN connector_types ct ON ct.code = p.connector_code
                    WHERE p.station_id = s.id AND p.is_active
                    GROUP BY p.connector_code, ct.current_type, p.max_power_kw
                ) grouped
            ),
            '[]'::jsonb
        ) AS connectors,
        COALESCE(
            (
                SELECT jsonb_agg(sa.amenity_code ORDER BY sa.amenity_code)
                FROM station_amenities sa
                WHERE sa.station_id = s.id AND sa.is_available IS TRUE
            ),
            '[]'::jsonb
        ) AS amenities
    FROM stations s
    WHERE s.is_active
"""
MAX_STATION_CANDIDATE_QUERY_LIMIT = 501


_VEHICLE_SELECT = """
    SELECT
        vm.code,
        vm.brand,
        vm.model,
        vm.variant,
        vm.battery_kwh,
        vm.usable_battery_kwh,
        vm.consumption_kwh_per_100km,
        vm.max_ac_kw,
        vm.max_dc_kw,
        vm.market,
        vm.provenance,
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
      AND COALESCE(vm.provenance->'_legacy_demo'->>'reserve_soc',
                   vm.provenance->'_calculation_defaults'->>'reserve_soc') IS NOT NULL
      AND COALESCE(vm.provenance->'_legacy_demo'->>'default_target_soc',
                   vm.provenance->'_calculation_defaults'->>'default_target_soc') IS NOT NULL
      AND COALESCE(vm.provenance->'_legacy_demo'->>'charging_efficiency',
                   vm.provenance->'_calculation_defaults'->>'charging_efficiency') IS NOT NULL
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
        slm.avg_session_duration_min,
        COALESCE((
            SELECT jsonb_agg(
                jsonb_build_object(
                    'connector_types', jsonb_build_array(p.connector_code),
                    'state', COALESCE(ps.status::text, 'unknown'),
                    'observed_at', ps.reported_at
                ) ORDER BY p.label
            )
            FROM ports p
            LEFT JOIN port_status ps ON ps.port_id = p.id
            WHERE p.station_id = s.id AND p.is_active
        ), '[]'::jsonb) AS port_runtime_statuses,
        NOT EXISTS (
            SELECT 1 FROM ports p
            JOIN port_status ps ON ps.port_id = p.id
            WHERE p.station_id = s.id AND p.is_active
              AND ps.data_origin::text <> 'synthetic'
        ) AS synthetic_status
    FROM stations s
    JOIN station_status_current ssc ON ssc.station_id = s.id
    LEFT JOIN station_live_metrics slm ON slm.station_id = s.id
    WHERE s.is_active
"""

_RELEASE_STATION_FILTER = """
    AND NOT EXISTS (
        SELECT 1
        FROM jsonb_each(COALESCE(s.provenance, '{}'::jsonb)) AS provenance_entry(key, value)
        WHERE jsonb_typeof(provenance_entry.value) = 'object'
          AND (
              provenance_entry.value->>'origin' = 'synthetic'
              OR provenance_entry.value->>'provider' ILIKE '%synthetic%'
          )
    )
    AND NOT EXISTS (
        SELECT 1 FROM ports p
        WHERE p.station_id = s.id AND p.is_active
          AND p.data_origin::text = 'synthetic'
    )
"""


def _synthetic_fields(provenance: dict[str, Any]) -> tuple[str, ...]:
    synthetic: set[str] = set()

    def visit(fields: dict[str, Any], prefix: str = "") -> None:
        for field, details in fields.items():
            if not isinstance(details, dict):
                continue
            field_path = f"{prefix}.{field}" if prefix else field
            provider = details.get("provider")
            if details.get("origin") == "synthetic" or (
                isinstance(provider, str) and "synthetic" in provider.casefold()
            ):
                synthetic.add(field_path)
            else:
                visit(details, field_path)

    visit(provenance)
    return tuple(sorted(synthetic))


def _station_from_row(row: Any) -> Station:
    connectors = tuple(Connector.model_validate(item) for item in row["connectors"])
    if not connectors:
        raise ValueError(f"active station has no active ports: {row['code']}")
    provenance = row["provenance"] or {}
    notes = (row["access_note"],) if row["access_note"] else ()
    source_provider = (
        provenance.get("name", {}).get("provider")
        if isinstance(provenance.get("name"), dict)
        else None
    ) or "database"
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
            source_provider=source_provider,
            source_updated_at=row["source_updated_at"],
            source_updated_at_basis=row.get("source_updated_at_basis", "missing"),
            synthetic_fields=_synthetic_fields(provenance),
        ),
    )


def _vehicle_from_row(row: Any) -> Vehicle:
    provenance = row["provenance"] or {}
    legacy = provenance.get("_legacy_demo") or {}
    catalog_import = provenance.get("catalog_import") or {}
    calculation = {**(provenance.get("_calculation_defaults") or {}), **legacy}
    planning_power = provenance.get("_planning_power_fallback") or {}
    battery_provenance = provenance.get("battery_kwh") or {}
    battery_note = (battery_provenance.get("note") or "").lower()
    connectors = row["connectors"]
    return Vehicle(
        vehicle_id=legacy.get("vehicle_id") or row["code"],
        make=row["brand"],
        model=row["model"],
        variant=row["variant"],
        battery_capacity_kwh=float(row["battery_kwh"]),
        usable_battery_kwh=(
            float(row["usable_battery_kwh"])
            if row.get("usable_battery_kwh") is not None
            else float(row["battery_kwh"])
            if battery_note.startswith(("published usable capacity", "catl usable capacity"))
            else None
        ),
        max_ac_power_kw=float(row["max_ac_kw"] or planning_power.get("max_ac_kw") or 0),
        max_dc_power_kw=float(row["max_dc_kw"] or planning_power.get("max_dc_kw") or 0),
        ac_connectors=tuple(
            item["code"] for item in connectors if item["current"] == "AC"
        ),
        dc_connectors=tuple(
            item["code"] for item in connectors if item["current"] == "DC"
        ),
        consumption_wh_km=float(row["consumption_kwh_per_100km"]) * 10,
        reserve_soc=float(calculation["reserve_soc"]),
        default_target_soc=float(calculation["default_target_soc"]),
        charging_efficiency=float(calculation["charging_efficiency"]),
        source=(
            legacy.get("source_ref")
            or battery_provenance.get("source_ref")
            or catalog_import.get("source")
            or "database"
        ),
        is_synthetic=row["market"] == "DEMO",
        synthetic_fields=_synthetic_fields(provenance),
    )


def _status_from_row(row: Any) -> StationStatus:
    unknown_ports = int(row["unknown_ports"])
    total_ports = int(row["total_ports"])
    port_runtime_statuses = row.get("port_runtime_statuses")
    if isinstance(port_runtime_statuses, str):
        port_runtime_statuses = json.loads(port_runtime_statuses)
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
        data_source=(
            "unknown"
            if unknown_ports == total_ports
            else "synthetic" if row["synthetic_status"] else "database"
        ),
        port_runtime_statuses=(
            tuple(PortRuntimeStatus.model_validate(item) for item in port_runtime_statuses)
            if port_runtime_statuses is not None
            else None
        ),
    )


class DatabaseStationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def all(self) -> tuple[Station, ...]:
        with self._engine.connect() as connection:
            rows = connection.execute(text(_STATION_SELECT + " ORDER BY s.code")).mappings()
            return tuple(_station_from_row(row) for row in rows)

    def page(
        self,
        *,
        limit: int,
        after_station_id: str | None = None,
        include_synthetic: bool = False,
    ) -> tuple[Station, ...]:
        query = _STATION_SELECT
        parameters: dict[str, Any] = {"limit": limit}
        if not include_synthetic:
            query += _RELEASE_STATION_FILTER
        if after_station_id is not None:
            query += " AND s.code > :after_station_id"
            parameters["after_station_id"] = after_station_id
        query += " ORDER BY s.code LIMIT :limit"
        with self._engine.connect() as connection:
            rows = connection.execute(text(query), parameters).mappings()
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

    def telemetry_port_inventory(
        self, station_id: str
    ) -> tuple[tuple[str, str], ...]:
        """Return reviewed telemetry IDs and connector codes for active ports.

        Provider port IDs take precedence when reviewed into ``external_id``;
        otherwise the stable catalog label is the adapter-facing ID.
        """
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT COALESCE(NULLIF(btrim(p.external_id), ''), p.label) "
                    "AS telemetry_port_id, p.connector_code "
                    "FROM ports p JOIN stations s ON s.id=p.station_id "
                    "WHERE s.code=:station_id AND s.is_active AND p.is_active "
                    "ORDER BY p.label"
                ),
                {"station_id": station_id},
            ).all()
        if not rows:
            raise KeyError(station_id)
        inventory = tuple((row[0], row[1]) for row in rows)
        identifiers = tuple(port_id for port_id, _connector in inventory)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(
                f"station {station_id} has duplicate telemetry port identifiers"
            )
        return inventory

    def filter_ids(
        self, station_ids: tuple[str, ...], *, include_synthetic: bool = False
    ) -> tuple[str, ...]:
        if not station_ids:
            return ()
        query = "SELECT s.code FROM stations s WHERE s.is_active AND s.code=ANY(:station_ids)"
        if not include_synthetic:
            query += _RELEASE_STATION_FILTER
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(query), {"station_ids": list(station_ids)}
            ).scalars()
            eligible = set(rows)
        return tuple(station_id for station_id in station_ids if station_id in eligible)

    def within_radius(
        self,
        longitude: float,
        latitude: float,
        radius_m: float,
        limit: int,
        *,
        include_synthetic: bool = False,
    ) -> tuple[Station, ...]:
        point = "ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography"
        query = _STATION_SELECT + ("" if include_synthetic else _RELEASE_STATION_FILTER) + f"""
            AND ST_DWithin(s.location, {point}, :radius_m)
            ORDER BY ST_Distance(s.location, {point}), s.code
            LIMIT :limit
        """
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(query),
                {
                    "longitude": longitude,
                    "latitude": latitude,
                    "radius_m": radius_m,
                    "limit": limit,
                },
            ).mappings()
            return tuple(_station_from_row(row) for row in rows)

    def within_bbox(
        self,
        west: float,
        south: float,
        east: float,
        north: float,
        limit: int,
        *,
        include_synthetic: bool = False,
    ) -> tuple[Station, ...]:
        query = _STATION_SELECT + ("" if include_synthetic else _RELEASE_STATION_FILTER) + """
            AND ST_Y(s.location::geometry) BETWEEN :south AND :north
            AND (
                (:west <= :east AND ST_X(s.location::geometry) BETWEEN :west AND :east)
                OR (:west > :east AND (
                    ST_X(s.location::geometry) >= :west
                    OR ST_X(s.location::geometry) <= :east
                ))
            )
            ORDER BY s.code
            LIMIT :limit
        """
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(query),
                {
                    "west": west,
                    "south": south,
                    "east": east,
                    "north": north,
                    "limit": limit,
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
        *,
        include_synthetic: bool = False,
        limit: int = 51,
    ) -> tuple[Station, ...]:
        if not 1 <= limit <= MAX_STATION_CANDIDATE_QUERY_LIMIT:
            raise ValueError(
                "station candidate query limit must be between 1 and "
                f"{MAX_STATION_CANDIDATE_QUERY_LIMIT}"
            )
        query = _STATION_SELECT + ("" if include_synthetic else _RELEASE_STATION_FILTER) + """
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
            LIMIT :limit
        """
        parameters = {
            "origin_lon": origin_lon,
            "origin_lat": origin_lat,
            "destination_lon": destination_lon,
            "destination_lat": destination_lat,
            "corridor_m": corridor_m,
            "limit": limit,
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

    def get_many(self, station_ids: tuple[str, ...]) -> tuple[StationStatus, ...]:
        if not station_ids:
            return ()
        with self._engine.connect() as connection:
            rows = connection.execute(
                text(_STATUS_SELECT + " AND s.code = ANY(:station_ids) ORDER BY s.code"),
                {"station_ids": list(station_ids)},
            ).mappings()
            return tuple(_status_from_row(row) for row in rows)
