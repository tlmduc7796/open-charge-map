#!/usr/bin/env python3
"""Validate Phase 1 artifacts and write the full data validation report."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data_platform" / "data"
REPORT = DATA_ROOT / "validation" / "full_data_validation_report.md"
errors: list[str] = []
warnings: list[str] = []
checks: list[str] = []


def error(message: str) -> None:
    errors.append(message)


def warning(message: str) -> None:
    warnings.append(message)


def checked(message: str) -> None:
    checks.append(message)


def load_json(relative_path: str):
    path = ROOT / relative_path
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        error(f"Missing required file: `{relative_path}`")
    except json.JSONDecodeError as exc:
        error(f"Invalid JSON in `{relative_path}`: {exc}")
    return None


def parse_datetime(value: object, context: str) -> datetime | None:
    if not isinstance(value, str):
        error(f"{context} must be an ISO-8601 string")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        error(f"{context} is not valid ISO-8601: {value}")
        return None
    if parsed.tzinfo is None:
        error(f"{context} must include a timezone: {value}")
    return parsed


def unique_ids(records: list, key: str, context: str) -> set[str]:
    values: list[str] = []
    for index, record in enumerate(records):
        value = record.get(key) if isinstance(record, dict) else None
        if not isinstance(value, str) or not value:
            error(f"{context}[{index}].{key} must be a non-empty string")
        else:
            values.append(value)
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        error(f"Duplicate {key} in {context}: {duplicates}")
    return set(values)


def validate_raw_source() -> None:
    manifest = load_json("data_platform/data/ml/urbanev/source_manifest.json")
    if not isinstance(manifest, dict):
        return
    archive_name = manifest.get("archive")
    archive = DATA_ROOT / "ml" / "urbanev" / "raw" / str(archive_name)
    if not archive.is_file():
        error(f"UrbanEV raw archive missing: `{archive.relative_to(ROOT)}`")
        return
    if archive.stat().st_size != manifest.get("size_bytes"):
        error("UrbanEV raw archive size differs from source manifest")
    digest = hashlib.sha256()
    with archive.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != manifest.get("sha256"):
        error("UrbanEV raw archive SHA-256 differs from source manifest")
    if manifest.get("zip_test") != "PASS":
        error("UrbanEV archive integrity is not PASS in source manifest")
    if not (DATA_ROOT / "ml" / "urbanev" / "source_manifest.md").is_file():
        error("Missing human-readable UrbanEV source manifest")
    checked(f"UrbanEV archive verified: {archive.stat().st_size} bytes, SHA-256 matched")


def validate_all() -> None:
    stations_doc = load_json("data_platform/data/static/stations.geojson")
    vehicles = load_json("data_platform/data/demo/vehicles.json")
    statuses = load_json("data_platform/data/runtime/station_status.json")
    arrivals = load_json("data_platform/data/runtime/planned_arrivals.json")
    events = load_json("data_platform/data/demo/demo_events.json")
    scenarios = load_json("data_platform/data/demo/demo_scenarios.json")
    assumptions = load_json("data_platform/data/demo/queue_assumptions.json")
    if any(value is None for value in [stations_doc, vehicles, statuses, arrivals, events, scenarios, assumptions]):
        return
    if not all(isinstance(value, list) for value in [vehicles, statuses, arrivals, events, scenarios]):
        error("vehicles, status, arrivals, events and scenarios must use top-level arrays")
        return

    features = stations_doc.get("features", []) if isinstance(stations_doc, dict) else []
    station_by_id = {
        item["properties"]["station_id"]: item
        for item in features
        if isinstance(item, dict) and isinstance(item.get("properties"), dict) and item["properties"].get("station_id")
    }
    station_ids = set(station_by_id)
    public_station_ids = {
        station_id
        for station_id, feature in station_by_id.items()
        if feature["properties"].get("access") == "public"
    }
    vehicle_ids = unique_ids(vehicles, "vehicle_id", "vehicles")
    status_ids = unique_ids(statuses, "station_id", "station_status")
    arrival_ids = unique_ids(arrivals, "arrival_id", "planned_arrivals")
    event_ids = unique_ids(events, "event_id", "demo_events")
    scenario_ids = unique_ids(scenarios, "scenario_id", "demo_scenarios")
    del arrival_ids

    if status_ids != station_ids:
        error(f"station_status station set differs from static master: missing={sorted(station_ids-status_ids)}, extra={sorted(status_ids-station_ids)}")
    status_by_id = {record["station_id"]: record for record in statuses if record.get("station_id")}
    for status in statuses:
        station_id = status.get("station_id", "<unknown>")
        if station_id not in station_ids:
            error(f"station_status references unknown station: {station_id}")
            continue
        static_ports = station_by_id[station_id]["properties"]["total_ports"]
        total = status.get("total_ports")
        operational = status.get("operational_ports")
        occupied = status.get("occupied_ports")
        available = status.get("available_ports")
        offline = status.get("offline_ports")
        values = [total, operational, occupied, available, offline]
        if not all(isinstance(value, int) and value >= 0 for value in values):
            error(f"{station_id}: port counts must be non-negative integers")
            continue
        if total != static_ports:
            error(f"{station_id}: runtime total_ports {total} != static {static_ports}")
        if occupied + available != operational:
            error(f"{station_id}: occupied + available != operational")
        if operational + offline != total:
            error(f"{station_id}: operational + offline != total")
        ratio = status.get("occupancy_ratio")
        expected_ratio = occupied / operational if operational else None
        if ratio is None if expected_ratio is not None else ratio is not None:
            error(f"{station_id}: occupancy_ratio nullability is invalid")
        elif expected_ratio is not None and (not isinstance(ratio, (int, float)) or not math.isclose(ratio, expected_ratio, abs_tol=1e-9)):
            error(f"{station_id}: occupancy_ratio does not match occupied/operational")
        if not isinstance(status.get("queue_length"), int) or status["queue_length"] < 0:
            error(f"{station_id}: queue_length must be a non-negative integer")
        if not isinstance(status.get("avg_session_duration_min"), (int, float)) or status["avg_session_duration_min"] <= 0:
            error(f"{station_id}: avg_session_duration_min must be positive")
        parse_datetime(status.get("timestamp"), f"{station_id}.timestamp")
    checked(f"Runtime capacity invariants checked for {len(statuses)} stations")

    route_by_id: dict[str, dict] = {}
    route_files = sorted((DATA_ROOT / "routes").glob("*.json")) if (DATA_ROOT / "routes").exists() else []
    for path in route_files:
        try:
            route = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            error(f"Invalid route JSON `{path.relative_to(ROOT)}`: {exc}")
            continue
        route_id = route.get("route_id")
        if not isinstance(route_id, str) or not route_id:
            error(f"Route `{path.name}` has no route_id")
            continue
        if route_id in route_by_id:
            error(f"Duplicate route_id: {route_id}")
        route_by_id[route_id] = route
        if route.get("provider") not in {"goong", "osrm"}:
            error(f"{route_id}: provider must be goong or osrm")
        if route.get("data_source") != "routing_api":
            error(f"{route_id}: data_source must be routing_api")
        if not isinstance(route.get("distance_m"), (int, float)) or route["distance_m"] <= 0:
            error(f"{route_id}: distance_m must be positive")
        if not isinstance(route.get("duration_s"), (int, float)) or route["duration_s"] <= 0:
            error(f"{route_id}: duration_s must be positive")
        geometry = route.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") != "LineString" or len(geometry.get("coordinates", [])) < 2:
            error(f"{route_id}: geometry must be a non-empty GeoJSON LineString")
        parse_datetime(route.get("retrieved_at"), f"{route_id}.retrieved_at")
        if not isinstance(route.get("request_hash"), str) or len(route["request_hash"]) != 64:
            error(f"{route_id}: request_hash must be SHA-256")
        for waypoint in route.get("waypoints", []):
            waypoint_station = waypoint.get("station_id")
            if waypoint_station and waypoint_station not in station_ids:
                error(f"{route_id}: waypoint references unknown station {waypoint_station}")
    checked(f"Validated {len(route_by_id)} routing API cache files")

    for arrival in arrivals:
        context = arrival.get("arrival_id", "<unknown arrival>")
        if arrival.get("station_id") not in station_ids:
            error(f"{context}: unknown station_id")
        if arrival.get("vehicle_id") is not None and arrival.get("vehicle_id") not in vehicle_ids:
            error(f"{context}: unknown vehicle_id")
        if arrival.get("route_id") is not None and arrival.get("route_id") not in route_by_id:
            error(f"{context}: unknown route_id {arrival.get('route_id')}")
        if arrival.get("status") not in {"planned", "arrived", "cancelled", "expired"}:
            error(f"{context}: invalid status")
        probability = arrival.get("arrival_probability")
        if not isinstance(probability, (int, float)) or not 0 <= probability <= 1:
            error(f"{context}: arrival_probability must be in [0, 1]")
        times = {
            key: parse_datetime(arrival.get(key), f"{context}.{key}")
            for key in ["created_at", "eta_at", "eta_window_start", "eta_window_end", "expires_at"]
        }
        if all(times.values()):
            if not times["eta_window_start"] <= times["eta_at"] <= times["eta_window_end"]:
                error(f"{context}: eta_at must be inside ETA window")
            if times["created_at"] > times["expires_at"]:
                error(f"{context}: created_at is after expires_at")
    if not any(item.get("status") == "planned" for item in arrivals):
        error("planned_arrivals has no planned case")
    if not any(item.get("status") == "cancelled" for item in arrivals):
        error("planned_arrivals has no cancelled case")
    if not any(item.get("status") == "expired" for item in arrivals):
        error("planned_arrivals has no expired case")
    planned_counts: dict[str, int] = {}
    for item in arrivals:
        if item.get("status") == "planned":
            planned_counts[item["station_id"]] = planned_counts.get(item["station_id"], 0) + 1
    if max(planned_counts.values(), default=0) < 2:
        error("planned_arrivals has no multiple-vehicles-to-one-station case")
    checked(f"Referential and temporal checks completed for {len(arrivals)} planned-arrival records")

    required_event_types = {"congestion", "port_outage", "queue_spike", "station_recovery"}
    actual_event_types = {event.get("event_type") for event in events}
    if not required_event_types <= actual_event_types:
        error(f"Missing event types: {sorted(required_event_types-actual_event_types)}")
    for event in events:
        context = event.get("event_id", "<unknown event>")
        station_id = event.get("station_id")
        if station_id not in station_ids or station_id not in status_by_id:
            error(f"{context}: unknown station_id")
            continue
        if event.get("severity") not in {"low", "medium", "high"}:
            error(f"{context}: invalid severity")
        if event.get("is_synthetic") is not True:
            error(f"{context}: is_synthetic must be true")
        parse_datetime(event.get("start_at"), f"{context}.start_at")
        if event.get("end_at") is not None:
            parse_datetime(event.get("end_at"), f"{context}.end_at")
        effects = event.get("effects")
        if not isinstance(effects, dict) or not effects:
            error(f"{context}: effects must be a non-empty object")
            continue
        unknown_effects = set(effects) - {"offline_ports_delta", "queue_length_delta", "occupied_ports_delta"}
        if unknown_effects:
            error(f"{context}: unsupported effects {sorted(unknown_effects)}")
        if not all(isinstance(value, int) for value in effects.values()):
            error(f"{context}: effect deltas must be integers")
            continue
        baseline = status_by_id[station_id]
        offline = baseline["offline_ports"] + effects.get("offline_ports_delta", 0)
        operational = baseline["total_ports"] - offline
        occupied = baseline["occupied_ports"] + effects.get("occupied_ports_delta", 0)
        queue = baseline["queue_length"] + effects.get("queue_length_delta", 0)
        if not (0 <= offline <= baseline["total_ports"] and 0 <= occupied <= operational and queue >= 0):
            error(f"{context}: applying effect to baseline violates capacity/queue invariants")
    checked(f"All {len(events)} required event types are present and capacity-safe")

    if len(scenarios) < 4:
        error("At least four demo scenarios are required")
    required_scenarios = {"SCN_NORMAL", "SCN_LOW_SOC", "SCN_CONGESTION_REROUTE", "SCN_PORT_OUTAGE_REROUTE"}
    if not required_scenarios <= scenario_ids:
        error(f"Missing fixed scenarios: {sorted(required_scenarios-scenario_ids)}")
    for scenario in scenarios:
        context = scenario.get("scenario_id", "<unknown scenario>")
        if scenario.get("vehicle_id") not in vehicle_ids:
            error(f"{context}: unknown vehicle_id")
        for key in ["initial_soc", "target_soc"]:
            value = scenario.get(key)
            if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                error(f"{context}: {key} must be in [0, 1]")
        if isinstance(scenario.get("initial_soc"), (int, float)) and isinstance(scenario.get("target_soc"), (int, float)) and scenario["initial_soc"] >= scenario["target_soc"]:
            error(f"{context}: initial_soc must be lower than target_soc")
        preference = scenario.get("preference", {})
        expected_weights = {"wait_weight", "detour_weight", "charging_time_weight", "soc_risk_weight"}
        if set(preference) != expected_weights or not all(isinstance(value, (int, float)) and value >= 0 for value in preference.values()):
            error(f"{context}: invalid preference weights")
        elif not math.isclose(sum(preference.values()), 1.0, abs_tol=1e-9):
            error(f"{context}: preference weights must sum to 1.0")
        for event_id in scenario.get("event_ids", []):
            if event_id not in event_ids:
                error(f"{context}: unknown event_id {event_id}")
        route_ids = scenario.get("route_ids")
        if not isinstance(route_ids, list) or not route_ids:
            error(f"{context}: route_ids must be a non-empty array")
        else:
            cached_station_ids: set[str] = set()
            has_direct_route = False
            for route_id in route_ids:
                if route_id not in route_by_id:
                    error(f"{context}: unknown route_id {route_id}")
                    continue
                waypoints = route_by_id[route_id].get("waypoints", [])
                if not waypoints:
                    has_direct_route = True
                cached_station_ids.update(
                    waypoint.get("station_id")
                    for waypoint in waypoints
                    if waypoint.get("station_id")
                )
            if not has_direct_route:
                error(f"{context}: route cache must include a direct route")
            if cached_station_ids != public_station_ids:
                error(
                    f"{context}: route cache coverage differs from public stations: "
                    f"missing={sorted(public_station_ids-cached_station_ids)}, "
                    f"extra={sorted(cached_station_ids-public_station_ids)}"
                )
        parse_datetime(scenario.get("departure_at"), f"{context}.departure_at")
    checked(f"Validated {len(scenarios)} deterministic demo scenarios")

    if not isinstance(assumptions, dict):
        error("queue_assumptions must be a top-level object")
    else:
        window = assumptions.get("planned_arrival_window_min")
        if not isinstance(window, int) or window <= 0:
            error("planned_arrival_window_min must be a positive integer")
        rates = assumptions.get("station_rates", [])
        rate_station_ids = [record.get("station_id") for record in rates if isinstance(record, dict)]
        if len(rate_station_ids) != len(set(rate_station_ids)):
            error("queue_assumptions has duplicate station rates")
        if set(rate_station_ids) != station_ids:
            error("queue_assumptions must contain exactly one baseline rate per station")
        for record in rates:
            rate = record.get("baseline_arrival_rate_per_hour")
            if not isinstance(rate, (int, float)) or rate < 0:
                error(f"Invalid baseline arrival rate for {record.get('station_id')}")
            station_id = record.get("station_id")
            if station_id in status_by_id and isinstance(rate, (int, float)):
                capacity = status_by_id[station_id]["operational_ports"] * 60 / status_by_id[station_id]["avg_session_duration_min"]
                if rate >= capacity:
                    warning(f"{station_id}: baseline arrival rate overloads Erlang C capacity")
        override_pairs: list[tuple] = []
        for override in assumptions.get("scenario_overrides", []):
            pair = (override.get("scenario_id"), override.get("station_id"))
            override_pairs.append(pair)
            if pair[0] not in scenario_ids or pair[1] not in station_ids:
                error(f"Unknown scenario/station in queue override: {pair}")
            rate = override.get("baseline_arrival_rate_per_hour")
            if not isinstance(rate, (int, float)) or rate < 0:
                error(f"Invalid override arrival rate for {pair}")
        if len(override_pairs) != len(set(override_pairs)):
            error("Duplicate scenario-station queue override")
        if assumptions.get("data_source") != "synthetic":
            error("queue_assumptions.data_source must be synthetic")
        checked(f"Validated one baseline arrival rate for each of {len(station_ids)} stations")

    if not (DATA_ROOT / "demo" / "station_history.csv").exists():
        warning("Optional station_history.csv omitted; UrbanEV-normalized replay will be decided in Phase 03")
    validate_raw_source()


def write_report() -> None:
    status = "PASS" if not errors else "FAIL"
    lines = [
        "# Full data validation report — Phase 01",
        "",
        f"**Result:** `{status}`",
        "",
        f"- Errors: {len(errors)}",
        f"- Warnings: {len(warnings)}",
        f"- Checks passed: {len(checks)}",
        "",
        "## Checks",
        "",
    ]
    lines.extend(f"- PASS — {message}" for message in checks)
    lines.extend(["", "## Errors", ""])
    lines.extend(f"- ERROR — {message}" for message in errors)
    if not errors:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- WARNING — {message}" for message in warnings)
    if not warnings:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Scope note",
            "",
            "`station_history.csv` is optional and is intentionally not generated in Phase 01. "
            "If Phase 03 confirms a suitable UrbanEV 5-minute station-level series, the demo replay may be derived from that processed source; it is never an ML training input.",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Phase 01 validation: {status} ({len(errors)} errors, {len(warnings)} warnings)")
    print(f"Report: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    validate_all()
    write_report()
    sys.exit(1 if errors else 0)
