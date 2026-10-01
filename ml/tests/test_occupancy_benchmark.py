"""Tests for target-time daily/weekly baselines and residual gate selection."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.src.benchmark_occupancy import (
    DAILY_STEPS,
    WEEKLY_STEPS,
    apply_residual_gate,
    build_horizon_frame,
    choose_residual_gate,
)
from ml.src.feature_contract import target_column


def test_daily_and_weekly_naive_are_anchored_at_target_time():
    timestamps = pd.date_range("2024-01-01", periods=WEEKLY_STEPS + 20, freq="5min")
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "entity_id": "station-a",
            "occupancy_ratio": np.arange(len(timestamps), dtype=float),
            "split": "train",
            "interval_min": 5,
        }
    )

    result = build_horizon_frame(frame, 5)
    first = result.iloc[0]
    origin_index = WEEKLY_STEPS - 1  # weekly offset for +5 = 2015 rows

    assert first["timestamp"] == timestamps[origin_index]
    assert first[target_column(5)] == origin_index + 1
    assert first["daily_naive"] == origin_index - (DAILY_STEPS - 1)
    assert first["weekly_naive"] == origin_index - (WEEKLY_STEPS - 1)


def test_residual_gate_prefers_persistence_when_validation_is_tied():
    y_true = np.array([0.2, 0.8])
    persistence = np.array([0.2, 0.8])
    residual = np.array([0.4, -0.4])

    selected = choose_residual_gate(y_true, persistence, residual)

    assert selected["alpha"] == 0.0
    assert selected["validation_mae"] == 0.0


def test_residual_gate_applies_alpha_only_above_threshold():
    prediction = apply_residual_gate(
        np.array([0.4, 0.4]),
        np.array([0.1, 0.5]),
        alpha=0.5,
        threshold=0.2,
    )

    assert prediction.tolist() == [0.4, 0.65]
