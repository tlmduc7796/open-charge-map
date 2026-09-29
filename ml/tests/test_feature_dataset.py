"""Contract tests for leakage-safe feature dataset generation."""

from __future__ import annotations

import pandas as pd

from ml.src.build_feature_dataset import build_feature_dataset


def test_baseline_feature_builder_keeps_targets_in_their_temporal_split(tmp_path):
    timestamps = pd.date_range("2024-01-01", periods=60, freq="5min")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "entity_id": ["station-a"] * len(timestamps),
            "occupancy_ratio": [index / 100 for index in range(len(timestamps))],
            "split": ["train"] * 30 + ["val"] * 15 + ["test"] * 15,
            "interval_min": 5,
        }
    )
    input_path = tmp_path / "occupancy.parquet"
    output_path = tmp_path / "features.parquet"
    frame.to_parquet(input_path, index=False)

    metadata = build_feature_dataset(input_path, output_path, profile_name="baseline")
    result = pd.read_parquet(output_path)

    assert metadata["profile"] == "baseline"
    assert metadata["serving_ready"] is True
    assert set(result["split"]) == {"train", "val", "test"}
    # At each split boundary, the maximum 15-minute target is discarded.
    assert len(result) < len(frame) - 12 - 3
    assert result.filter(regex="^lag_").isna().sum().sum() == 0
    assert result.filter(regex="^target_").isna().sum().sum() == 0
