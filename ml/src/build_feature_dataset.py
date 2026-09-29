#!/usr/bin/env python3
"""Build a leakage-safe, versioned feature dataset; this command never trains."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:  # Supports both `python ml/src/...py` and package imports in tests/notebooks.
    from .feature_contract import (
        CONTRACT_VERSION,
        HORIZONS_MIN,
        INTERVAL_MIN,
        LOOKBACK_STEPS,
        get_feature_profile,
        target_column,
    )
except ImportError:  # pragma: no cover - executed only for direct script invocation.
    from feature_contract import (
        CONTRACT_VERSION,
        HORIZONS_MIN,
        INTERVAL_MIN,
        LOOKBACK_STEPS,
        get_feature_profile,
        target_column,
    )

ROOT_DIR = Path(__file__).resolve().parents[2]


def _read_parquet(path: Path, label: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"{label} file not found: {path}")
    return pd.read_parquet(path)


def _validate_occupancy(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "entity_id", "occupancy_ratio", "split", "interval_min"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Processed occupancy data misses columns: {sorted(missing)}")
    result = frame.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], errors="raise")
    if not (result["interval_min"] == INTERVAL_MIN).all():
        raise ValueError(f"Only {INTERVAL_MIN}-minute occupancy data is supported")
    if not result["split"].isin(["train", "val", "test"]).all():
        raise ValueError("Occupancy split must contain only train/val/test")
    if result.duplicated(["entity_id", "timestamp"]).any():
        raise ValueError("Duplicate occupancy observations detected")
    if not result["occupancy_ratio"].between(0, 1).all():
        raise ValueError("occupancy_ratio must be within [0, 1]")
    return result.sort_values(["entity_id", "timestamp"]).reset_index(drop=True)


def _join_context(
    frame: pd.DataFrame,
    *,
    profile_name: str,
    calendar_path: Path | None,
    weather_path: Path | None,
) -> pd.DataFrame:
    profile = get_feature_profile(profile_name)
    result = frame
    if "calendar" in profile.required_inputs:
        if calendar_path is None:
            raise ValueError(f"Profile {profile.name!r} requires --calendar")
        calendar = _read_parquet(calendar_path, "Calendar")
        calendar["timestamp"] = pd.to_datetime(calendar["timestamp"], errors="raise")
        calendar_columns = [name for name in profile.feature_names if name not in result.columns]
        missing = set(calendar_columns) - set(calendar.columns)
        if missing:
            raise ValueError(f"Calendar file misses columns: {sorted(missing)}")
        result = result.merge(
            calendar[["timestamp", *calendar_columns]], on="timestamp", how="left"
        )
    if "weather" in profile.required_inputs:
        if weather_path is None:
            raise ValueError(f"Profile {profile.name!r} requires --weather")
        weather = _read_parquet(weather_path, "Weather")
        weather["timestamp"] = pd.to_datetime(weather["timestamp"], errors="raise")
        weather_columns = [name for name in profile.feature_names if name not in result.columns]
        missing = set(weather_columns) - set(weather.columns)
        if missing:
            raise ValueError(f"Weather file misses columns: {sorted(missing)}")
        result = result.merge(weather[["timestamp", *weather_columns]], on="timestamp", how="left")
    return result


def build_feature_dataset(
    occupancy_path: Path,
    output_path: Path,
    *,
    profile_name: str,
    calendar_path: Path | None = None,
    weather_path: Path | None = None,
) -> dict[str, object]:
    """Create supervised rows, preserving the original temporal split exactly."""
    profile = get_feature_profile(profile_name)
    frame = _join_context(
        _validate_occupancy(_read_parquet(occupancy_path, "Processed occupancy")),
        profile_name=profile_name,
        calendar_path=calendar_path,
        weather_path=weather_path,
    )
    grouped = frame.groupby("entity_id", sort=False)["occupancy_ratio"]
    for step in range(1, LOOKBACK_STEPS + 1):
        frame[f"lag_{step}"] = grouped.shift(step)
    for horizon in HORIZONS_MIN:
        frame[target_column(horizon)] = grouped.shift(-(horizon // INTERVAL_MIN))

    required = [*profile.feature_names, *(target_column(item) for item in HORIZONS_MIN)]
    result = frame.dropna(subset=required).copy()
    # A supervised row belongs to the split of every target it contains, never
    # merely its final lag.  Discard boundary rows rather than leaking labels.
    split_grouped = frame.groupby("entity_id", sort=False)["split"]
    same_split = pd.Series(True, index=frame.index)
    for horizon in HORIZONS_MIN:
        target_split = split_grouped.shift(-(horizon // INTERVAL_MIN))
        same_split &= target_split == frame["split"]
    result = result.loc[same_split.loc[result.index]].copy()
    if result.empty:
        raise ValueError("No trainable rows after lag/target and split-boundary filtering")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "profile": profile.name,
        "feature_names": list(profile.feature_names),
        "target_columns": [target_column(item) for item in HORIZONS_MIN],
        "lookback_steps": LOOKBACK_STEPS,
        "horizons_min": list(HORIZONS_MIN),
        "serving_ready": profile.serving_ready,
        "serving_reason": profile.serving_reason,
        "input_files": {
            "occupancy": str(occupancy_path),
            "calendar": str(calendar_path) if calendar_path else None,
            "weather": str(weather_path) if weather_path else None,
        },
        "records_by_split": {
            split: int(count)
            for split, count in result["split"].value_counts().sort_index().items()
        },
    }
    meta_path = output_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {**metadata, "output_path": str(output_path), "metadata_path": str(meta_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--occupancy", type=Path, default=ROOT_DIR / "ml/artifacts/urbanev_processed.parquet"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT_DIR / "ml/artifacts/occupancy_features_baseline.parquet",
    )
    parser.add_argument(
        "--profile", choices=("baseline", "temporal", "context"), default="baseline"
    )
    parser.add_argument("--calendar", type=Path)
    parser.add_argument("--weather", type=Path)
    args = parser.parse_args()
    summary = build_feature_dataset(
        args.occupancy, args.output, profile_name=args.profile,
        calendar_path=args.calendar, weather_path=args.weather,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
