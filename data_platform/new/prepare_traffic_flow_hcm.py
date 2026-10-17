"""Prepare reproducible HCMC traffic-condition JSON for the nine-ward pilot.

The downloaded source reports a road-segment velocity, not a count of vehicles.
This script deliberately preserves that distinction: every output record has a
null ``vehicle_count`` with an explicit availability status.  It must not be
used as a vehicle-volume dataset.

Input files are expected below ``raw_data/traffic_flow_hcm/source`` and are
the unmodified CSV files supplied by the public source.  Outputs are written to
``raw_data/traffic_flow_hcm``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "raw_data" / "traffic_flow_hcm" / "source"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "raw_data" / "traffic_flow_hcm"
DEFAULT_CANONICAL_OUTPUT_DIR = PROJECT_ROOT / "data_platform" / "station_planning" / "planner_v2"
DEFAULT_BOUNDARIES = (
    PROJECT_ROOT / "raw_data" / "admin_boundaries" / "hcm_planning_units_2025.geojson"
)
DEFAULT_WARD_SELECTION = (
    PROJECT_ROOT
    / "raw_data"
    / "charging_stations"
    / "hcm_dc80kw"
    / "five_wards_report.json"
)

# Vietnam has no daylight-saving transitions. A fixed UTC+07:00 offset avoids a
# platform-specific IANA timezone-data dependency on Windows installations.
LOCAL_TIMEZONE = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")
SOURCE_URL = "https://www.kaggle.com/datasets/thanhnguyen2612/traffic-flow-data-in-ho-chi-minh-city-viet-nam"
MIRROR_URL = (
    "https://ckan.tdc.prod.datopian.com/dataset/501f44ae-5c42-4a49-90db-b71e4168a7e6/"
    "resource/9e5ba67b-cfb3-44f8-ac34-fdef7343e1a6/download/archive3.zip"
)
SOURCE_DESCRIPTION = (
    "Historical HCMC road-segment status: timestamp, segment identifier and velocity. "
    "It does not contain vehicle counts."
)
TRAFFIC_SOURCE_ID = "src-kaggle-hcm-traffic-2026-10-17"
BOUNDARY_SOURCE_ID = "src-hcm-administrative-2025"


@dataclass(frozen=True)
class Ward:
    """One selected 2025 administrative unit and its polygon rings."""

    unit_id: str
    name: str
    polygons: tuple[tuple[tuple[tuple[float, float], ...], ...], ...]
    bounds: tuple[float, float, float, float]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def decimal_or_none(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def point_on_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> bool:
    """Return whether point lies on a closed line segment within a small tolerance."""

    px, py = point
    ax, ay = start
    bx, by = end
    cross_product = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross_product) > 1e-12:
        return False
    return min(ax, bx) - 1e-12 <= px <= max(ax, bx) + 1e-12 and min(ay, by) - 1e-12 <= py <= max(ay, by) + 1e-12


def point_in_ring(point: tuple[float, float], ring: tuple[tuple[float, float], ...]) -> bool:
    """Inclusive ray-casting point-in-ring test for longitude/latitude coordinates."""

    x, y = point
    inside = False
    for previous, current in zip(ring, ring[1:] + ring[:1]):
        if point_on_segment(point, previous, current):
            return True
        x1, y1 = previous
        x2, y2 = current
        crosses_horizontal_ray = (y1 > y) != (y2 > y)
        if crosses_horizontal_ray:
            intersection_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < intersection_x:
                inside = not inside
    return inside


def point_in_polygon(
    point: tuple[float, float], polygon: tuple[tuple[tuple[float, float], ...], ...]
) -> bool:
    """Return true for a point in the exterior ring but outside any hole."""

    return bool(polygon) and point_in_ring(point, polygon[0]) and not any(
        point_in_ring(point, hole) for hole in polygon[1:]
    )


def point_in_ward(point: tuple[float, float], ward: Ward) -> bool:
    lon, lat = point
    min_lon, min_lat, max_lon, max_lat = ward.bounds
    if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
        return False
    return any(point_in_polygon(point, polygon) for polygon in ward.polygons)


def coerce_polygon(coordinates: Any) -> tuple[tuple[tuple[float, float], ...], ...]:
    return tuple(tuple((float(lon), float(lat)) for lon, lat, *_ in ring) for ring in coordinates)


def polygon_bounds(
    polygons: tuple[tuple[tuple[tuple[float, float], ...], ...], ...]
) -> tuple[float, float, float, float]:
    points = [point for polygon in polygons for ring in polygon for point in ring]
    longitudes, latitudes = zip(*points)
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def load_selected_wards(boundaries_path: Path, ward_selection_path: Path) -> list[Ward]:
    selected_ids = set(read_json(ward_selection_path)["ward_admin_ids"].values())
    boundary_collection = read_json(boundaries_path)
    wards: list[Ward] = []

    for feature in boundary_collection["features"]:
        properties = feature["properties"]
        unit_id = properties["unit_id"]
        if unit_id.rsplit("_", maxsplit=1)[-1] not in selected_ids:
            continue
        geometry = feature["geometry"]
        geometry_type = geometry["type"]
        if geometry_type == "Polygon":
            polygons = (coerce_polygon(geometry["coordinates"]),)
        elif geometry_type == "MultiPolygon":
            polygons = tuple(coerce_polygon(polygon) for polygon in geometry["coordinates"])
        else:
            raise ValueError(f"Unsupported geometry {geometry_type} for {unit_id}")
        wards.append(
            Ward(
                unit_id=unit_id,
                name=properties["unit_name"],
                polygons=polygons,
                bounds=polygon_bounds(polygons),
            )
        )

    if len(wards) != 9:
        raise ValueError(f"Expected nine selected wards, found {len(wards)}")
    return sorted(wards, key=lambda ward: ward.unit_id)


def load_nodes(path: Path) -> dict[str, tuple[float, float]]:
    nodes: dict[str, tuple[float, float]] = {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            lon, lat = decimal_or_none(row["long"]), decimal_or_none(row["lat"])
            if lon is not None and lat is not None:
                nodes[row["_id"]] = (lon, lat)
    return nodes


def midpoint(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
    return ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2)


def load_selected_segments(
    path: Path, nodes: dict[str, tuple[float, float]], wards: Iterable[Ward]
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    selected_segments: dict[str, dict[str, Any]] = {}
    diagnostics = defaultdict(int)
    ward_list = list(wards)

    with path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            diagnostics["source_segments"] += 1
            start = nodes.get(row["s_node_id"])
            end = nodes.get(row["e_node_id"])
            if start is None or end is None:
                diagnostics["segments_missing_node_geometry"] += 1
                continue
            segment_midpoint = midpoint(start, end)
            matches = [ward for ward in ward_list if point_in_ward(segment_midpoint, ward)]
            if not matches:
                diagnostics["segments_outside_selected_wards"] += 1
                continue
            if len(matches) > 1:
                diagnostics["segments_matching_multiple_wards"] += 1
                continue
            ward = matches[0]
            velocity_limit = decimal_or_none(row["max_velocity"])
            selected_segments[row["_id"]] = {
                "segment_id": row["_id"],
                "ward_id": ward.unit_id,
                "ward_name": ward.name,
                "street_id": row["street_id"],
                "street_name": row["street_name"] or None,
                "street_type": row["street_type"] or None,
                "street_level": decimal_or_none(row["street_level"]),
                "length_m": decimal_or_none(row["length"]),
                "maximum_velocity_kmh": velocity_limit,
                "start_point": {"lon": start[0], "lat": start[1]},
                "end_point": {"lon": end[0], "lat": end[1]},
                "midpoint": {"lon": segment_midpoint[0], "lat": segment_midpoint[1]},
                "spatial_assignment": "segment_midpoint_in_administrative_2025_polygon",
            }
            diagnostics["segments_in_selected_wards"] += 1
    return selected_segments, dict(diagnostics)


def parse_utc(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return parsed.astimezone(LOCAL_TIMEZONE)


def iso_week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def percentile_50(values: list[float]) -> float | None:
    return round(float(median(values)), 6) if values else None


def aggregate_record(
    ward: Ward,
    period: str,
    frequency: str,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    velocities = [record["velocity_kmh"] for record in observations]
    ratios = [
        record["speed_ratio_to_segment_max"]
        for record in observations
        if record["speed_ratio_to_segment_max"] is not None
    ]
    return {
        "ward_id": ward.unit_id,
        "ward_name": ward.name,
        "period": period,
        "frequency": frequency,
        "observation_count": len(observations),
        "observed_segment_count": len({record["segment_id"] for record in observations}),
        "mean_velocity_kmh": mean(velocities),
        "median_velocity_kmh": percentile_50(velocities),
        "mean_speed_ratio_to_segment_max": mean(ratios),
        "vehicle_count": None,
        "vehicle_count_unit": "vehicles",
        "vehicle_count_status": "not_available_in_source",
        "source_type": "unknown",
        "quality_status": "unknown",
        "availability_status": (
            "no_observations_for_period" if not observations else "source_observation_present"
        ),
        "is_proxy": False,
        "is_synthetic": False,
        "record_semantics": "historical_segment_velocity_not_vehicle_volume",
    }


def date_range(start: date, end: date) -> Iterable[date]:
    value = start
    while value <= end:
        yield value
        value += timedelta(days=1)


def month_range(start: date, end: date) -> Iterable[str]:
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        yield f"{year:04d}-{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    """Write canonical CSV with a BOM so it opens safely in Vietnamese Excel."""

    with path.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def selected_boundary_features(boundaries_path: Path, wards: list[Ward]) -> list[dict[str, Any]]:
    selected_ids = {ward.unit_id for ward in wards}
    features: list[dict[str, Any]] = []
    for feature in read_json(boundaries_path)["features"]:
        if feature["properties"].get("unit_id") not in selected_ids:
            continue
        features.append(
            {
                "type": "Feature",
                "id": feature["id"],
                "geometry": feature["geometry"],
                "properties": {
                    **feature["properties"],
                    "source_id": BOUNDARY_SOURCE_ID,
                    "source_type": "official",
                    "quality_status": "official",
                    "observed_at": None,
                    "is_synthetic": False,
                },
            }
        )
    if len(features) != 9:
        raise ValueError(f"Expected nine selected boundary features, found {len(features)}")
    return sorted(features, key=lambda feature: feature["properties"]["unit_id"])


def canonical_segment_features(selected_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map source nodes/segments to the target GeoJSON line contract."""

    return [
        {
            "type": "Feature",
            "id": f"hcm-traffic-segment-{segment['segment_id']}",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [segment["start_point"]["lon"], segment["start_point"]["lat"]],
                    [segment["end_point"]["lon"], segment["end_point"]["lat"]],
                ],
            },
            "properties": {
                "segment_id": segment["segment_id"],
                "road_class": segment["street_type"],
                "direction": "unknown",
                "access_rules": "unknown",
                "street_id": segment["street_id"],
                "street_name": segment["street_name"],
                "street_level": segment["street_level"],
                "length_m": segment["length_m"],
                "maximum_velocity_kmh": segment["maximum_velocity_kmh"],
                "ward_id": segment["ward_id"],
                "ward_name": segment["ward_name"],
                "spatial_assignment": segment["spatial_assignment"],
                "source_id": TRAFFIC_SOURCE_ID,
                "source_type": "unknown",
                "quality_status": "unknown",
                "is_synthetic": False,
            },
        }
        for segment in selected_segments
    ]


