"""Canonical occupancy preparation and model-agnostic supervised datasets."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .adapters import normalize_occupancy_source
from .manifests import write_dataset_manifest
from .splits import TemporalSplitConfig, assign_temporal_split


def prepare_occupancy_history(
    source_path: Path,
    output_path: Path,
    *,
    source: str,
    split_config: TemporalSplitConfig,
) -> dict[str, object]:
    """Write a canonical, split occupancy history from a source export.

    The output retains actual counts and freshness metadata.  It intentionally
    has no lags, seasonal priors, calendar or target labels; those belong to a
    model-independent supervised-dataset build step.
    """
    if source_path.suffix.lower() == ".parquet":
        raw = pd.read_parquet(source_path)
    elif source_path.suffix.lower() == ".csv":
        raw = pd.read_csv(source_path)
    else:
        raise ValueError("Occupancy source must be a parquet or CSV export")
    canonical = normalize_occupancy_source(raw, source=source)
    canonical = assign_temporal_split(canonical, split_config, timestamp_column="observed_at")
    # Keep legacy aliases only in the canonical occupancy product.  Existing
    # feature code and artifact adapters can migrate without a risky big bang.
    canonical["timestamp"] = canonical["observed_at"]
    canonical["entity_id"] = canonical["station_id"]
    canonical["interval_min"] = _infer_interval(canonical)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canonical.to_parquet(output_path, index=False)
    manifest_path = write_dataset_manifest(
        output_path,
        canonical,
        dataset_kind="canonical_occupancy_history",
        source_paths=[source_path],
        extra={
            "source": source,
            "split_policy": {
                "timestamp": "observed_at",
                "train_end": split_config.train_end_utc.isoformat(),
                "validation_end": split_config.validation_end_utc.isoformat(),
            },
        },
    )
    return {
        "output_path": str(output_path),
        "manifest_path": str(manifest_path),
        "records": int(len(canonical)),
        "records_by_split": {
            key: int(value) for key, value in canonical["split"].value_counts().items()
        },
    }


def _infer_interval(frame: pd.DataFrame) -> int:
    """Refuse irregular histories instead of silently pretending they are 5-minute data."""
    intervals: list[float] = []
    for _, station in frame.groupby("station_id", sort=False):
        delta = station["observed_at"].sort_values().diff().dropna().dt.total_seconds() / 60
        intervals.extend(delta.tolist())
    if not intervals:
        raise ValueError("Cannot infer cadence from fewer than two occupancy observations")
    unique = pd.Series(intervals).round(8).unique()
    if len(unique) != 1 or unique[0] <= 0:
        raise ValueError(
            "Occupancy history has irregular cadence; resample with a documented policy first"
        )
    return int(unique[0])
