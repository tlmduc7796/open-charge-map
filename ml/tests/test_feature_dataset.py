"""Contract tests for leakage-safe feature dataset generation."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ml.src.build_feature_dataset import build_feature_dataset
from ml.src.feature_contract import HORIZONS_MIN, SEASONAL_PRIOR_FEATURES
from shared.seasonal_profile import seasonal_prior


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


def test_seasonal_prior_uses_the_frozen_profile_for_training_and_serving(tmp_path):
    timestamps = pd.date_range("2024-01-01", periods=100, freq="5min")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "entity_id": ["station-a"] * len(timestamps),
            # A deliberately sharp post-train shift makes leakage observable.
            "occupancy_ratio": [0.0] * 50 + [1.0] * 50,
            "split": ["train"] * 50 + ["val"] * 25 + ["test"] * 25,
            "interval_min": 5,
        }
    )
    input_path = tmp_path / "occupancy.parquet"
    output_path = tmp_path / "features.parquet"
    frame.to_parquet(input_path, index=False)

    metadata = build_feature_dataset(input_path, output_path, profile_name="seasonal")
    result = pd.read_parquet(output_path)
    profile = json.loads(Path(str(metadata["seasonal_profile_path"])).read_text(encoding="utf-8"))

    assert set(SEASONAL_PRIOR_FEATURES).issubset(result.columns)
    assert metadata["horizons_min"] == list(HORIZONS_MIN)
    # The profile excludes validation/test labels and is used unchanged by every split.
    first_val = result.loc[result["split"] == "val"].sort_values("timestamp").iloc[0]
    assert first_val["seasonal_prior_t_plus_5m"] == 0.0
    assert profile["station_means"]["station-a"]["mean"] == 0.0
    for _, row in result.iterrows():
        for horizon, column in zip(HORIZONS_MIN, SEASONAL_PRIOR_FEATURES, strict=True):
            expected = seasonal_prior(
                profile,
                row["entity_id"],
                row["timestamp"].to_pydatetime(),
                horizon,
            )
            assert row[column] == expected


def test_seasonal_feature_matches_shared_formula_when_a_bucket_is_observed(tmp_path):
    timestamps = pd.date_range("2024-01-01", periods=700, freq="5min")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "entity_id": ["station-a"] * len(timestamps),
            "occupancy_ratio": [(index % 288) / 287 for index in range(len(timestamps))],
            "split": ["train"] * 500 + ["val"] * 100 + ["test"] * 100,
            "interval_min": 5,
        }
    )
    input_path = tmp_path / "occupancy.parquet"
    output_path = tmp_path / "features.parquet"
    frame.to_parquet(input_path, index=False)

    metadata = build_feature_dataset(input_path, output_path, profile_name="seasonal")
    result = pd.read_parquet(output_path)
    profile = json.loads(Path(str(metadata["seasonal_profile_path"])).read_text(encoding="utf-8"))
    row = result.iloc[0]

    expected = seasonal_prior(
        profile,
        row["entity_id"],
        row["timestamp"].to_pydatetime(),
        5,
    )
    assert row["seasonal_prior_t_plus_5m"] == expected
    assert expected != profile["station_means"]["station-a"]["mean"]
