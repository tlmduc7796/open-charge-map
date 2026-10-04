"""Release-bundle validation tests for the optional ML serving adapter."""

from __future__ import annotations

import json
from datetime import datetime

import joblib

from backend.app.domain.model_artifacts import JoblibOccupancyPredictor


class ConstantModel:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, rows):
        assert len(rows) == 1
        return [self.value]


class CapturingModel(ConstantModel):
    def predict(self, rows):
        self.rows = rows
        return super().predict(rows)


def test_backend_loads_only_a_complete_baseline_release(tmp_path):
    feature_names = [f"lag_{step}" for step in range(1, 13)]
    horizons = list(range(5, 61, 5))
    features_by_horizon = {str(horizon): feature_names for horizon in horizons}
    model_path = tmp_path / "occupancy_model.joblib"
    preprocessor_path = tmp_path / "occupancy_preprocessor.joblib"
    meta_path = tmp_path / "occupancy_model_meta.json"
    joblib.dump(
        {
            "format_version": "2.1",
            "feature_names_by_horizon": features_by_horizon,
            "models": {horizon: ConstantModel(horizon / 100) for horizon in horizons},
        },
        model_path,
    )
    joblib.dump(
        {"format_version": "2.1", "feature_names_by_horizon": features_by_horizon},
        preprocessor_path,
    )
    meta_path.write_text(
        json.dumps(
            {
                "format_version": "2.1",
                "profile": "baseline",
                "feature_names": feature_names,
                "feature_names_by_horizon": features_by_horizon,
                "horizons_min": horizons,
                "serving_ready": True,
            }
        ),
        encoding="utf-8",
    )

    predictor, metadata = JoblibOccupancyPredictor.from_files(
        model_path, preprocessor_path, meta_path
    )

    assert metadata["profile"] == "baseline"
    assert predictor.predict(tuple(range(12)), 10) == 0.1


def test_seasonal_predictor_looks_up_the_target_time_bucket():
    model = CapturingModel(0.4)
    feature_names = tuple([*(f"lag_{step}" for step in range(1, 13)), "seasonal_prior_t_plus_5m"])
    predictor = JoblibOccupancyPredictor(
        {5: model},
        {5: feature_names},
        {
            "default": 0.5,
            "smoothing": 8,
            "station_means": {"station-a": {"mean": 0.25, "count": 10}},
            "buckets": {"station-a|0|1": {"mean": 0.75, "count": 2}},
        },
    )

    prediction = predictor.predict(
        tuple(range(12)),
        5,
        station_id="station-a",
        forecast_at=datetime.fromisoformat("2024-01-01T00:00:00+00:00"),
    )

    assert prediction == 0.4
    assert model.rows[0][0] == 11  # lag_1 is the newest item in chronological history.
    assert model.rows[0][-1] == 0.35  # (0.75 * 2 + 0.25 * 8) / (2 + 8)


def test_residual_model_adds_its_prediction_to_the_latest_occupancy():
    predictor = JoblibOccupancyPredictor(
        {5: ConstantModel(0.1)},
        {5: tuple(f"lag_{step}" for step in range(1, 13))},
        prediction_mode="residual_to_persistence",
    )

    assert predictor.predict((0.1,) * 12, 5) == 0.2
