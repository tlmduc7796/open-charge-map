"""Release-bundle validation tests for the optional ML serving adapter."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import pytest

from backend.app.domain.model_artifacts import (
    CONTRACT_VERSION,
    SUPPORTED_HORIZONS,
    ArtifactValidationError,
    JoblibOccupancyPredictor,
)


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


def _write_metadata_with_evaluation(
    metadata_path: Path,
    metadata: dict[str, Any],
    model_path: Path,
    preprocessor_path: Path,
) -> None:
    model_version = metadata.get("model_version") or metadata.get("release_id")
    report = {
        "evaluation_type": "independent_temporal_holdout",
        "holdout_status": "independent_untouched",
        "holdout_id": "TEST-HOLDOUT-1",
        "source_record": "TEST-REVIEW-1",
        "timezone": "Asia/Ho_Chi_Minh",
        "evaluation_start": "2026-10-01T01:00:00+00:00",
        "evaluation_end": "2026-10-02T01:00:00+00:00",
        "data_domain": "hcmc_operational",
        "dataset_sha256": "c" * 64,
        "holdout_manifest_sha256": "d" * 64,
        "model_version": model_version,
        "model_frozen_at": metadata["model_frozen_at"],
        "training_data_max_timestamp": metadata["training_data_max_timestamp"],
        "training_data_sha256s": metadata["training_data_sha256s"],
        "serving_contract_version": CONTRACT_VERSION,
        "quality_gate_passed": True,
        "evidence_gaps": [],
        "deployment_eligible": True,
        "promotion_performed": False,
        "required_relative_mae_gain": 0.05,
        "approved_calibration_policy": {
            "max_ece_10bin": 0.1,
            "min_slope": 0.5,
            "max_slope": 1.5,
            "max_abs_intercept": 0.2,
            "approved_by": "test reviewer",
            "approval_reference": "TEST-1",
        },
        "approved_sample_policy": {
            "minimum_stations": 1,
            "minimum_samples_per_horizon": 10,
            "approved_by": "test reviewer",
            "approval_reference": "TEST-1",
        },
        "per_horizon": {
            str(horizon): {
                "sample_count": 100,
                "station_count": 10,
                "relative_mae_gain": 0.06,
                "mae_gate_passed": True,
                "calibration_gate_passed": True,
                "sample_coverage_gate_passed": True,
                "candidate_calibration": {
                    "ece_10bin": 0.01,
                    "slope": 1.0,
                    "intercept": 0.0,
                },
            }
            for horizon in SUPPORTED_HORIZONS
        },
        "artifact_sha256s": {
            model_path.name: hashlib.sha256(model_path.read_bytes()).hexdigest(),
            preprocessor_path.name: hashlib.sha256(
                preprocessor_path.read_bytes()
            ).hexdigest(),
        },
    }
    report_path = metadata_path.with_name("occupancy_evaluation_report.json")
    report_bytes = (json.dumps(report, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(report_bytes)
    metadata["evaluation_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")


def test_backend_loads_only_a_complete_baseline_release(tmp_path):
    feature_names = [f"lag_{step}" for step in range(1, 13)]
    horizons = list(SUPPORTED_HORIZONS)
    features_by_horizon = {str(horizon): feature_names for horizon in horizons}
    model_path = tmp_path / "occupancy_model.joblib"
    preprocessor_path = tmp_path / "occupancy_preprocessor.joblib"
    meta_path = tmp_path / "occupancy_model_meta.json"
    joblib.dump(
        {
            "format_version": CONTRACT_VERSION,
            "feature_names_by_horizon": features_by_horizon,
            "models": {horizon: ConstantModel(horizon / 100) for horizon in horizons},
        },
        model_path,
    )
    joblib.dump(
        {"format_version": CONTRACT_VERSION, "feature_names_by_horizon": features_by_horizon},
        preprocessor_path,
    )
    metadata = {
        "format_version": CONTRACT_VERSION,
        "model_version": "occupancy-test-v1",
        "profile": "baseline",
        "feature_names": feature_names,
        "feature_names_by_horizon": features_by_horizon,
        "horizons_min": horizons,
        "serving_ready": True,
        "model_frozen_at": "2026-09-30T00:00:00Z",
        "training_data_max_timestamp": "2026-09-29T23:55:00Z",
        "training_data_sha256s": ["a" * 64],
    }
    _write_metadata_with_evaluation(
        meta_path, metadata, model_path, preprocessor_path
    )

    predictor, metadata = JoblibOccupancyPredictor.from_files(
        model_path, preprocessor_path, meta_path
    )

    assert metadata["profile"] == "baseline"
    assert metadata["model_version"] == "occupancy-test-v1"
    assert predictor.predict(tuple(range(12)), 10) == 0.1

    report_path = meta_path.with_name("occupancy_evaluation_report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["holdout_manifest_sha256"] = "invalid"
    report_bytes = (json.dumps(report, sort_keys=True) + "\n").encode("utf-8")
    report_path.write_bytes(report_bytes)
    metadata["evaluation_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(
        ArtifactValidationError,
        match="holdout dataset or manifest provenance is invalid",
    ):
        JoblibOccupancyPredictor.from_files(model_path, preprocessor_path, meta_path)
    _write_metadata_with_evaluation(meta_path, metadata, model_path, preprocessor_path)

    meta_path.write_text("[]", encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="metadata must be a JSON object"):
        JoblibOccupancyPredictor.from_files(model_path, preprocessor_path, meta_path)
    _write_metadata_with_evaluation(meta_path, metadata, model_path, preprocessor_path)

    model_bytes = model_path.read_bytes()
    model_path.write_bytes(model_bytes + b"tampered")
    with pytest.raises(ArtifactValidationError, match="differs from the evaluated candidate"):
        JoblibOccupancyPredictor.from_files(model_path, preprocessor_path, meta_path)
    model_path.write_bytes(model_bytes)

    metadata.pop("evaluation_report_sha256")
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="no valid evaluation report hash"):
        JoblibOccupancyPredictor.from_files(model_path, preprocessor_path, meta_path)

    metadata.pop("model_version")
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ArtifactValidationError, match="model_version or release_id"):
        JoblibOccupancyPredictor.from_files(model_path, preprocessor_path, meta_path)

    metadata["release_id"] = "legacy-release-v1"
    _write_metadata_with_evaluation(meta_path, metadata, model_path, preprocessor_path)
    _, normalized_metadata = JoblibOccupancyPredictor.from_files(
        model_path, preprocessor_path, meta_path
    )
    assert normalized_metadata["model_version"] == "legacy-release-v1"

    metadata["model_version"] = "occupancy-test-v1"
    metadata.pop("release_id")
    metadata["horizons_min"] = list(range(5, 61, 5))
    _write_metadata_with_evaluation(meta_path, metadata, model_path, preprocessor_path)
    with pytest.raises(ArtifactValidationError, match=r"every \+5 to \+30"):
        JoblibOccupancyPredictor.from_files(model_path, preprocessor_path, meta_path)


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
