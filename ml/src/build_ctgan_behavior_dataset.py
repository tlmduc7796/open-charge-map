#!/usr/bin/env python3
"""Build a privacy-minimized ACN behavioral table for a CTGAN experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:
    from .data_pipeline.manifests import write_dataset_manifest
    from .data_pipeline.splits import TemporalSplitConfig, assign_temporal_split
except ImportError:  # pragma: no cover
    from data_pipeline.manifests import write_dataset_manifest
    from data_pipeline.splits import TemporalSplitConfig, assign_temporal_split


def _last_user_input(values: object, field: str) -> object:
    if not isinstance(values, list) or not values:
        return None
    latest = values[-1]
    return latest.get(field) if isinstance(latest, dict) else None


def build_behavior_dataset(
    source_paths: Path | list[Path], output_path: Path, *, split_config: TemporalSplitConfig
) -> dict[str, object]:
    """Extract session behavior, excluding user and station identifiers.

    This dataset is a source-domain behavior prior.  It deliberately excludes
    ACN's user ID, space/station IDs and final disconnect timestamp from CTGAN
    features; the target topology and DES engine supply physical assignments.
    """
    if isinstance(source_paths, Path):
        source_paths = [source_paths]
    if not source_paths:
        raise ValueError("At least one ACN raw export is required")
    records: list[dict] = []
    seen_ids: set[str] = set()
    for source_path in source_paths:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        source_records = payload.get("_items")
        if not isinstance(source_records, list):
            raise ValueError(f"ACN raw export must have an _items list: {source_path}")
        for record in source_records:
            identifier = str(record.get("_id") or record.get("sessionID") or "")
            if not identifier:
                raise ValueError(f"ACN session has no stable ID: {source_path}")
            if identifier not in seen_ids:
                seen_ids.add(identifier)
                records.append(record)
    frame = pd.DataFrame(records)
    connection = pd.to_datetime(frame["connectionTime"], utc=True, errors="coerce")
    disconnect = pd.to_datetime(frame["disconnectTime"], utc=True, errors="coerce")
    done = pd.to_datetime(frame.get("doneChargingTime"), utc=True, errors="coerce")
    user_inputs = frame.get("userInputs", pd.Series([[]] * len(frame)))
    requested = user_inputs.map(lambda values: _last_user_input(values, "kWhRequested"))
    available = user_inputs.map(lambda values: _last_user_input(values, "minutesAvailable"))
    result = pd.DataFrame(
        {
            "arrival_at": connection,
            "arrival_hour": connection.dt.hour,
            "arrival_weekday": connection.dt.dayofweek,
            "stay_min": (disconnect - connection).dt.total_seconds() / 60,
            "charge_min": (done - connection).dt.total_seconds() / 60,
            "energy_kwh": pd.to_numeric(frame.get("kWhDelivered"), errors="coerce"),
            "requested_energy_kwh": pd.to_numeric(requested, errors="coerce"),
            "minutes_available": pd.to_numeric(available, errors="coerce"),
            "source": "acn_data",
            "is_synthetic": False,
        }
    )
    result = result.dropna(subset=["arrival_at", "stay_min", "energy_kwh"])
    result = result.loc[(result["stay_min"] > 0) & (result["energy_kwh"] >= 0)].copy()
    if result.empty:
        raise ValueError("No complete ACN sessions available for CTGAN behavior training")
    result = assign_temporal_split(result, split_config, timestamp_column="arrival_at")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)
    manifest = write_dataset_manifest(
        output_path,
        result,
        dataset_kind="ctgan_behavior_source",
        source_paths=source_paths,
        extra={
            "privacy": "user_id, session_id, station_id and port_id excluded",
            "usage": "source-domain behavior prior; not Vietnamese ground truth",
            "target_mapping": "topology and DES mapping are separate downstream steps",
        },
    )
    return {
        "output": str(output_path),
        "manifest": str(manifest),
        "records": int(len(result)),
        "source_exports": len(source_paths),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-end", required=True)
    parser.add_argument("--validation-end", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build_behavior_dataset(
                args.input,
                args.output,
                split_config=TemporalSplitConfig(args.train_end, args.validation_end),
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
