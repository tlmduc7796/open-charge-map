"""Validate and transactionally import operator-reviewed release catalogs."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field
from sqlalchemy import Engine, text

from backend.app.domain.models import Connector, StationCollection, StationProperties, Vehicle

NAMESPACE = uuid.UUID("bc88783d-7c75-4a73-b45d-6c0457abfe55")
CONNECTORS = {
    "CCS2": ("CCS2", "DC"),
    "TYPE2": ("Type2", "AC"),
    "GBTAC": ("GB/T AC", "AC"),
    "GBTDC": ("GB/T DC", "DC"),
}
CODE_PATTERN = re.compile(r"[^A-Za-z0-9]+")
VEHICLE_PROVENANCE_FIELDS = (
    "battery_capacity_kwh",
    "usable_battery_kwh",
    "max_ac_power_kw",
    "max_dc_power_kw",
    "ac_connectors",
    "dc_connectors",
    "consumption_wh_km",
    "reserve_soc",
    "default_target_soc",
    "charging_efficiency",
)
VEHICLE_PROVENANCE_ORIGINS = {"observed", "inferred", "operator_policy", "unpublished"}


class ReleaseCatalogVehicle(Vehicle):
    """Import-only vehicle record carrying provenance absent from public API models."""

    field_provenance: dict[str, Any] = Field()


def _connector_code(value: str) -> str:
    code = CODE_PATTERN.sub("", value).upper()
    if code not in CONNECTORS:
        raise ValueError(f"unsupported connector code: {value}")
    return code


def _expanded_station_ports(
    connectors: tuple[Connector, ...],
) -> tuple[tuple[Connector, str, str], ...]:
    """Assign stable unique labels when one connector standard has power groups."""
    assignments: list[tuple[Connector, str, str]] = []
    ordinals: dict[str, int] = {}
    ordered_groups = sorted(
        connectors,
        key=lambda connector: (
            _connector_code(connector.type),
            round(connector.max_power_kw, 2),
            connector.current,
        ),
    )
    for connector in ordered_groups:
        code = _connector_code(connector.type)
        for _ in range(connector.count):
            ordinal = ordinals.get(code, 0) + 1
            ordinals[code] = ordinal
            assignments.append((connector, code, f"{code}-{ordinal}"))
    return tuple(assignments)


def _validate_vehicle_field_provenance(vehicle: ReleaseCatalogVehicle) -> list[str]:
    provenance = vehicle.field_provenance
    issues: list[str] = []
    for field_name in VEHICLE_PROVENANCE_FIELDS:
        details = provenance.get(field_name)
        if not isinstance(details, dict):
            issues.append(
                f"vehicle {vehicle.vehicle_id} requires field_provenance.{field_name}"
            )
            continue
        origin = details.get("origin")
        if not isinstance(origin, str) or origin not in VEHICLE_PROVENANCE_ORIGINS:
            issues.append(
                f"vehicle {vehicle.vehicle_id} has invalid provenance origin for "
                f"{field_name}: {origin!r}"
            )
            continue
        provider = details.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            issues.append(
                f"vehicle {vehicle.vehicle_id} requires provenance provider "
                f"for {field_name}"
            )
        elif "synthetic" in provider.casefold():
            issues.append(
                f"vehicle {vehicle.vehicle_id} has a synthetic provenance provider "
                f"for {field_name}"
            )
        if origin == "operator_policy":
            if not isinstance(details.get("policy_id"), str) or not details["policy_id"].strip():
                issues.append(
                    f"vehicle {vehicle.vehicle_id} requires policy_id for {field_name}"
                )
        else:
            source_ref = details.get("source_ref")
            if not isinstance(source_ref, str) or not source_ref.strip():
                issues.append(
                    f"vehicle {vehicle.vehicle_id} requires source_ref for {field_name}"
                )
        if field_name in {"reserve_soc", "default_target_soc", "charging_efficiency"}:
            if origin != "operator_policy":
                issues.append(
                    f"vehicle {vehicle.vehicle_id} requires operator_policy provenance "
                    f"for {field_name}"
                )
        elif origin == "operator_policy":
            issues.append(
                f"vehicle {vehicle.vehicle_id} cannot use operator_policy provenance "
                f"for {field_name}"
            )
        if field_name in {"battery_capacity_kwh", "consumption_wh_km"} and origin == "unpublished":
            issues.append(
                f"vehicle {vehicle.vehicle_id} cannot mark populated {field_name} "
                "as unpublished"
            )
        if field_name in {"usable_battery_kwh", "max_ac_power_kw", "max_dc_power_kw"}:
            value = getattr(vehicle, field_name)
            if (value is None or value == 0) and origin != "unpublished":
                issues.append(
                    f"vehicle {vehicle.vehicle_id} must mark unavailable {field_name} "
                    "as unpublished"
                )
            elif value not in (None, 0) and origin == "unpublished":
                issues.append(
                    f"vehicle {vehicle.vehicle_id} has a value for unpublished {field_name}"
                )
        if field_name in {"ac_connectors", "dc_connectors"}:
            connector_values = getattr(vehicle, field_name)
            if connector_values and origin == "unpublished":
                issues.append(
                    f"vehicle {vehicle.vehicle_id} has {field_name} values marked unpublished"
                )
    return issues


def _vehicle_provenance_for_import(
    vehicle: ReleaseCatalogVehicle, *, reviewed_by: str, imported_at: datetime
) -> dict[str, object]:
    fields = vehicle.field_provenance
    return {
        "catalog_import": {
            "origin": "operator_reviewed",
            "source": vehicle.source,
            "reviewed_by": reviewed_by.strip(),
            "imported_at": imported_at.isoformat(),
        },
        "battery_kwh": dict(fields["battery_capacity_kwh"]),
        "usable_battery_kwh": dict(fields["usable_battery_kwh"]),
        "max_ac_kw": dict(fields["max_ac_power_kw"]),
        "max_dc_kw": dict(fields["max_dc_power_kw"]),
        "consumption_kwh_per_100km": dict(fields["consumption_wh_km"]),
        "ac_connectors": dict(fields["ac_connectors"]),
        "dc_connectors": dict(fields["dc_connectors"]),
        "_calculation_defaults": {
            "reserve_soc": vehicle.reserve_soc,
            "default_target_soc": vehicle.default_target_soc,
            "charging_efficiency": vehicle.charging_efficiency,
        },
        "_calculation_defaults_provenance": {
            "reserve_soc": dict(fields["reserve_soc"]),
            "default_target_soc": dict(fields["default_target_soc"]),
            "charging_efficiency": dict(fields["charging_efficiency"]),
        },
    }


def _station_provenance_for_import(
    properties: StationProperties, *, reviewed_by: str, imported_at: datetime
) -> dict[str, object]:
    source_updated_at = (
        properties.source_updated_at.isoformat()
        if properties.source_updated_at is not None
        else None
    )
    reviewed = {
        "origin": "operator_reviewed",
        "provider": properties.source_provider,
        "reviewed_by": reviewed_by.strip(),
        "source_updated_at": source_updated_at,
    }
    return {
        "catalog_import": {
            **reviewed,
            "imported_at": imported_at.isoformat(),
        },
        "name": dict(reviewed),
        "location": dict(reviewed),
        "connectors": dict(reviewed),
    }


def _invalidate_station_runtime_snapshots(connection, station_id) -> int:
    """Remove snapshots whose per-port topology no longer matches the catalog."""
    connection.execute(
        text("DELETE FROM port_status WHERE port_id IN "
             "(SELECT id FROM ports WHERE station_id=:station_id)"),
        {"station_id": station_id},
    )
    connection.execute(
        text("DELETE FROM station_live_metrics WHERE station_id=:station_id"),
        {"station_id": station_id},
    )
    # API status and recommendation paths read this table as the latest runtime
    # snapshot. Remove all snapshots so an older one cannot become current after
    # deleting only the newest record. Aggregated occupancy history is retained.
    result = connection.execute(
        text("DELETE FROM station_telemetry_snapshots WHERE station_id=:station_id"),
        {"station_id": station_id},
    )
    return max(result.rowcount, 0)


def _assert_provider_station_ref_owner(
    connection: Any, *, provider: str, external_id: str, station_id: uuid.UUID
) -> None:
    existing_station_id = connection.execute(
        text(
            "SELECT station_id FROM station_external_refs "
            "WHERE provider=:provider AND external_id=:external_id FOR UPDATE"
        ),
        {"provider": provider, "external_id": external_id},
    ).scalar_one_or_none()
    if existing_station_id is not None and existing_station_id != station_id:
        raise ValueError(
            f"provider station reference {provider}/{external_id} already belongs "
            "to a different station; review and resolve the existing mapping first"
        )


def _upsert_provider_station_ref(
    connection: Any,
    *,
    reference_id: uuid.UUID,
    station_id: uuid.UUID,
    provider: str,
    external_id: str,
    retrieved_at: datetime,
) -> None:
    saved_station_id = connection.execute(
        text(
            "INSERT INTO station_external_refs "
            "(id, station_id, provider, external_id, retrieved_at, is_primary) "
            "VALUES (:id, :station_id, :provider, :external_id, :retrieved_at, true) "
            "ON CONFLICT (provider, external_id) DO UPDATE SET "
            "station_id=EXCLUDED.station_id, retrieved_at=EXCLUDED.retrieved_at, "
            "is_primary=true WHERE station_external_refs.station_id="
            "EXCLUDED.station_id RETURNING station_id"
        ),
        {
            "id": reference_id,
            "station_id": station_id,
            "provider": provider,
            "external_id": external_id,
            "retrieved_at": retrieved_at,
        },
    ).scalar_one_or_none()
    if saved_station_id is None:
        raise ValueError(
            f"provider station reference {provider}/{external_id} was concurrently "
            "assigned to a different station"
        )


def _validate_release_catalog(
    stations: StationCollection, vehicles: tuple[ReleaseCatalogVehicle, ...]
) -> None:
    eligibility_issues: list[str] = []
    vehicle_ids = [vehicle.vehicle_id for vehicle in vehicles]
    if len(vehicle_ids) != len(set(vehicle_ids)):
        eligibility_issues.append("release vehicle catalog contains duplicate vehicle_id values")
    external_station_ids: dict[tuple[str, str], str] = {}
    for station in stations.features:
        properties = station.properties
        provider_station_id = properties.provider_station_id
        if not properties.source_provider.strip():
            eligibility_issues.append(
                f"station {station.station_id} requires source_provider"
            )
        if "synthetic" in properties.source_provider.casefold():
            eligibility_issues.append(
                f"station {station.station_id} has a synthetic source provider"
            )
        if provider_station_id is not None:
            if not provider_station_id.strip():
                eligibility_issues.append(
                    f"station {station.station_id} has an empty provider_station_id"
                )
            else:
                external_key = (
                    properties.source_provider.strip(),
                    provider_station_id.strip(),
                )
                existing_station_id = external_station_ids.get(external_key)
                if existing_station_id is not None and existing_station_id != station.station_id:
                    eligibility_issues.append(
                        f"provider station reference {properties.source_provider}/"
                        f"{provider_station_id} is assigned to multiple stations: "
                        f"{existing_station_id}, {station.station_id}"
                    )
                else:
                    external_station_ids[external_key] = station.station_id
        if properties.synthetic_fields:
            eligibility_issues.append(
                f"station {station.station_id} has synthetic fields: "
                + ", ".join(properties.synthetic_fields)
            )
        for connector in properties.connectors:
            if "synthetic" in connector.source.lower():
                eligibility_issues.append(
                    f"station {station.station_id} has synthetic connectors"
                )
            try:
                connector_code = _connector_code(connector.type)
            except ValueError as exc:
                eligibility_issues.append(f"station {station.station_id}: {exc}")
                continue
            if CONNECTORS[connector_code][1] != connector.current:
                eligibility_issues.append(
                    f"station {station.station_id} connector current type does not match "
                    f"{connector.type}"
                )
        if properties.source_updated_at is None:
            eligibility_issues.append(
                f"station {station.station_id} requires source_updated_at"
            )
        elif properties.source_updated_at.tzinfo is None:
            eligibility_issues.append(
                f"station {station.station_id} source_updated_at requires a timezone"
            )

    for vehicle in vehicles:
        eligibility_issues.extend(_validate_vehicle_field_provenance(vehicle))
        if (
            vehicle.is_synthetic
            or vehicle.synthetic_fields
            or "synthetic" in vehicle.source.casefold()
        ):
            eligibility_issues.append(
                f"vehicle {vehicle.vehicle_id} contains synthetic data"
            )
        if vehicle.max_ac_power_kw <= 0 and vehicle.max_dc_power_kw <= 0:
            eligibility_issues.append(
                f"vehicle {vehicle.vehicle_id} requires a positive charging power"
            )
        if (
            vehicle.usable_battery_kwh is not None
            and vehicle.usable_battery_kwh > vehicle.battery_capacity_kwh
        ):
            eligibility_issues.append(
                f"vehicle {vehicle.vehicle_id} usable capacity exceeds battery capacity"
            )
        if not 0 <= vehicle.reserve_soc < vehicle.default_target_soc <= 1:
            eligibility_issues.append(
                f"vehicle {vehicle.vehicle_id} SOC policy is inconsistent"
            )
        if not vehicle.source.strip():
            eligibility_issues.append(
                f"vehicle {vehicle.vehicle_id} requires a source reference"
            )
        if not vehicle.ac_connectors and not vehicle.dc_connectors:
            eligibility_issues.append(
                f"vehicle {vehicle.vehicle_id} requires a compatible connector"
            )
        if vehicle.ac_connectors and vehicle.max_ac_power_kw <= 0:
            eligibility_issues.append(
                f"vehicle {vehicle.vehicle_id} has AC connectors without AC power"
            )
        if vehicle.dc_connectors and vehicle.max_dc_power_kw <= 0:
            eligibility_issues.append(
                f"vehicle {vehicle.vehicle_id} has DC connectors without DC power"
            )
        for current, codes in (("AC", vehicle.ac_connectors), ("DC", vehicle.dc_connectors)):
            for raw_code in codes:
                try:
                    code = _connector_code(raw_code)
                except ValueError as exc:
                    eligibility_issues.append(f"vehicle {vehicle.vehicle_id}: {exc}")
                    continue
                if CONNECTORS[code][1] != current:
                    eligibility_issues.append(
                        f"vehicle {vehicle.vehicle_id} lists {raw_code} under "
                        "the wrong current type"
                    )

    eligibility_issues = list(dict.fromkeys(eligibility_issues))
    if eligibility_issues:
        details = "\n- ".join(eligibility_issues)
        raise ValueError(f"release catalog is not eligible:\n- {details}")


def _validated_port_external_ids(
    stations: StationCollection,
    port_external_ids: dict[str, dict[str, str | None]] | None,
) -> dict[str, dict[str, str | None]]:
    """Validate operator mappings from generated port labels to provider IDs."""
    if port_external_ids is None:
        return {}
    if not isinstance(port_external_ids, dict):
        raise ValueError("port_external_ids must be an object keyed by station ID")
    stations_by_id = {station.station_id: station for station in stations.features}
    validated: dict[str, dict[str, str | None]] = {}
    for station_id, mappings in port_external_ids.items():
        if not isinstance(station_id, str):
            raise ValueError("port mapping station IDs and labels must be strings")
        station = stations_by_id.get(station_id)
        if station is None:
            raise ValueError(f"port mapping references unknown station {station_id}")
        if not isinstance(mappings, dict):
            raise ValueError(f"port mapping for station {station_id} must be an object")
        if any(not isinstance(label, str) for label in mappings):
            raise ValueError("port mapping station IDs and labels must be strings")
        labels = {
            label
            for _connector, _connector_code, label in _expanded_station_ports(
                station.properties.connectors
            )
        }
        unknown_labels = set(mappings) - labels
        if unknown_labels:
            raise ValueError(
                f"port mapping for station {station_id} has unknown labels: "
                f"{sorted(unknown_labels)}"
            )
        normalized: dict[str, str | None] = {}
        for label, external_id in mappings.items():
            if external_id is None:
                normalized[label] = None
                continue
            if not isinstance(external_id, str) or not external_id.strip() or len(
                external_id.strip()
            ) > 128:
                raise ValueError(
                    f"port mapping for station {station_id} requires null or "
                    "nonempty provider IDs of at most 128 characters"
                )
            normalized[label] = external_id.strip()
        provider_ids = [value for value in normalized.values() if value is not None]
        if len(set(provider_ids)) != len(provider_ids):
            raise ValueError(
                f"port mapping for station {station_id} contains duplicate provider IDs"
            )
        validated[station_id] = normalized
    return validated


def load_release_catalog(
    stations_path: Path, vehicles_path: Path
) -> tuple[StationCollection, tuple[ReleaseCatalogVehicle, ...]]:
    """Load current API catalog contracts and reject synthetic/unreviewed candidates."""
    station_data = json.loads(stations_path.read_text(encoding="utf-8"))
    vehicle_data = json.loads(vehicles_path.read_text(encoding="utf-8"))
    stations = StationCollection.model_validate(station_data)
    if not isinstance(vehicle_data, list) or not vehicle_data:
        raise ValueError("release vehicle catalog must be a nonempty JSON array")
    vehicles = tuple(ReleaseCatalogVehicle.model_validate(item) for item in vehicle_data)
    _validate_release_catalog(stations, vehicles)
    return stations, vehicles


def import_release_catalog(
    engine: Engine | None,
    stations: StationCollection,
    vehicles: tuple[ReleaseCatalogVehicle, ...],
    *,
    apply: bool = False,
    reviewed_by: str | None = None,
    replace_snapshot: bool = False,
    port_external_ids: dict[str, dict[str, str | None]] | None = None,
) -> dict[str, int | bool]:
    """Preview by default; optionally reconcile complete reviewed source snapshots."""
    _validate_release_catalog(stations, vehicles)
    validated_port_external_ids = _validated_port_external_ids(
        stations, port_external_ids
    )
    mapped_port_ids = sum(
        external_id is not None
        for mappings in validated_port_external_ids.values()
        for external_id in mappings.values()
    )
    station_count = len(stations.features)
    vehicle_count = len(vehicles)
    if not apply:
        return {
            "applied": False,
            "stations": station_count,
            "vehicles": vehicle_count,
            "replace_snapshot": replace_snapshot,
            "mapped_port_ids": mapped_port_ids,
        }
    if engine is None:
        raise ValueError("a database engine is required when applying a catalog")
    if reviewed_by is None or not reviewed_by.strip():
        raise ValueError("reviewed_by is required when applying a release catalog")
    if replace_snapshot and not stations.features:
        raise ValueError(
            "replace_snapshot requires at least one station so the provider scope "
            "can be established safely"
        )
    if replace_snapshot and not vehicles:
        raise ValueError(
            "replace_snapshot requires at least one vehicle to avoid deactivating "
            "the entire reviewed vehicle catalog"
        )

    now = datetime.now(UTC)
    deactivated_stations = 0
    deactivated_vehicles = 0
    invalidated_telemetry_snapshots = 0
    with engine.begin() as connection:
        if replace_snapshot:
            providers = sorted(
                {station.properties.source_provider for station in stations.features}
            )
            station_codes = [station.station_id for station in stations.features]
            vehicle_codes = [vehicle.vehicle_id for vehicle in vehicles]
            deactivated_stations = connection.execute(
                text(
                    "UPDATE stations SET is_active=false "
                    "WHERE is_active IS TRUE "
                    "AND provenance->'catalog_import'->>'origin'='operator_reviewed' "
                    "AND provenance->'catalog_import'->>'provider'=ANY(:providers) "
                    "AND NOT (code=ANY(:station_codes))"
                ),
                {"providers": providers, "station_codes": station_codes},
            ).rowcount
            deactivated_vehicles = connection.execute(
                text(
                    "UPDATE vehicle_models SET is_active=false "
                    "WHERE is_active IS TRUE "
                    "AND provenance->'catalog_import'->>'origin'='operator_reviewed' "
                    "AND NOT (code=ANY(:vehicle_codes))"
                ),
                {"vehicle_codes": vehicle_codes},
            ).rowcount

        for code, (display_name, current) in CONNECTORS.items():
            connection.execute(
                text(
                    "INSERT INTO connector_types (code, display_name, current_type) "
                    "VALUES (:code, :display_name, CAST(:current AS current_type)) "
                    "ON CONFLICT (code) DO UPDATE SET display_name=EXCLUDED.display_name, "
                    "current_type=EXCLUDED.current_type"
                ),
                {"code": code, "display_name": display_name, "current": current},
            )

        for station in stations.features:
            properties = station.properties
            station_uuid = uuid.uuid5(NAMESPACE, "station:" + properties.station_id)
            source_at = properties.source_updated_at
            provenance = _station_provenance_for_import(
                properties, reviewed_by=reviewed_by, imported_at=now
            )
            connection.execute(
                text(
                    "INSERT INTO stations (id, code, name, address, operator_name, location, "
                    "opening_hours, access_level, access_note, is_active, provenance) "
                    "VALUES (:id, :code, :name, :address, :operator, "
                    "ST_SetSRID(ST_MakePoint(:longitude, :latitude),4326)::geography, "
                    "CAST(:opening_hours AS jsonb), CAST(:access AS access_level), "
                    ":access_note, true, CAST(:provenance AS jsonb)) "
                    "ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, "
                    "address=EXCLUDED.address, operator_name=EXCLUDED.operator_name, "
                    "location=EXCLUDED.location, opening_hours=EXCLUDED.opening_hours, "
                    "access_level=EXCLUDED.access_level, access_note=EXCLUDED.access_note, "
                    "is_active=true, provenance=EXCLUDED.provenance"
                ),
                {
                    "id": station_uuid,
                    "code": properties.station_id,
                    "name": properties.name,
                    "address": properties.address,
                    "operator": properties.operator,
                    "longitude": station.geometry.coordinates[0],
                    "latitude": station.geometry.coordinates[1],
                    "opening_hours": json.dumps(properties.opening_hours),
                    "access": properties.access,
                    "access_note": "\n".join(properties.notes) or None,
                    "provenance": json.dumps(provenance),
                },
            )
            station_uuid = connection.execute(
                text("SELECT id FROM stations WHERE code=:code"),
                {"code": properties.station_id},
            ).scalar_one()
            current_ports = connection.execute(
                text(
                    "SELECT label, connector_code, max_power_kw, external_id FROM ports "
                    "WHERE station_id=:station_id AND is_active"
                ),
                {"station_id": station_uuid},
            ).mappings().all()
            existing_external_ids = {
                row["label"]: row["external_id"] for row in current_ports
            }
            station_external_ids = validated_port_external_ids.get(
                properties.station_id, {}
            )
            desired_ports = {
                (
                    label,
                    connector_code,
                    round(connector.max_power_kw, 2),
                    (
                        station_external_ids[label]
                        if label in station_external_ids
                        else existing_external_ids.get(label)
                    ),
                )
                for connector, connector_code, label in _expanded_station_ports(
                    properties.connectors
                )
            }
            existing_ports = {
                (
                    row["label"],
                    row["connector_code"],
                    round(float(row["max_power_kw"]), 2),
                    row["external_id"],
                )
                for row in current_ports
            }
            effective_external_ids = [port[3] for port in desired_ports if port[3]]
            if len(effective_external_ids) != len(set(effective_external_ids)):
                raise ValueError(
                    f"station {properties.station_id} has duplicate provider port IDs"
                )
            if existing_ports != desired_ports:
                invalidated_telemetry_snapshots += (
                    _invalidate_station_runtime_snapshots(connection, station_uuid)
                )
            connection.execute(
                text("UPDATE ports SET is_active=false WHERE station_id=:station_id"),
                {"station_id": station_uuid},
            )
            if properties.provider_station_id:
                _assert_provider_station_ref_owner(
                    connection,
                    provider=properties.source_provider,
                    external_id=properties.provider_station_id,
                    station_id=station_uuid,
                )
                _upsert_provider_station_ref(
                    connection,
                    reference_id=uuid.uuid5(
                        NAMESPACE,
                        f"external:{properties.source_provider}:"
                        f"{properties.provider_station_id}",
                    ),
                    station_id=station_uuid,
                    provider=properties.source_provider,
                    external_id=properties.provider_station_id,
                    retrieved_at=now,
                )

            for connector, connector_code, label in _expanded_station_ports(
                properties.connectors
            ):
                port_id = uuid.uuid5(
                    NAMESPACE, f"port:{properties.station_id}:{label}"
                )
                connection.execute(
                    text(
                        "INSERT INTO ports (id, station_id, connector_code, external_id, label, "
                        "max_power_kw, is_active, data_origin, provenance) "
                        "VALUES (:id, :station_id, :connector, :external_id, :label, :power, true, "
                        "'observed', CAST(:provenance AS jsonb)) "
                        "ON CONFLICT (station_id, label) DO UPDATE SET "
                        "connector_code=EXCLUDED.connector_code, "
                        "max_power_kw=EXCLUDED.max_power_kw, is_active=true, "
                        "external_id=CASE WHEN :has_external_id_mapping "
                        "THEN EXCLUDED.external_id "
                        "ELSE COALESCE(EXCLUDED.external_id, ports.external_id) END, "
                        "data_origin='observed', provenance=CASE "
                        "WHEN EXCLUDED.provenance ? 'port_mapping' THEN EXCLUDED.provenance "
                        "WHEN ports.provenance ? 'port_mapping' THEN "
                        "EXCLUDED.provenance || jsonb_build_object("
                        "'port_mapping', ports.provenance->'port_mapping') "
                        "ELSE EXCLUDED.provenance END"
                    ),
                    {
                        "id": port_id,
                        "station_id": station_uuid,
                        "connector": connector_code,
                        "external_id": station_external_ids.get(label),
                        "has_external_id_mapping": label in station_external_ids,
                        "label": label,
                        "power": connector.max_power_kw,
                        "provenance": json.dumps(
                            {
                                "origin": "operator_reviewed",
                                "provider": properties.source_provider,
                                "source": connector.source,
                                "reviewed_by": reviewed_by.strip(),
                                "source_updated_at": source_at.isoformat() if source_at else None,
                                **(
                                    {
                                        "port_mapping": {
                                            "origin": "operator_reviewed",
                                            "provider": properties.source_provider,
                                            "reviewed_by": reviewed_by.strip(),
                                            "imported_at": now.isoformat(),
                                            "external_id": station_external_ids[label],
                                        }
                                    }
                                    if label in station_external_ids
                                    else {}
                                ),
                            }
                        ),
                    },
                )
            connection.execute(
                text("UPDATE station_amenities SET is_available=false WHERE station_id=:id"),
                {"id": station_uuid},
            )
            for amenity in properties.amenities:
                connection.execute(
                    text(
                        "INSERT INTO station_amenities "
                        "(id, station_id, amenity_code, is_available, verified_at, provenance) "
                        "VALUES (:id, :station_id, :code, true, :verified_at, "
                        "CAST(:provenance AS jsonb)) ON CONFLICT (station_id, amenity_code) "
                        "DO UPDATE SET is_available=true, verified_at=EXCLUDED.verified_at, "
                        "provenance=EXCLUDED.provenance"
                    ),
                    {
                        "id": uuid.uuid5(NAMESPACE, f"amenity:{properties.station_id}:{amenity}"),
                        "station_id": station_uuid,
                        "code": amenity,
                        "verified_at": source_at,
                        "provenance": json.dumps(
                            {
                                "origin": "operator_reviewed",
                                "provider": properties.source_provider,
                                "reviewed_by": reviewed_by.strip(),
                                "source_updated_at": source_at.isoformat() if source_at else None,
                            }
                        ),
                    },
                )

        for vehicle in vehicles:
            vehicle_uuid = uuid.uuid5(NAMESPACE, "vehicle:" + vehicle.vehicle_id)
            connector_codes = {
                _connector_code(code)
                for code in (*vehicle.ac_connectors, *vehicle.dc_connectors)
            }
            provenance = _vehicle_provenance_for_import(
                vehicle, reviewed_by=reviewed_by, imported_at=now
            )
            connection.execute(
                text(
                    "INSERT INTO vehicle_models (id, code, brand, model, variant, market, "
                    "battery_kwh, usable_battery_kwh, consumption_kwh_per_100km, "
                    "max_ac_kw, max_dc_kw, is_active, provenance) "
                    "VALUES (:id, :code, :brand, :model, :variant, 'VN', :battery, "
                    ":usable_battery, :consumption, :max_ac, :max_dc, true, "
                    "CAST(:provenance AS jsonb)) ON CONFLICT (code) DO UPDATE SET "
                    "brand=EXCLUDED.brand, model=EXCLUDED.model, variant=EXCLUDED.variant, "
                    "market='VN', battery_kwh=EXCLUDED.battery_kwh, "
                    "usable_battery_kwh=EXCLUDED.usable_battery_kwh, "
                    "consumption_kwh_per_100km=EXCLUDED.consumption_kwh_per_100km, "
                    "max_ac_kw=EXCLUDED.max_ac_kw, max_dc_kw=EXCLUDED.max_dc_kw, "
                    "is_active=true, provenance=EXCLUDED.provenance"
                ),
                {
                    "id": vehicle_uuid,
                    "code": vehicle.vehicle_id,
                    "brand": vehicle.make,
                    "model": vehicle.model,
                    "variant": vehicle.variant,
                    "battery": vehicle.battery_capacity_kwh,
                    "usable_battery": vehicle.usable_battery_kwh,
                    "consumption": vehicle.consumption_wh_km / 10,
                    "max_ac": vehicle.max_ac_power_kw or None,
                    "max_dc": vehicle.max_dc_power_kw or None,
                    "provenance": json.dumps(provenance),
                },
            )
            vehicle_uuid = connection.execute(
                text("SELECT id FROM vehicle_models WHERE code=:code"),
                {"code": vehicle.vehicle_id},
            ).scalar_one()
            connection.execute(
                text("DELETE FROM vehicle_connectors WHERE vehicle_model_id=:id"),
                {"id": vehicle_uuid},
            )
            for connector_code in sorted(connector_codes):
                connection.execute(
                    text(
                        "INSERT INTO vehicle_connectors (vehicle_model_id, connector_code) "
                        "VALUES (:id, :connector)"
                    ),
                    {"id": vehicle_uuid, "connector": connector_code},
                )

    return {
        "applied": True,
        "stations": station_count,
        "vehicles": vehicle_count,
        "replace_snapshot": replace_snapshot,
        "deactivated_stations": deactivated_stations,
        "deactivated_vehicles": deactivated_vehicles,
        "invalidated_telemetry_snapshots": invalidated_telemetry_snapshots,
        "mapped_port_ids": mapped_port_ids,
    }
