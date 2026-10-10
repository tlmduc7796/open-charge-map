from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.benchmark_urbanev import (
    DAILY_STEPS,
    WEEKLY_STEPS,
    apply_residual_gate,
    build_horizon_frame,
    choose_residual_gate,
    relative_mae_gain,
    target_column,
)
from shared.occupancy_contract import SUPPORTED_HORIZONS_MIN


def test_benchmark_horizons_and_target_names_match_backend_contract() -> None:
    assert SUPPORTED_HORIZONS_MIN == (5, 10, 15, 20, 25, 30)
    assert [target_column(horizon) for horizon in SUPPORTED_HORIZONS_MIN] == [
        f"target_occupancy_t_plus_{horizon}m" for horizon in SUPPORTED_HORIZONS_MIN
    ]
    with pytest.raises(ValueError, match="Unsupported occupancy horizon"):
        target_column(60)


def test_daily_weekly_naive_are_anchored_at_target_time() -> None:
    timestamps = pd.date_range("2024-01-01", periods=WEEKLY_STEPS + 20, freq="5min")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "entity_id": "station-a",
            "occupancy_ratio": np.arange(len(timestamps), dtype=float) % 100 / 100,
            "split": "train",
            "interval_min": 5,
        }
    )

    result = build_horizon_frame(frame, 5)
    first = result.iloc[0]
    origin_index = WEEKLY_STEPS - 1

    assert first["timestamp"] == timestamps[origin_index]
    assert first[target_column(5)] == (origin_index + 1) % 100 / 100
    assert first["daily_naive"] == (origin_index - (DAILY_STEPS - 1)) % 100 / 100
    assert first["weekly_naive"] == 0


def test_residual_gate_prefers_persistence_on_validation_tie() -> None:
    selected = choose_residual_gate(
        np.array([0.2, 0.8]), np.array([0.2, 0.8]), np.array([0.4, -0.4])
    )

    assert selected["alpha"] == 0.0
    assert selected["validation_mae"] == 0.0


def test_residual_gate_applies_only_above_selected_threshold() -> None:
    prediction = apply_residual_gate(
        np.array([0.4, 0.4]), np.array([0.1, 0.5]), alpha=0.5, threshold=0.2
    )

    assert prediction.tolist() == [0.4, 0.65]


def test_test_mae_gain_is_relative_and_requires_positive_baseline() -> None:
    assert relative_mae_gain(0.2, 0.19) == pytest.approx(0.05)
    assert relative_mae_gain(0.2, 0.21) < 0
    with pytest.raises(ValueError, match="must be positive"):
        relative_mae_gain(0, 0)
