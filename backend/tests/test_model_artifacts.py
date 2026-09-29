"""Release-bundle validation tests for the optional ML serving adapter."""

from __future__ import annotations

import json

import joblib

from backend.app.domain.model_artifacts import JoblibOccupancyPredictor


class ConstantModel:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, rows):
        assert len(rows) == 1
        return [self.value]


def test_backend_loads_only_a_complete_baseline_release(tmp_path):
    feature_names = [f"lag_{step}" for step in range(1, 13)]
    model_path = tmp_path / "occupancy_model.joblib"
    preprocessor_path = tmp_path / "occupancy_preprocessor.joblib"
    meta_path = tmp_path / "occupancy_model_meta.json"
    joblib.dump(
        {
            "format_version": "1.0",
            "feature_names": feature_names,
            "models": {5: ConstantModel(0.2), 10: ConstantModel(0.3), 15: ConstantModel(0.4)},
        },
        model_path,
    )
    joblib.dump({"format_version": "1.0", "feature_names": feature_names}, preprocessor_path)
    meta_path.write_text(
        json.dumps(
            {
                "format_version": "1.0",
                "profile": "baseline",
                "feature_names": feature_names,
                "serving_ready": True,
            }
        ),
        encoding="utf-8",
    )

    predictor, metadata = JoblibOccupancyPredictor.from_files(
        model_path, preprocessor_path, meta_path
    )

    assert metadata["profile"] == "baseline"
    assert predictor.predict(tuple(range(12)), 10) == 0.3