def canonical_observation_rows(
    observations: list[dict[str, Any]], generated_at: str
) -> list[dict[str, Any]]:
    """Map source speed observations to the Planner traffic-observation contract.

    The source's velocity field is retained as an average-speed input.  The
    count and VPH fields intentionally remain null because no count is present
    in the source and its collection method is not documented sufficiently to
    classify it as a measured vehicle-volume feed.
    """

    return [
        {
            "segment_id": record["segment_id"],
            "interval_start": record["observed_at_local"],
            "interval_minutes": None,
            "vehicle_count": None,
            "vehicle_volume_vph": None,
            "average_speed_kph": record["velocity_kmh"],
            "vehicle_class": "unknown",
            "direction": "unknown",
            "measurement_method": "historical_segment_velocity_source_method_not_documented",
            "coverage_percent": None,
            "source_id": TRAFFIC_SOURCE_ID,
            "source_type": "unknown",
            "quality_status": "unknown",
            "is_proxy": "false",
            "scenario_traffic_level": None,
            "source_observation_id": record["source_observation_id"],
            "ward_id": record["ward_id"],
            "ward_name": record["ward_name"],
            "maximum_velocity_kmh": record["maximum_velocity_kmh"],
            "speed_ratio_to_segment_max": record["speed_ratio_to_segment_max"],
            "observed_at": record["observed_at_local"],
            "published_at": None,
            "ingested_at": generated_at,
            "last_verified_at": generated_at,
            "confidence": None,
            "is_synthetic": "false",
            "record_semantics": "historical_segment_velocity_not_vehicle_volume",
        }
        for record in observations
    ]


