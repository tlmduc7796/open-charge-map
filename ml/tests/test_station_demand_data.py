from __future__ import annotations

import pandas as pd
import pytest

from ml.station_demand.data import (
    FEATURE_COLUMNS,
    generate_synthetic_dataset,
    make_temporal_spatial_splits,
    validate_training_table,
)


def test_synthetic_training_table_is_reproducible_and_contract_labeled() -> None:
    first = generate_synthetic_dataset(seed=9, spatial_units=16, days=100)
    second = generate_synthetic_dataset(seed=9, spatial_units=16, days=100)
    pd.testing.assert_frame_equal(first, second)
    assert set(first["status"]) == {"synthetic"}
    assert first["is_synthetic"].all()
    assert set(first["unit"]) == {"sessions_per_day"}
    assert set(FEATURE_COLUMNS).isdisjoint({"value", "target", "source_id", "spatial_group"})


def test_label_status_and_unit_validation_prevent_proxy_targets() -> None:
    frame = generate_synthetic_dataset(seed=4, spatial_units=16, days=100)
    with pytest.raises(ValueError, match="allow_synthetic"):
        validate_training_table(frame, target="charging_sessions")
    validated = validate_training_table(frame, target="charging_sessions", allow_synthetic=True)
    assert validated["value"].ge(0).all()

    frame.loc[frame.index[0], "status"] = "proxy"
    with pytest.raises(ValueError, match="cannot be demand labels"):
        validate_training_table(frame, target="charging_sessions", allow_synthetic=True)

    frame = generate_synthetic_dataset(seed=4, spatial_units=16, days=100)
    frame.loc[frame.index[0], "unit"] = "kwh_per_day"
    with pytest.raises(ValueError, match="exactly one target"):
        validate_training_table(frame, target="charging_sessions", allow_synthetic=True)


def test_observed_and_synthetic_labels_cannot_be_mixed() -> None:
    frame = generate_synthetic_dataset(seed=5, spatial_units=16, days=100)
    frame.loc[frame.index[0], "status"] = "observed"
    frame.loc[frame.index[0], "source_id"] = "observed-source-v1"
    frame.loc[frame.index[0], "is_synthetic"] = False
    with pytest.raises(ValueError, match="cannot be mixed"):
        validate_training_table(frame, target="charging_sessions", allow_synthetic=True)


def test_time_and_spatial_splits_hold_out_groups_and_boundary_windows() -> None:
    frame = validate_training_table(
        generate_synthetic_dataset(seed=11, spatial_units=32, days=180),
        target="charging_sessions",
        allow_synthetic=True,
    )
    splits = make_temporal_spatial_splits(
        frame,
        validation_start="2025-03-15T00:00:00+07:00",
        test_start="2025-05-15T00:00:00+07:00",
        seed=11,
    )
    train_groups = set(splits.train["spatial_group"])
    assert not train_groups.intersection(splits.spatial_holdout_groups)
    assert set(splits.spatial_test["spatial_group"]) == set(splits.spatial_holdout_groups)
    assert (splits.train["time_window_end"] <= pd.Timestamp("2025-03-15T00:00:00Z")).all()
    assert (splits.validation["time_window_start"] >= pd.Timestamp("2025-03-14T17:00:00Z")).all()
    assert (splits.temporal_test["time_window_start"] >= pd.Timestamp("2025-05-14T17:00:00Z")).all()


def test_bad_window_and_nonfinite_feature_are_rejected() -> None:
    frame = generate_synthetic_dataset(seed=3, spatial_units=16, days=100)
    frame.loc[frame.index[0], "time_window_end"] = "2024-12-31T00:00:00+07:00"
    with pytest.raises(ValueError, match="must be after"):
        validate_training_table(frame, target="charging_sessions", allow_synthetic=True)

    frame = generate_synthetic_dataset(seed=3, spatial_units=16, days=100)
    frame.loc[frame.index[0], "road_traffic_index"] = float("inf")
    with pytest.raises(ValueError, match="infinity"):
        validate_training_table(frame, target="charging_sessions", allow_synthetic=True)
