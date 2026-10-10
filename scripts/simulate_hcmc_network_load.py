#!/usr/bin/env python3
"""Compare nearest-only and load-aware charging choices on synthetic HCMC data.

This reproducible discrete-event study uses the repository's explicitly
synthetic demo catalog, status and arrival-rate assumptions. It is not a
forecast model, does not estimate production performance, and must not be used
as telemetry or training data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.domain.models import OccupancyForecastResult, StationStatus  # noqa: E402
from backend.app.domain.repositories import QueueAssumptionsRepository  # noqa: E402
from backend.app.domain.wait_estimation import WaitEstimator  # noqa: E402

DEFAULT_STATIONS = ROOT / "data_platform" / "data" / "static" / "stations.geojson"
DEFAULT_STATUSES = ROOT / "data_platform" / "data" / "runtime" / "station_status.json"
DEFAULT_ASSUMPTIONS = ROOT / "data_platform" / "data" / "demo" / "queue_assumptions.json"


@dataclass(frozen=True)
class StationInput:
    station_id: str
    longitude: float
    latitude: float
    operational_ports: int
    occupied_ports: int
    queue_length: int
    mean_session_min: float
    baseline_rate_per_hour: float


@dataclass(frozen=True)
class Arrival:
    minute: float
    origin_lon: float | None
    origin_lat: float | None
    baseline_station_id: str | None
    service_by_station: tuple[tuple[str, float], ...]


@dataclass
class StationState:
    free_at: list[float]
    sessions: list[tuple[float, float]]


def estimate_backend_wait(
    station: StationInput,
    state: StationState,
    *,
    minute: float,
    wait_estimator: WaitEstimator,
) -> tuple[float, float]:
    simulated_at = datetime.fromtimestamp(minute * 60, tz=UTC)
    occupied = sum(start <= minute < end for start, end in state.sessions)
    queued = sum(start > minute for start, _ in state.sessions)
    status = StationStatus(
        station_id=station.station_id,
        timestamp=simulated_at,
        total_ports=station.operational_ports,
        operational_ports=station.operational_ports,
        occupied_ports=occupied,
        available_ports=station.operational_ports - occupied,
        offline_ports=0,
        unknown_ports=0,
        occupancy_ratio=occupied / station.operational_ports,
        queue_length=queued,
        avg_session_duration_min=station.mean_session_min,
        data_source="simulated",
    )
    forecast = OccupancyForecastResult(
        station_id=station.station_id,
        requested_horizon_min=5,
        used_horizon_min=5,
        predicted_occupancy_ratio=occupied / station.operational_ports,
        predicted_occupied_ports=float(occupied),
        operational_ports=station.operational_ports,
        prediction_source="persistence",
        flags=("SIMULATED_HISTORY",),
    )
    result = wait_estimator.estimate_wait(
        status,
        forecast,
        evaluation_at=simulated_at,
        include_planned_arrivals=False,
    )
    return result.estimated_wait_min, result.estimated_wait_p90_min


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_stations(
    stations_path: Path,
    statuses_path: Path,
    assumptions_path: Path,
) -> tuple[list[StationInput], dict[str, str]]:
    stations_data = json.loads(stations_path.read_text(encoding="utf-8"))
    statuses_data = json.loads(statuses_path.read_text(encoding="utf-8"))
    assumptions_data = json.loads(assumptions_path.read_text(encoding="utf-8"))
    if assumptions_data.get("data_source") != "synthetic":
        raise ValueError("the demo arrival assumptions must declare data_source=synthetic")
    features = stations_data.get("features")
    if not isinstance(features, list):
        raise ValueError("station catalog must contain a features list")
    status_by_id = {
        item["station_id"]: item
        for item in statuses_data
        if isinstance(item, dict) and isinstance(item.get("station_id"), str)
    }
    rate_by_id = {
        item["station_id"]: float(item["baseline_arrival_rate_per_hour"])
        for item in assumptions_data.get("station_rates", [])
    }
    station_inputs = []
    for feature in features:
        properties = feature.get("properties", {})
        station_id = properties.get("station_id")
        status = status_by_id.get(station_id)
        if status is None or station_id not in rate_by_id:
            continue
        if status.get("data_source") != "synthetic":
            raise ValueError(f"status for {station_id} is not marked synthetic")
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if len(coordinates) != 2:
            raise ValueError(f"station {station_id} has invalid coordinates")
        capacity = int(status["operational_ports"])
        occupied = int(status["occupied_ports"])
        queue_length = int(status["queue_length"])
        mean_session = float(status["avg_session_duration_min"])
        rate = rate_by_id[station_id]
        if capacity < 1 or not 0 <= occupied <= capacity or queue_length < 0:
            raise ValueError(f"station {station_id} has invalid synthetic status")
        if not all(math.isfinite(value) for value in (mean_session, rate)):
            raise ValueError(f"station {station_id} has non-finite simulation inputs")
        if mean_session <= 0 or rate < 0:
            raise ValueError(f"station {station_id} has invalid duration or arrival rate")
        station_inputs.append(
            StationInput(
                station_id=station_id,
                longitude=float(coordinates[0]),
                latitude=float(coordinates[1]),
                operational_ports=capacity,
                occupied_ports=occupied,
                queue_length=queue_length,
                mean_session_min=mean_session,
                baseline_rate_per_hour=rate,
            )
        )
    if not station_inputs:
        raise ValueError("no stations have both synthetic status and arrival assumptions")
    station_inputs.sort(key=lambda item: item.station_id)
    hashes = {
        "station_catalog_sha256": sha256_file(stations_path),
        "station_status_sha256": sha256_file(statuses_path),
        "arrival_assumptions_sha256": sha256_file(assumptions_path),
    }
    return station_inputs, hashes


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    radius_km = 6371.0088
    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    delta_lat = lat2_r - lat1_r
    delta_lon = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(min(1.0, value)))


def generate_arrivals(
    stations: list[StationInput],
    *,
    duration_hours: float,
    network_arrivals_per_hour: float,
    seed: int,
) -> list[Arrival]:
    rng = random.Random(seed)
    arrivals: list[Arrival] = []
    duration_min = duration_hours * 60
    station_ids = [station.station_id for station in stations]
    mean_session_by_id = {station.station_id: station.mean_session_min for station in stations}

    def service_samples() -> tuple[tuple[str, float], ...]:
        return tuple(
            (station_id, rng.expovariate(1 / mean_session_by_id[station_id]))
            for station_id in station_ids
        )

    for station in stations:
        if station.baseline_rate_per_hour == 0:
            continue
        minute = rng.expovariate(station.baseline_rate_per_hour) * 60
        while minute < duration_min:
            arrivals.append(
                Arrival(
                    minute=minute,
                    origin_lon=None,
                    origin_lat=None,
                    baseline_station_id=station.station_id,
                    service_by_station=service_samples(),
                )
            )
            minute += rng.expovariate(station.baseline_rate_per_hour) * 60

    if network_arrivals_per_hour > 0:
        longitude_min = min(station.longitude for station in stations)
        longitude_max = max(station.longitude for station in stations)
        latitude_min = min(station.latitude for station in stations)
        latitude_max = max(station.latitude for station in stations)
        minute = rng.expovariate(network_arrivals_per_hour) * 60
        while minute < duration_min:
            arrivals.append(
                Arrival(
                    minute=minute,
                    origin_lon=rng.uniform(longitude_min, longitude_max),
                    origin_lat=rng.uniform(latitude_min, latitude_max),
                    baseline_station_id=None,
                    service_by_station=service_samples(),
                )
            )
            minute += rng.expovariate(network_arrivals_per_hour) * 60
    arrivals.sort(key=lambda item: item.minute)
    return arrivals


def travel_minutes(origin_lon: float, origin_lat: float, station: StationInput) -> float:
    # Straight-line distance scaled to an explicitly synthetic road-time proxy.
    return haversine_km(
        origin_lon, origin_lat, station.longitude, station.latitude
    ) * 1.5 / 25 * 60


def _initialize_states(
    stations: list[StationInput], rng: random.Random
) -> dict[str, StationState]:
    states = {}
    for station in stations:
        free_at = [0.0] * station.operational_ports
        sessions: list[tuple[float, float]] = []
        for _ in range(station.occupied_ports):
            index = min(range(len(free_at)), key=free_at.__getitem__)
            remaining = rng.expovariate(1 / station.mean_session_min)
            free_at[index] = remaining
            sessions.append((0.0, remaining))
        for _ in range(station.queue_length):
            index = min(range(len(free_at)), key=free_at.__getitem__)
            start = free_at[index]
            end = start + rng.expovariate(1 / station.mean_session_min)
            free_at[index] = end
            sessions.append((start, end))
        states[station.station_id] = StationState(free_at=free_at, sessions=sessions)
    return states


def simulate_policy(
    stations: list[StationInput],
    arrivals: list[Arrival],
    *,
    policy: Literal["nearest", "load_aware"],
    seed: int,
    duration_hours: float,
    capacity_wait_multiplier: float = 1.0,
    wait_estimator: WaitEstimator | None = None,
) -> dict[str, Any]:
    states = _initialize_states(stations, random.Random(seed))
    station_by_id = {station.station_id: station for station in stations}
    network_travel_values = []
    network_wait_values = []
    network_charge_values = []
    predicted_wait_values = []
    predicted_p90_values = []
    wait_values = []
    charge_values = []
    selected_counts = {station.station_id: 0 for station in stations}
    for arrival in arrivals:
        if arrival.baseline_station_id is not None:
            chosen = station_by_id[arrival.baseline_station_id]
            drive_min = 0.0
        else:
            assert arrival.origin_lon is not None and arrival.origin_lat is not None
            options = []
            for station in stations:
                drive_min = travel_minutes(arrival.origin_lon, arrival.origin_lat, station)
                if wait_estimator is None:
                    earliest_free = min(states[station.station_id].free_at)
                    expected_wait = max(0.0, earliest_free - arrival.minute)
                    expected_wait_p90 = expected_wait
                else:
                    expected_wait, expected_wait_p90 = estimate_backend_wait(
                        station,
                        states[station.station_id],
                        minute=arrival.minute,
                        wait_estimator=wait_estimator,
                    )
                score = drive_min + (
                    expected_wait * capacity_wait_multiplier if policy == "load_aware" else 0
                )
                options.append(
                    (
                        score,
                        station.station_id,
                        station,
                        drive_min,
                        expected_wait,
                        expected_wait_p90,
                    )
                )
            _, _, chosen, drive_min, expected_wait, expected_wait_p90 = min(options)
        state = states[chosen.station_id]
        port_index = min(range(len(state.free_at)), key=state.free_at.__getitem__)
        start = max(arrival.minute, state.free_at[port_index])
        end = start + dict(arrival.service_by_station)[chosen.station_id]
        state.free_at[port_index] = end
        state.sessions.append((start, end))
        wait_values.append(start - arrival.minute)
        charge_values.append(end - start)
        if arrival.baseline_station_id is None:
            selected_counts[chosen.station_id] += 1
            network_travel_values.append(drive_min)
            network_wait_values.append(start - arrival.minute)
            network_charge_values.append(end - start)
            predicted_wait_values.append(expected_wait)
            predicted_p90_values.append(expected_wait_p90)

    duration_min = duration_hours * 60
    occupancy_values = []
    for minute in range(0, int(duration_min), 5):
        for station in stations:
            active = sum(
                start <= minute < end
                for start, end in states[station.station_id].sessions
            )
            occupancy_values.append(min(1.0, active / station.operational_ports))
    next_bucket_errors = []
    for index in range(max(0, len(occupancy_values) - len(stations))):
        next_bucket_errors.append(
            abs(occupancy_values[index] - occupancy_values[index + len(stations)])
        )
    station_sample_count = max(1, len(occupancy_values))
    network_trip_time = [
        travel + wait + charge
        for travel, wait, charge in zip(
            network_travel_values,
            network_wait_values,
            network_charge_values,
            strict=True,
        )
    ]
    return {
        "policy": policy,
        "network_customer_count": sum(selected_counts.values()),
        "baseline_customer_count": len(arrivals) - sum(selected_counts.values()),
        "mean_network_drive_min": round(statistics.fmean(network_travel_values), 3)
        if network_travel_values
        else 0,
        "mean_network_wait_min": round(statistics.fmean(network_wait_values), 3)
        if network_wait_values
        else 0,
        "network_p90_wait_min": round(_quantile(network_wait_values, 0.90), 3)
        if network_wait_values
        else 0,
        "network_predicted_wait_mae_min": round(
            statistics.fmean(
                abs(predicted - actual)
                for predicted, actual in zip(
                    predicted_wait_values, network_wait_values, strict=True
                )
            ),
            3,
        )
        if predicted_wait_values
        else 0,
        "network_predicted_wait_p90_coverage": round(
            sum(
                actual <= predicted
                for actual, predicted in zip(
                    network_wait_values, predicted_p90_values, strict=True
                )
            )
            / len(network_wait_values),
            4,
        )
        if predicted_p90_values
        else 0,
        "mean_wait_min": round(statistics.fmean(wait_values), 3) if wait_values else 0,
        "p90_wait_min": round(_quantile(wait_values, 0.90), 3) if wait_values else 0,
        "mean_charge_min": round(statistics.fmean(charge_values), 3) if charge_values else 0,
        "mean_network_trip_service_min": round(statistics.fmean(network_trip_time), 3)
        if network_trip_time
        else 0,
        "mean_sampled_occupancy_ratio": round(
            sum(occupancy_values) / station_sample_count, 4
        ),
        "peak_sampled_occupancy_ratio": round(max(occupancy_values, default=0), 4),
        "next_bucket_persistence_mae": round(statistics.fmean(next_bucket_errors), 5)
        if next_bucket_errors
        else 0,
        "network_assignments_by_station": selected_counts,
    }


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def run_study(
    stations: list[StationInput],
    *,
    duration_hours: float,
    network_arrivals_per_hour: float,
    seed: int,
    capacity_wait_multiplier: float,
    wait_estimator: WaitEstimator | None = None,
) -> dict[str, Any]:
    arrivals = generate_arrivals(
        stations,
        duration_hours=duration_hours,
        network_arrivals_per_hour=network_arrivals_per_hour,
        seed=seed,
    )
    return {
        "data_source": "synthetic",
        "data_domain": "hcmc_synthetic_demo",
        "release_evidence": False,
        "training_data": False,
        "seed": seed,
        "duration_hours": duration_hours,
        "network_arrivals_per_hour": network_arrivals_per_hour,
        "capacity_wait_multiplier": capacity_wait_multiplier,
        "station_count": len(stations),
        "arrival_count": len(arrivals),
        "methodology": {
            "nearest": "minimum synthetic straight-line road-time proxy",
            "load_aware": "minimum road-time proxy plus estimated queue wait",
            "wait_estimator": (
                "backend WaitEstimator with persistence forecast and synthetic queue inputs"
                if wait_estimator is not None
                else "simulator exact-queue oracle (unit-study fallback only)"
            ),
            "service_duration": "exponential with synthetic station mean",
            "occupancy_sampling_min": 5,
            "limitations": [
                "not calibrated to observed HCMC arrivals or service durations",
                "road time is a straight-line distance proxy, not provider routing",
                "wait estimates use synthetic event state and do not validate "
                "operational calibration",
                "persistence MAE is measured only against synthetic generated occupancy",
            ],
        },
        "input_hashes": {},
        "results": [
            simulate_policy(
                stations,
                arrivals,
                policy=policy,
                seed=seed,
                duration_hours=duration_hours,
                capacity_wait_multiplier=capacity_wait_multiplier,
                wait_estimator=wait_estimator,
            )
            for policy in ("nearest", "load_aware")
        ],
    }


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be finite and positive")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("value must be finite and non-negative")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stations", type=Path, default=DEFAULT_STATIONS)
    parser.add_argument("--statuses", type=Path, default=DEFAULT_STATUSES)
    parser.add_argument("--assumptions", type=Path, default=DEFAULT_ASSUMPTIONS)
    parser.add_argument("--duration-hours", type=positive_float, default=24)
    parser.add_argument("--network-arrivals-per-hour", type=nonnegative_float, default=12)
    parser.add_argument("--capacity-wait-multiplier", type=nonnegative_float, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--report", type=Path, default=ROOT / "build" / "simulation" / "hcmc_network_load.json"
    )
    args = parser.parse_args()
    if args.seed < 0:
        parser.error("--seed must be non-negative")
    try:
        stations, hashes = load_stations(args.stations, args.statuses, args.assumptions)
        report = run_study(
            stations,
            duration_hours=args.duration_hours,
            network_arrivals_per_hour=args.network_arrivals_per_hour,
            seed=args.seed,
            capacity_wait_multiplier=args.capacity_wait_multiplier,
            wait_estimator=WaitEstimator(
                QueueAssumptionsRepository.from_file(args.assumptions)
            ),
        )
        report["input_hashes"] = hashes
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Synthetic study written: {args.report}")
    for result in report["results"]:
        print(
            f"{result['policy']}: arrivals={result['network_customer_count']} "
            f"network_mean_wait={result['mean_network_wait_min']} min "
            f"network_p90_wait={result['network_p90_wait_min']} min "
            f"wait_mae={result['network_predicted_wait_mae_min']} min "
            f"peak_occupancy={result['peak_sampled_occupancy_ratio']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
