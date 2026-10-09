from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.domain.model_artifact import OccupancyModelMetadata


def _metadata() -> dict:
    return {
        "model_version": "occupancy-xgb-1",
        "training_data_source": "UrbanEV Phase 03 temporal split",
        "feature_order": ["lag_1", "lag_2", "hour_sin", "hour_cos"],
        "lookback_steps": 12,
        "resolution_min": 5,
        "supported_horizons_min": [5, 10, 15],
        "metrics_by_horizon": {
            "5": {"mae": 0.08, "rmse": 0.11},
            "10": {"mae": 0.1, "rmse": 0.14},
            "15": {"mae": 0.12, "rmse": 0.16},
        },
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
