from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIONS_PATH = ROOT / "data_platform" / "data" / "static" / "stations.geojson"
VEHICLES_PATH = ROOT / "data_platform" / "data" / "demo" / "vehicles.json"
REPORT_PATH = ROOT / "data_platform" / "data" / "validation" / "static_data_validation_report.md"

STATION_REQUIRED = {
    "station_id",
    "name",
    "address",
    "total_ports",
    "connectors",
    "access",
    "notes",
    "source_provider",
    "synthetic_fields",
}
VEHICLE_REQUIRED = {
    "vehicle_id",
    "make",
    "model",
    "battery_capacity_kwh",
    "max_ac_power_kw",
    "max_dc_power_kw",
    "ac_connectors",
    "dc_connectors",
    "consumption_wh_km",
    "reserve_soc",
    "default_target_soc",
    "charging_efficiency",
    "source",
    "is_synthetic",
    "synthetic_fields",
}
DEMO_BOUNDS = {
    "min_lon": 106.65,
    "max_lon": 106.75,
    "min_lat": 10.70,
    "max_lat": 10.82,
}


def load_json(path: Path, errors: list[str]):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"Cannot read {path.relative_to(ROOT)}: {exc}")
        return None


def positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def validate_stations(data: object, errors: list[str], warnings: list[str]) -> list[dict]:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        errors.append("stations.geojson must be a GeoJSON FeatureCollection")
        return []
    features = data.get("features")
    if not isinstance(features, list) or not features:
        errors.append("stations.geojson.features must be a non-empty array")
        return []

    seen: set[str] = set()
    valid_features: list[dict] = []
    for index, feature in enumerate(features):
        label = f"stations.features[{index}]"
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            errors.append(f"{label} must be a GeoJSON Feature")
            continue
        geometry = feature.get("geometry")
        coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if not (
            isinstance(geometry, dict)
            and geometry.get("type") == "Point"
            and isinstance(coordinates, list)
            and len(coordinates) == 2
            and all(isinstance(value, (int, float)) for value in coordinates)
        ):
            errors.append(f"{label}.geometry must be a Point with [lon, lat]")
            continue
        lon, lat = coordinates
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            errors.append(f"{label} has invalid WGS84 coordinates")
        if not (
            DEMO_BOUNDS["min_lon"] <= lon <= DEMO_BOUNDS["max_lon"]
            and DEMO_BOUNDS["min_lat"] <= lat <= DEMO_BOUNDS["max_lat"]
        ):
            errors.append(f"{label} is outside the approved HCMC demo bounds")

        props = feature.get("properties")
        if not isinstance(props, dict):
            errors.append(f"{label}.properties must be an object")
            continue
        missing = sorted(STATION_REQUIRED - props.keys())
        if missing:
            errors.append(f"{label} is missing fields: {', '.join(missing)}")
            continue
        station_id = props["station_id"]
        if not isinstance(station_id, str) or not station_id:
            errors.append(f"{label}.station_id must be a non-empty string")
        elif station_id in seen:
            errors.append(f"Duplicate station_id: {station_id}")
        else:
            seen.add(station_id)

        total_ports = props["total_ports"]
        if not isinstance(total_ports, int) or isinstance(total_ports, bool) or total_ports <= 0:
            errors.append(f"{station_id}.total_ports must be a positive integer")
        connectors = props["connectors"]
        connector_count = 0
        if not isinstance(connectors, list) or not connectors:
            errors.append(f"{station_id}.connectors must be a non-empty array")
        else:
            for connector_index, connector in enumerate(connectors):
                connector_label = f"{station_id}.connectors[{connector_index}]"
                if not isinstance(connector, dict):
                    errors.append(f"{connector_label} must be an object")
                    continue
                if connector.get("current") not in {"AC", "DC"}:
                    errors.append(f"{connector_label}.current must be AC or DC")
                if not isinstance(connector.get("type"), str) or not connector["type"]:
                    errors.append(f"{connector_label}.type must be a non-empty string")
                if not positive_number(connector.get("max_power_kw")):
                    errors.append(f"{connector_label}.max_power_kw must be positive")
                count = connector.get("count")
                if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                    errors.append(f"{connector_label}.count must be a positive integer")
                else:
                    connector_count += count
                if connector.get("source") not in {"real", "synthetic"}:
                    errors.append(f"{connector_label}.source must be real or synthetic")
            if isinstance(total_ports, int) and connector_count != total_ports:
                errors.append(
                    f"{station_id}: connector count {connector_count} != total_ports {total_ports}"
                )

        synthetic_fields = props["synthetic_fields"]
        if not isinstance(synthetic_fields, list) or not all(
            isinstance(field, str) and field in props for field in synthetic_fields
        ):
            errors.append(f"{station_id}.synthetic_fields must reference existing properties")
        if any(c.get("source") == "synthetic" for c in connectors if isinstance(c, dict)) and (
            not isinstance(synthetic_fields, list) or "connectors" not in synthetic_fields
        ):
            errors.append(f"{station_id} has synthetic connector data without provenance")
        if props["access"] not in {"public", "customers", "private", "unknown"}:
            errors.append(f"{station_id}.access has an unsupported value")
        notes = props["notes"]
        if not isinstance(notes, list) or not all(
            isinstance(note, str) and note.strip() for note in notes
        ):
            errors.append(f"{station_id}.notes must be an array of non-empty strings")
        if props["access"] != "public" and isinstance(notes, list) and not notes:
            errors.append(f"{station_id} must explain its restricted/unknown access in notes")
        if props.get("provider_station_id") is None:
            warnings.append(f"{station_id} has no provider_station_id")
        valid_features.append(feature)
    return valid_features