def write_canonical_snapshot(
    canonical_output_dir: Path,
    boundaries_path: Path,
    wards: list[Ward],
    selected_segments: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    aggregate_payloads: dict[str, dict[str, Any]],
    source_metadata: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Write the target Planner import snapshot without altering the demo v3."""

    canonical_output_dir.mkdir(parents=True, exist_ok=True)
    boundaries_file = canonical_output_dir / "boundaries.geojson"
    segments_file = canonical_output_dir / "traffic_segments.geojson"
    observations_file = canonical_output_dir / "traffic_observations.csv"
    source_registry_file = canonical_output_dir / "source_registry.csv"

    write_json(
        boundaries_file,
        {
            "type": "FeatureCollection",
            "name": "hcmc-nine-wards-administrative-2025",
            "features": selected_boundary_features(boundaries_path, wards),
        },
    )
    write_json(
        segments_file,
        {
            "type": "FeatureCollection",
            "name": "hcmc-nine-wards-historical-traffic-segments",
            "features": canonical_segment_features(selected_segments),
        },
    )
    observation_rows = canonical_observation_rows(observations, generated_at)
    observation_columns = [
        "segment_id",
        "interval_start",
        "interval_minutes",
        "vehicle_count",
        "vehicle_volume_vph",
        "average_speed_kph",
        "vehicle_class",
        "direction",
        "measurement_method",
        "coverage_percent",
        "source_id",
        "source_type",
        "quality_status",
        "is_proxy",
        "scenario_traffic_level",
        "source_observation_id",
        "ward_id",
        "ward_name",
        "maximum_velocity_kmh",
        "speed_ratio_to_segment_max",
        "observed_at",
        "published_at",
        "ingested_at",
        "last_verified_at",
        "confidence",
        "is_synthetic",
        "record_semantics",
    ]
    write_csv(observations_file, observation_columns, observation_rows)
    write_csv(
        source_registry_file,
        [
            "source_id",
            "source_name",
            "source_type",
            "source_url",
            "license_or_contract_ref",
            "collected_at",
            "coverage",
            "access_scope",
            "refresh_policy",
            "contact_or_owner",
            "notes",
        ],
        [
            {
                "source_id": TRAFFIC_SOURCE_ID,
                "source_name": "Traffic Flow data in Ho Chi Minh City, Viet Nam",
                "source_type": "unknown",
                "source_url": SOURCE_URL,
                "license_or_contract_ref": "CC0-as-published-by-primary-source",
                "collected_at": generated_at,
                "coverage": "HCMC source network; normalized to the nine selected wards",
                "access_scope": "public",
                "refresh_policy": "static_historical_snapshot",
                "contact_or_owner": "Kaggle dataset publisher; underlying collection method not documented in supplied files",
                "notes": "Velocity/status only. No vehicle count, vehicle class, direction, or measured interval duration.",
            },
            {
                "source_id": BOUNDARY_SOURCE_ID,
                "source_name": "Bản đồ số TP.HCM — ADMINISTRATIVE_2025",
                "source_type": "official",
                "source_url": "https://bando.tphcm.gov.vn/",
                "license_or_contract_ref": "project_raw_source_manifest",
                "collected_at": generated_at,
                "coverage": "nine selected wards",
                "access_scope": "project_snapshot",
                "refresh_policy": "when_official_boundary_snapshot_changes",
                "contact_or_owner": "TP.HCM Digital Map",
                "notes": "Used only for spatial harmonization by segment midpoint.",
            },
        ],
    )

    # The chart-oriented JSONs remain part of the canonical snapshot, but the
    # import contract uses the CSV above as the atomic observation table.
    chart_files: list[Path] = []
    for frequency, payload in aggregate_payloads.items():
        chart_file = canonical_output_dir / f"traffic_condition_{frequency}_9_wards.json"
        write_json(
            chart_file,
            {
                "dataset_id": "hcmc-nine-wards-historical-traffic-condition-v1",
                "source_id": TRAFFIC_SOURCE_ID,
                "source_type": "unknown",
                "quality_status": "unknown",
                "vehicle_count_available": False,
                "vehicle_count_status": "not_available_in_source",
                "source": source_metadata,
                **payload,
            },
        )
        chart_files.append(chart_file)

    local_observed_times = [record["observed_at_local"] for record in observations]
    dataset_files = [
        ("boundaries", boundaries_file, len(wards), None, None),
        ("traffic_segments", segments_file, len(selected_segments), None, None),
        (
            "traffic_observations",
            observations_file,
            len(observation_rows),
            min(local_observed_times),
            max(local_observed_times),
        ),
        ("source_registry", source_registry_file, 2, None, None),
        *[
            (
                f"traffic_condition_{frequency}",
                chart_file,
                len(aggregate_payloads[frequency]["records"]),
                None,
                None,
            )
            for frequency, chart_file in zip(aggregate_payloads, chart_files)
        ],
    ]
    snapshot = {
        "snapshot_id": "hcm-planner-v2-2026-10-17-traffic-condition-v1",
        "created_at": generated_at,
        "timezone": "Asia/Ho_Chi_Minh",
        "crs": "EPSG:4326",
        "is_simulation_snapshot": True,
        "data_classification": "historical_traffic_condition_not_vehicle_volume",
        "datasets": [
            {
                "dataset_id": dataset_id,
                "file": path.name,
                "sha256": sha256(path),
                "row_or_feature_count": record_count,
                "source_ids": (
                    [BOUNDARY_SOURCE_ID]
                    if dataset_id == "boundaries"
                    else [TRAFFIC_SOURCE_ID, BOUNDARY_SOURCE_ID]
                    if dataset_id == "source_registry"
                    else [TRAFFIC_SOURCE_ID]
                ),
                "min_observed_at": minimum,
                "max_observed_at": maximum,
            }
            for dataset_id, path, record_count, minimum, maximum in dataset_files
        ],
        "warnings": [
            "traffic_observations.csv contains historical segment velocity, not vehicle counts.",
            "vehicle_count and vehicle_volume_vph are blank by design; empty is unknown, never zero.",
            "source_type and quality_status are unknown because the dataset files do not document the measurement method required to claim measured vehicle volume.",
            "The 2020–2021 source timeline is spatially harmonized against the 2025 ward boundary snapshot using segment midpoints.",
            "This snapshot is separate from demo_hcmc_v3 and is not automatically loaded by the existing Planner/API/UI.",
        ],
    }
    write_json(canonical_output_dir / "snapshot_manifest.json", snapshot)
    return snapshot


def collect_observations(
    status_path: Path, selected_segments: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    observations: list[dict[str, Any]] = []
    diagnostics = defaultdict(int)
    with status_path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            diagnostics["source_status_rows"] += 1
            segment = selected_segments.get(row["segment_id"])
            if segment is None:
                diagnostics["status_rows_outside_selected_wards"] += 1
                continue
            observed_at_local = parse_utc(row["updated_at"])
            velocity = decimal_or_none(row["velocity"])
            if velocity is None:
                diagnostics["selected_status_rows_with_invalid_velocity"] += 1
                continue
            maximum_velocity = segment["maximum_velocity_kmh"]
            ratio = velocity / maximum_velocity if maximum_velocity and maximum_velocity > 0 else None
            observations.append(
                {
                    "source_observation_id": row["_id"],
                    "observed_at": row["updated_at"],
                    "observed_at_local": observed_at_local.isoformat(),
                    "ward_id": segment["ward_id"],
                    "ward_name": segment["ward_name"],
                    "segment_id": segment["segment_id"],
                    "velocity_kmh": velocity,
                    "maximum_velocity_kmh": maximum_velocity,
                    "speed_ratio_to_segment_max": round(ratio, 6) if ratio is not None else None,
                    "vehicle_count": None,
                    "vehicle_count_status": "not_available_in_source",
                    "source_type": "unknown",
                    "quality_status": "unknown",
                    "is_proxy": False,
                    "is_synthetic": False,
                    "record_semantics": "historical_segment_velocity_not_vehicle_volume",
                }
            )
            diagnostics["selected_status_rows"] += 1
    return sorted(observations, key=lambda record: (record["observed_at"], record["source_observation_id"])), dict(diagnostics)


def create_aggregate_payloads(
    wards: list[Ward], observations: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    by_day: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_week: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_month: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    local_dates = [datetime.fromisoformat(record["observed_at_local"]).date() for record in observations]
    start, end = min(local_dates), max(local_dates)

    for record, observed_date in zip(observations, local_dates):
        by_day[(record["ward_id"], observed_date.isoformat())].append(record)
        by_week[(record["ward_id"], iso_week_start(observed_date).isoformat())].append(record)
        by_month[(record["ward_id"], f"{observed_date:%Y-%m}")].append(record)

    daily = [
        aggregate_record(ward, current.isoformat(), "day", by_day[(ward.unit_id, current.isoformat())])
        for current in date_range(start, end)
        for ward in wards
    ]
    weekly = [
        aggregate_record(ward, current.isoformat(), "week", by_week[(ward.unit_id, current.isoformat())])
        for current in date_range(iso_week_start(start), iso_week_start(end))
        if current.weekday() == 0
        for ward in wards
    ]
    monthly = [
        aggregate_record(ward, current, "month", by_month[(ward.unit_id, current)])
        for current in month_range(start, end)
        for ward in wards
    ]

    return {
        "daily": {
            "frequency": "day",
            "coverage_start_local": start.isoformat(),
            "coverage_end_local": end.isoformat(),
            "records": daily,
        },
        "weekly": {
            "frequency": "week",
            "coverage_start_local": iso_week_start(start).isoformat(),
            "coverage_end_local": iso_week_start(end).isoformat(),
            "records": weekly,
        },
        "monthly": {
            "frequency": "month",
            "coverage_start_local": start.replace(day=1).isoformat(),
            "coverage_end_local": end.replace(day=1).isoformat(),
            "records": monthly,
        },
    }


def prepare(
    source_dir: Path,
    output_dir: Path,
    canonical_output_dir: Path,
    boundaries_path: Path,
    ward_selection_path: Path,
) -> dict[str, Any]:
    source_files = {
        name: source_dir / name
        for name in ("nodes.csv", "segments.csv", "segment_status.csv", "streets.csv", "train.csv")
    }
    missing = [str(path) for path in source_files.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing source file(s): {', '.join(missing)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    wards = load_selected_wards(boundaries_path, ward_selection_path)
    nodes = load_nodes(source_files["nodes.csv"])
    segments, segment_diagnostics = load_selected_segments(source_files["segments.csv"], nodes, wards)
    observations, status_diagnostics = collect_observations(source_files["segment_status.csv"], segments)
    if not observations:
        raise ValueError("No traffic-condition observations mapped to the selected wards")

    aggregate_payloads = create_aggregate_payloads(wards, observations)
    source_hashes = {
        name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for name, path in source_files.items()
    }
    selected_segment_rows = [segments[segment_id] for segment_id in sorted(segments, key=int)]
    source_metadata = {
        "dataset_name": "Traffic Flow data in Ho Chi Minh City, Viet Nam",
        "primary_source_url": SOURCE_URL,
        "download_mirror_url": MIRROR_URL,
        "source_description": SOURCE_DESCRIPTION,
        "license_as_published_by_primary_source": "CC0: Public Domain",
        "source_data_files": source_hashes,
        "timezone_for_aggregation": "Asia/Ho_Chi_Minh",
        "source_timestamp_timezone": "UTC (ISO 8601 Z suffix)",
        "spatial_assignment": "segment midpoint within current ADMINISTRATIVE_2025 polygon",
    }
    limitations = [
        "This source supplies historical segment velocity/status only; it contains no number of vehicles, vehicle class, origin-destination, or turn-count field.",
        "vehicle_count is null by design. A zero vehicle count must never be inferred from an absent observation.",
        "Observations are irregular and sparse across the source date range. A period with observation_count=0 means no mapped source observation, not zero traffic.",
        "The source observations are from 2020-07 through 2021-04, while spatial assignment uses the project's 2025 ward boundary snapshot. This is a spatial harmonization, not a claim that the 2020 administrative boundary was identical.",
        "A road segment is assigned using its midpoint; segments crossing a ward boundary are not length-split.",
        "The maximum velocity is a segment attribute supplied by the source. Ratio metrics are derived diagnostics, not a measured vehicle-volume or congestion count.",
    ]
    generated_at_local = datetime.now(tz=LOCAL_TIMEZONE).isoformat(timespec="seconds")
    manifest = {
        "dataset_id": "hcmc-nine-wards-historical-traffic-condition-v1",
        "generated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "data_classification": "observed_historical_traffic_condition_not_vehicle_volume",
        "vehicle_count_available": False,
        "vehicle_count_status": "not_available_in_source",
        "source": source_metadata,
        "wards": [{"ward_id": ward.unit_id, "ward_name": ward.name} for ward in wards],
        "outputs": {
            "segments": "traffic_segments_9_wards.json",
            "observations": "traffic_condition_observations_9_wards.json",
            "daily": "traffic_condition_daily_9_wards.json",
            "weekly": "traffic_condition_weekly_9_wards.json",
            "monthly": "traffic_condition_monthly_9_wards.json",
            "canonical_snapshot": str(canonical_output_dir.relative_to(PROJECT_ROOT)),
        },
        "counts": {
            "selected_wards": len(wards),
            "selected_segments": len(selected_segment_rows),
            "selected_observations": len(observations),
            "daily_records": len(aggregate_payloads["daily"]["records"]),
            "weekly_records": len(aggregate_payloads["weekly"]["records"]),
            "monthly_records": len(aggregate_payloads["monthly"]["records"]),
        },
        "diagnostics": {**segment_diagnostics, **status_diagnostics},
        "limitations": limitations,
    }

    shared_envelope = {
        "dataset_id": manifest["dataset_id"],
        "data_classification": manifest["data_classification"],
        "vehicle_count_available": False,
        "vehicle_count_status": "not_available_in_source",
        "source": source_metadata,
        "limitations": limitations,
    }
    write_json(output_dir / "traffic_segments_9_wards.json", {**shared_envelope, "records": selected_segment_rows})
    write_json(output_dir / "traffic_condition_observations_9_wards.json", {**shared_envelope, "records": observations})
    for name, payload in aggregate_payloads.items():
        write_json(output_dir / f"traffic_condition_{name}_9_wards.json", {**shared_envelope, **payload})
    canonical_snapshot = write_canonical_snapshot(
        canonical_output_dir=canonical_output_dir,
        boundaries_path=boundaries_path,
        wards=wards,
        selected_segments=selected_segment_rows,
        observations=observations,
        aggregate_payloads=aggregate_payloads,
        source_metadata=source_metadata,
        generated_at=generated_at_local,
    )
    manifest["canonical_snapshot_id"] = canonical_snapshot["snapshot_id"]
    manifest["canonical_snapshot_manifest"] = str(
        (canonical_output_dir / "snapshot_manifest.json").relative_to(PROJECT_ROOT)
    )
    write_json(output_dir / "collection_manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--canonical-output-dir", type=Path, default=DEFAULT_CANONICAL_OUTPUT_DIR)
    parser.add_argument("--boundaries", type=Path, default=DEFAULT_BOUNDARIES)
    parser.add_argument("--ward-selection", type=Path, default=DEFAULT_WARD_SELECTION)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = prepare(
        args.source_dir,
        args.output_dir,
        args.canonical_output_dir,
        args.boundaries,
        args.ward_selection,
    )
    print(json.dumps(manifest["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
