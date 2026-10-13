from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ml.station_demand.data import BASE_FEATURE_COLUMNS, generate_synthetic_dataset
from ml.station_demand.inference import load_model, predict_demand_payload
from ml.station_demand.train import train_model


class _FixedModel:
    def predict(self, frame) -> np.ndarray:
        return np.asarray([18.5], dtype=float)


def test_inference_emits_the_shared_m2a_m2b_payload() -> None:
    card = {
        "target": "charging_sessions",
        "unit": "sessions_per_day",
        "model_version": "demand-xgb-v0.1-test",
        "is_synthetic": True,
    }
    features = {name: 1.0 for name in BASE_FEATURE_COLUMNS}
    payload = predict_demand_payload(
        _FixedModel(),
        card,
        subject_id="candidate-7",
        subject_type="candidate",
        features=features,
        time_window={"start": "2027-01-01T00:00:00+07:00", "end": "2027-01-02T00:00:00+07:00"},
        data_snapshot_id="snapshot-v4",
        scenario="base",
    )
    assert payload["candidate_id"] == "candidate-7"
    assert payload["target"] == "charging_sessions"
    assert payload["value"] == 18.5
    assert payload["unit"] == "sessions_per_day"
    assert payload["status"] == "synthetic"
    assert payload["model_version"] == "demand-xgb-v0.1-test"
    assert payload["data_snapshot_id"] == "snapshot-v4"
    assert "uncertainty" not in payload


@pytest.mark.parametrize(
    ("target", "unit"),
    (
        ("charging_sessions", "sessions_per_day"),
        ("charging_energy", "kwh_per_day"),
    ),
)
def test_training_smoke_writes_model_card_and_both_holdout_metrics(
    tmp_path: Path, target: str, unit: str
) -> None:
    pytest.importorskip("xgboost")
    frame = generate_synthetic_dataset(seed=8, spatial_units=24, days=180, target=target)
    report = train_model(
        frame,
        target=target,
        output_dir=tmp_path,
        validation_start="2025-03-15T00:00:00+07:00",
        test_start="2025-05-15T00:00:00+07:00",
        seed=8,
        n_estimators=20,
        early_stopping_rounds=5,
        allow_synthetic=True,
    )
    assert report["is_synthetic"] is True
    assert report["serving_ready"] is False
    assert report["metrics"]["temporal_test"]["n"] > 0
    assert report["metrics"]["spatial_test"]["n"] > 0
    assert (tmp_path / "demand_model.json").is_file()
    assert (tmp_path / "feature_importance.csv").is_file()
    card = json.loads((tmp_path / "model_card.json").read_text(encoding="utf-8"))
    assert card["model_version"] == report["model_version"]
    assert card["split_protocol"]["test_used_for_tuning"] is False

    model, loaded_card = load_model(tmp_path)
    row = frame.iloc[0]
    payload = predict_demand_payload(
        model,
        loaded_card,
        subject_id=str(row["spatial_unit_id"]),
        subject_type="demand_cell",
        features={name: row[name] for name in BASE_FEATURE_COLUMNS},
        time_window={
            "start": str(row["time_window_start"]),
            "end": str(row["time_window_end"]),
        },
        data_snapshot_id=str(row["data_snapshot_id"]),
        scenario="synthetic-demo",
    )
    assert payload["demand_cell_id"] == row["spatial_unit_id"]
    assert payload["status"] == "synthetic"
    assert payload["model_version"] == report["model_version"]
    assert payload["target"] == target
    assert payload["unit"] == unit