def validate_vehicles(data: object, errors: list[str]) -> list[dict]:
    if not isinstance(data, list) or not data:
        errors.append("vehicles.json must be a non-empty top-level array")
        return []
    seen: set[str] = set()
    valid_vehicles: list[dict] = []
    for index, vehicle in enumerate(data):
        label = f"vehicles[{index}]"
        if not isinstance(vehicle, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = sorted(VEHICLE_REQUIRED - vehicle.keys())
        if missing:
            errors.append(f"{label} is missing fields: {', '.join(missing)}")
            continue
        vehicle_id = vehicle["vehicle_id"]
        if not isinstance(vehicle_id, str) or not vehicle_id:
            errors.append(f"{label}.vehicle_id must be a non-empty string")
        elif vehicle_id in seen:
            errors.append(f"Duplicate vehicle_id: {vehicle_id}")
        else:
            seen.add(vehicle_id)
        for field in (
            "battery_capacity_kwh",
            "max_ac_power_kw",
            "max_dc_power_kw",
            "consumption_wh_km",
            "charging_efficiency",
        ):
            if not positive_number(vehicle[field]):
                errors.append(f"{vehicle_id}.{field} must be positive")
        usable = vehicle.get("usable_battery_kwh")
        if usable is not None and (
            not positive_number(usable) or usable > vehicle["battery_capacity_kwh"]
        ):
            errors.append(f"{vehicle_id}.usable_battery_kwh must be positive and <= capacity")
        for field in ("reserve_soc", "default_target_soc", "charging_efficiency"):
            value = vehicle[field]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 1:
                errors.append(f"{vehicle_id}.{field} must be within [0, 1]")
        if vehicle["default_target_soc"] <= vehicle["reserve_soc"]:
            errors.append(f"{vehicle_id}.default_target_soc must exceed reserve_soc")
        for field in ("ac_connectors", "dc_connectors"):
            connectors = vehicle[field]
            if not isinstance(connectors, list) or not all(
                isinstance(connector, str) and connector for connector in connectors
            ):
                errors.append(f"{vehicle_id}.{field} must be an array of non-empty strings")
        synthetic_fields = vehicle["synthetic_fields"]
        if not isinstance(synthetic_fields, list) or not all(
            isinstance(field, str) and field in vehicle for field in synthetic_fields
        ):
            errors.append(f"{vehicle_id}.synthetic_fields must reference existing fields")
        valid_vehicles.append(vehicle)
    if len(valid_vehicles) < 3:
        errors.append("vehicles.json must contain at least three vehicle profiles")
    return valid_vehicles


def validate_coverage(stations: list[dict], vehicles: list[dict], errors: list[str]) -> None:
    station_types = {
        connector["type"]
        for station in stations
        for connector in station["properties"].get("connectors", [])
        if isinstance(connector, dict) and isinstance(connector.get("type"), str)
    }
    matches = []
    mismatches = []
    for vehicle in vehicles:
        vehicle_types = set(vehicle["ac_connectors"] + vehicle["dc_connectors"])
        (matches if station_types & vehicle_types else mismatches).append(vehicle["vehicle_id"])
    if not matches:
        errors.append("No vehicle is compatible with any demo station")
    if not mismatches:
        errors.append("No vehicle provides the required incompatible-connector test case")


def write_report(errors: list[str], warnings: list[str], station_count: int, vehicle_count: int) -> None:
    status = "PASS" if not errors else "FAIL"
    lines = [
        "# Static data validation report",
        "",
        f"**Result:** `{status}`",
        "",
        f"- Stations checked: {station_count}",
        f"- Vehicles checked: {vehicle_count}",
        f"- Errors: {len(errors)}",
        f"- Warnings: {len(warnings)}",
        "",
        "## Errors",
        "",
        *(f"- {error}" for error in errors),
    ]
    if not errors:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- None")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    station_data = load_json(STATIONS_PATH, errors)
    vehicle_data = load_json(VEHICLES_PATH, errors)
    stations = validate_stations(station_data, errors, warnings) if station_data is not None else []
    vehicles = validate_vehicles(vehicle_data, errors) if vehicle_data is not None else []
    if stations and vehicles:
        validate_coverage(stations, vehicles, errors)
    write_report(errors, warnings, len(stations), len(vehicles))
    print(f"Static data validation: {'PASS' if not errors else 'FAIL'}")
    print(f"Report: {REPORT_PATH}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
