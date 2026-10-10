from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.domain.model_artifact import OccupancyModelMetadata


def _metadata() -> dict:
    return {
        "model_name": "smart_ev_occupancy",
        "model_version": "occupancy-xgb-1",
        "task": "occupancy_forecasting",
        "training_dataset": "UrbanEV Phase 03 temporal split",
        "training_level": "station",
        "feature_order": ["lag_1", "lag_2", "hour_sin", "hour_cos"],
        "lookback_steps": 12,
        "temporal_resolution_min": 5,
        "supported_horizons_min": [5, 10, 15],
        "target": "occupancy_ratio",
        "metrics_by_horizon": {
            "5": {"mae": 0.08, "rmse": 0.11},
            "10": {"mae": 0.1, "rmse": 0.14},
            "15": {"mae": 0.12, "rmse": 0.16},
        },
        "persistence_metrics_by_horizon": {
            "5": {"mae": 0.1, "rmse": 0.13},
            "10": {"mae": 0.12, "rmse": 0.16},
            "15": {"mae": 0.14, "rmse": 0.18},
        },
        "serving_decision": "model",
        "random_seed": 42,
        "model_artifact": {"path": "occupancy_model.joblib", "sha256": "a" * 64},
        "preprocessor_artifact": {
            "path": "occupancy_preprocessor.joblib", "sha256": "b" * 64
        },
        "limitations": ["Demo integration pending"],
    }


def test_model_metadata_handoff_contract_validates() -> None:
    metadata = OccupancyModelMetadata.model_validate(_metadata())

    assert metadata.lookback_steps == 12
    assert metadata.supported_horizons_min == (5, 10, 15)


def test_model_metadata_rejects_missing_horizon_metrics() -> None:
    payload = _metadata()
    del payload["metrics_by_horizon"]["15"]

    with pytest.raises(ValidationError, match="metrics must cover"):
        OccupancyModelMetadata.model_validate(payload)


def test_model_metadata_rejects_serving_model_below_baseline_threshold() -> None:
    payload = _metadata()
    payload["metrics_by_horizon"]["5"]["mae"] = 0.096

    with pytest.raises(ValidationError, match="improve persistence MAE"):
        OccupancyModelMetadata.model_validate(payload)
