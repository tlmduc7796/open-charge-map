#!/usr/bin/env python3
"""Create physically constrained, Vietnam-topology synthetic ML datasets.

This is an offline evaluation-data generator.  ACN supplies only a de-identified
behavior prior through CTGAN; the station catalogue supplies capacity constraints.
Every emitted row is explicitly synthetic and must not be presented as observed
Vietnamese charging behavior.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .data_pipeline.contracts import validate_occupancy, validate_sessions, validate_telemetry
    from .data_pipeline.manifests import write_dataset_manifest
    from .data_pipeline.splits import TemporalSplitConfig, assign_temporal_split
except ImportError:  # pragma: no cover - direct CLI invocation.
    from data_pipeline.contracts import validate_occupancy, validate_sessions, validate_telemetry
    from data_pipeline.manifests import write_dataset_manifest
    from data_pipeline.splits import TemporalSplitConfig, assign_temporal_split


VN_TZ = "Asia/Ho_Chi_Minh"
FEATURES = (
    "arrival_hour",
    "arrival_weekday",
    "stay_min",
    "charge_min",
    "energy_kwh",
    "requested_energy_kwh",
    "minutes_available",
)


@dataclass(frozen=True)
class Port:
    station_id: str
    port_id: str
    connector_type: str
    current: str
    max_power_kw: float


def _topology(catalog_path: Path) -> tuple[pd.DataFrame, list[Port]]:
    """Use only provider-reported technical topology by default.

    The candidate catalogue contains demo-inferred connectors.  Those are useful
    for UI exploration but must not silently become physical constraints for a
    gold ML dataset, so they are excluded here.
    """
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    candidates = catalog.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Station catalog must contain candidates")
    station_rows: list[dict] = []
    ports: list[Port] = []
    for candidate in candidates:
        technical = candidate.get("technical") or {}
        verification = candidate.get("verification") or {}
        station_id = candidate.get("matched_station_id")
        connectors = technical.get("connectors")
        if (
            verification.get("technical_status") != "provider_reported"
            or not station_id
            or not isinstance(connectors, list)
        ):
            continue
        before = len(ports)
        for connector in connectors:
            count = connector.get("count")
            power = connector.get("max_power_kw")
            kind = connector.get("type")
            current = connector.get("current")
            if (
                not isinstance(count, int)
                or count <= 0
                or not isinstance(power, (int, float))
                or power <= 0
            ):
                continue
            if not isinstance(kind, str) or not isinstance(current, str):
                continue
            for _ in range(count):
                ports.append(
                    Port(
                        station_id=station_id,
                        port_id=f"{station_id}_P{len(ports) - before + 1}",
                        connector_type=kind,
                        current=current,
                        max_power_kw=float(power),
                    )
                )
        port_count = len(ports) - before
        if port_count:
            station_rows.append(
                {
                    "station_id": station_id,
                    "station_name": candidate.get("name"),
                    "lat": (candidate.get("location") or {}).get("lat"),
                    "lon": (candidate.get("location") or {}).get("lon"),
                    "total_ports": port_count,
                    "topology_confidence": "provider_reported",
                    "is_synthetic": True,
                }
            )
    if not ports:
        raise ValueError("No provider-reported station topology available")
    return pd.DataFrame(station_rows).drop_duplicates("station_id"), ports


def _sample_behavior(model_path: Path, count: int, rng: np.random.Generator) -> pd.DataFrame:
    try:
        from sdv.single_table import CTGANSynthesizer
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install ml/requirements.txt before sampling CTGAN") from exc
    model = CTGANSynthesizer.load(model_path)
    # SDV controls its own random state.  Reordering does not change the source
    # model, while this local shuffle makes station allocation reproducible.
    sampled = model.sample(num_rows=count).loc[:, list(FEATURES)].copy()
    return sampled.iloc[rng.permutation(len(sampled))].reset_index(drop=True)


def _sample_arrivals(
    behavior: pd.DataFrame,
    stations: pd.DataFrame,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    sessions_per_port_day: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    days = pd.date_range(start.normalize(), end.normalize(), freq="D", tz=VN_TZ)
    rows: list[dict] = []
    behavior = behavior.copy()
    behavior["arrival_hour"] = (
        pd.to_numeric(behavior["arrival_hour"], errors="coerce")
        .fillna(12)
        .round()
        .clip(0, 23)
        .astype(int)
    )
    behavior["arrival_weekday"] = (
        pd.to_numeric(behavior["arrival_weekday"], errors="coerce")
        .fillna(0)
        .round()
        .mod(7)
        .astype(int)
    )
    by_weekday = {
        day: group.reset_index(drop=True) for day, group in behavior.groupby("arrival_weekday")
    }
    if set(by_weekday) != set(range(7)):
        # CTGAN may omit a category; all observed behavior remains a valid fallback.
        by_weekday = {day: behavior.reset_index(drop=True) for day in range(7)}
    for station in stations.itertuples(index=False):
        daily_mean = station.total_ports * sessions_per_port_day
        for day in days:
            count = int(rng.poisson(daily_mean))
            source = by_weekday[day.dayofweek]
            indices = rng.integers(0, len(source), size=count)
            for value in source.iloc[indices].itertuples(index=False):
                minute = int(rng.integers(0, 60))
                arrival_at = day + pd.Timedelta(hours=int(value.arrival_hour), minutes=minute)
                if start <= arrival_at < end:
                    rows.append(
                        {
                            "station_id": station.station_id,
                            "arrival_at": arrival_at,
                            **value._asdict(),
                        }
                    )
    return pd.DataFrame(rows).sort_values(["station_id", "arrival_at"]).reset_index(drop=True)


def _constrain_and_allocate(
    arrivals: pd.DataFrame,
    ports: list[Port],
    *,
    max_wait_min: int,
    window_end: pd.Timestamp,
) -> pd.DataFrame:
    by_station: dict[str, list[Port]] = {}
    for port in ports:
        by_station.setdefault(port.station_id, []).append(port)
    output: list[dict] = []
    next_free: dict[str, pd.Timestamp] = {}
    session_number = 0
    for row in arrivals.itertuples(index=False):
        candidates = by_station[row.station_id]
        port = min(
            candidates, key=lambda candidate: next_free.get(candidate.port_id, row.arrival_at)
        )
        connection = max(row.arrival_at, next_free.get(port.port_id, row.arrival_at))
        wait_min = (connection - row.arrival_at).total_seconds() / 60
        if wait_min > max_wait_min:
            continue
        stay_min = float(np.clip(pd.to_numeric(row.stay_min, errors="coerce"), 10, 24 * 60))
        charge_min = float(np.clip(pd.to_numeric(row.charge_min, errors="coerce"), 5, stay_min))
        charge_min = min(charge_min, stay_min)
        requested = float(max(0, pd.to_numeric(row.requested_energy_kwh, errors="coerce")))
        energy = float(max(0, pd.to_numeric(row.energy_kwh, errors="coerce")))
        # Energy cannot exceed port power times charging duration.  The 0.92
        # factor is a declared charging-efficiency assumption, not a measurement.
        physical_max = port.max_power_kw * charge_min / 60 * 0.92
        energy = min(energy, requested if requested > 0 else energy, physical_max)
        done = connection + pd.Timedelta(minutes=charge_min)
        disconnect = connection + pd.Timedelta(minutes=stay_min)
        # The Gold window contains complete target labels only.  Carry-over
        # sessions would belong to the following scenario window instead.
        if disconnect > window_end:
            continue
        session_number += 1
        output.append(
            {
                "session_id": f"GOLD_SYN_{session_number:08d}",
                "station_id": port.station_id,
                "port_id": port.port_id,
                "connector_type": port.connector_type,
                "arrival_at": row.arrival_at,
                "connection_at": connection,
                "done_charging_at": done,
                "disconnect_at": disconnect,
                "final_energy_delivered_kwh": round(energy, 4),
                "max_port_power_kw": port.max_power_kw,
                "wait_min": round(wait_min, 3),
                "source": "acn_ctgan_conditioned_vietnam_topology",
                "schema_version": "gold-synthetic-1",
                "quality_flag": "synthetic_evaluation_only",
                "is_censored": False,
                "censoring_at": pd.NaT,
                "is_synthetic": True,
            }
        )
        next_free[port.port_id] = disconnect
    result = pd.DataFrame(output)
    if result.empty:
        raise ValueError("No sessions survived capacity allocation")
    return validate_sessions(result)


def _telemetry(sessions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for session in sessions.itertuples(index=False):
        total_seconds = max((session.done_charging_at - session.connection_at).total_seconds(), 1)
        timestamps = pd.date_range(
            session.connection_at.ceil("5min"), session.done_charging_at, freq="5min", tz="UTC"
        )
        if timestamps.empty or timestamps[-1] != session.done_charging_at:
            timestamps = timestamps.append(pd.DatetimeIndex([session.done_charging_at]))
        for observed_at in timestamps.unique():
            progress = min(
                max((observed_at - session.connection_at).total_seconds() / total_seconds, 0), 1
            )
            power = session.final_energy_delivered_kwh / (total_seconds / 3600)
            rows.append(
                {
                    "session_id": session.session_id,
                    "station_id": session.station_id,
                    "port_id": session.port_id,
                    "observed_at": observed_at,
                    "received_at": observed_at,
                    "energy_delivered_kwh": round(session.final_energy_delivered_kwh * progress, 4),
                    "current_power_kw": round(power, 4),
                    "source": session.source,
                    "schema_version": "gold-synthetic-1",
                    "quality_flag": "synthetic_piecewise_constant",
                    "is_backfilled": False,
                    "is_synthetic": True,
                }
            )
    return validate_telemetry(pd.DataFrame(rows))


def _occupancy(
    sessions: pd.DataFrame, stations: pd.DataFrame, *, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    timeline = pd.date_range(start, end, freq="5min", inclusive="left", tz=VN_TZ).tz_convert("UTC")
    rows: list[pd.DataFrame] = []
    for station in stations.itertuples(index=False):
        changes = np.zeros(len(timeline) + 1, dtype=np.int32)
        current = sessions.loc[sessions["station_id"] == station.station_id]
        for value in current.itertuples(index=False):
            left = int(timeline.searchsorted(value.connection_at, side="left"))
            right = int(timeline.searchsorted(value.disconnect_at, side="left"))
            left, right = max(left, 0), min(right, len(timeline))
            if left < right:
                changes[left] += 1
                changes[right] -= 1
        occupied = np.cumsum(changes[:-1])
        rows.append(
            pd.DataFrame(
                {
                    "observed_at": timeline,
                    "received_at": timeline,
                    "station_id": station.station_id,
                    "occupied_ports": occupied,
                    "available_ports": station.total_ports - occupied,
                    "offline_ports": 0,
                    "total_ports": station.total_ports,
                    "occupancy_ratio": occupied / station.total_ports,
                    "source": "acn_ctgan_conditioned_vietnam_topology",
                    "schema_version": "gold-synthetic-1",
                    "quality_flag": "synthetic_replay_from_sessions",
                    "is_backfilled": False,
                    "is_synthetic": True,
                }
            )
        )
    result = validate_occupancy(pd.concat(rows, ignore_index=True))
    # Legacy model builders use these aliases.  Keep the canonical fields above
    # as the authoritative contract, while making this Gold product directly
    # consumable by the existing occupancy feature builder.
    result["timestamp"] = result["observed_at"]
    result["entity_id"] = result["station_id"]
    result["interval_min"] = 5
    return result


def build_gold(
    *,
    model_path: Path,
    catalog_path: Path,
    output_dir: Path,
    start: str,
    end: str,
    sessions_per_port_day: float,
    seed: int,
) -> dict[str, object]:
    if sessions_per_port_day <= 0:
        raise ValueError("sessions_per_port_day must be positive")
    start_at = pd.Timestamp(start, tz=VN_TZ)
    end_at = pd.Timestamp(end, tz=VN_TZ)
    if end_at <= start_at + timedelta(days=14):
        raise ValueError("Gold window must exceed 14 days")
    stations, ports = _topology(catalog_path)
    rng = np.random.default_rng(seed)
    expected = int(
        stations["total_ports"].sum() * sessions_per_port_day * (end_at - start_at).days * 1.15
    )
    behavior = _sample_behavior(model_path, max(expected, 1_000), rng)
    arrivals = _sample_arrivals(
        behavior,
        stations,
        start=start_at,
        end=end_at,
        sessions_per_port_day=sessions_per_port_day,
        rng=rng,
    )
    sessions = _constrain_and_allocate(
        arrivals,
        ports,
        max_wait_min=120,
        window_end=end_at,
    )
    telemetry = _telemetry(sessions)
    occupancy = _occupancy(sessions, stations, start=start_at, end=end_at)
    split = TemporalSplitConfig(
        start_at + (end_at - start_at) * 0.60,
        start_at + (end_at - start_at) * 0.80,
    )
    sessions = assign_temporal_split(sessions, split, timestamp_column="disconnect_at")
    telemetry = telemetry.merge(sessions[["session_id", "split"]], on="session_id", how="inner")
    occupancy = assign_temporal_split(occupancy, split, timestamp_column="observed_at")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "stations": output_dir / "stations.parquet",
        "ports": output_dir / "ports.parquet",
        "sessions": output_dir / "sessions.parquet",
        "telemetry": output_dir / "telemetry_5min.parquet",
        "occupancy": output_dir / "occupancy_5min.parquet",
    }
    stations.to_parquet(paths["stations"], index=False)
    pd.DataFrame([port.__dict__ for port in ports]).to_parquet(paths["ports"], index=False)
    sessions.to_parquet(paths["sessions"], index=False)
    telemetry.to_parquet(paths["telemetry"], index=False)
    occupancy.to_parquet(paths["occupancy"], index=False)
    extra = {
        "is_synthetic": True,
        "usage": (
            "offline model development and evaluation only; not Vietnamese observed ground truth"
        ),
        "behavior_prior": str(model_path),
        "topology_policy": "provider_reported matched stations only",
        "physical_constraints": [
            "one session per port",
            "max port power",
            "120-minute queue limit",
        ],
        "timezone": VN_TZ,
        "seed": seed,
    }
    manifests = {
        name: str(
            write_dataset_manifest(
                path,
                frame,
                dataset_kind=f"gold_synthetic_{name}",
                source_paths=[catalog_path, model_path],
                extra=extra,
            )
        )
        for name, path, frame in (
            ("stations", paths["stations"], stations),
            ("ports", paths["ports"], pd.DataFrame([port.__dict__ for port in ports])),
            ("sessions", paths["sessions"], sessions),
            ("telemetry", paths["telemetry"], telemetry),
            ("occupancy", paths["occupancy"], occupancy),
        )
    }
    return {
        "output_dir": str(output_dir),
        "station_count": int(len(stations)),
        "port_count": int(len(ports)),
        "sessions": int(len(sessions)),
        "telemetry_rows": int(len(telemetry)),
        "occupancy_rows": int(len(occupancy)),
        "paths": {name: str(path) for name, path in paths.items()},
        "manifests": manifests,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--stations", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-04-01")
    parser.add_argument("--sessions-per-port-day", type=float, default=1.5)
    parser.add_argument("--seed", type=int, default=20261004)
    args = parser.parse_args()
    print(
        json.dumps(
            build_gold(
                model_path=args.model,
                catalog_path=args.stations,
                output_dir=args.output_dir,
                start=args.start,
                end=args.end,
                sessions_per_port_day=args.sessions_per_port_day,
                seed=args.seed,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
