from __future__ import annotations

import json

import numpy as np
import pandas as pd

from ml.src import train_rdm_quantile
from ml.src.data_pipeline.rdm import RDM_LIVE_SAFE_FEATURE_COLUMNS, RDM_TARGET_COLUMN


class _ConstantQuantileModel:
    def fit(self, features, target):
        self.value = float(np.median(target))
        return self

    def predict(self, features):
        return np.full(len(features), self.value)


def test_rdm_trainer_does_not_access_test_without_explicit_opt_in(tmp_path, monkeypatch):
    rows = []
    for split, prefix, target in (("train", "a", 20.0), ("val", "b", 30.0), ("test", "c", 40.0)):
        for index in range(2):
            rows.append(
                {
                    "session_id": f"{prefix}-{index}",
                    "observed_at": "2024-01-01T00:00:00+00:00",
                    "split": split,
                    "session_elapsed_min": 10.0,
                    "energy_delivered_kwh": 3.0,
                    "current_power_kw": 20.0,
                    "station_id": "station-a",
                    "port_id": "port-a",
                    "connector_type": "CCS2",
                    RDM_TARGET_COLUMN: target,
                }
            )
    dataset = tmp_path / "rdm.parquet"
    artifact_dir = tmp_path / "artifact"
    pd.DataFrame(rows).to_parquet(dataset, index=False)
    monkeypatch.setattr(
        train_rdm_quantile, "_build_model", lambda quantile, seed: _ConstantQuantileModel()
    )

    result = train_rdm_quantile.train_rdm(dataset, artifact_dir)
    metadata = json.loads((artifact_dir / "rdm_quantile_meta.json").read_text(encoding="utf-8"))

    assert result["test_accessed"] is False
    assert metadata["test_status"] == "not_accessed"
    assert "test_metrics" not in metadata


def test_live_safe_rdm_profile_requires_and_records_live_features(tmp_path, monkeypatch):
    rows = []
    for split, prefix, target in (("train", "a", 20.0), ("val", "b", 30.0), ("test", "c", 40.0)):
        for index in range(2):
            rows.append(
                {
                    "session_id": f"{prefix}-{index}",
                    "observed_at": "2024-01-01T00:00:00+00:00",
                    "split": split,
                    "session_elapsed_min": 10.0,
                    "energy_delivered_kwh": 3.0,
                    "current_power_kw": 20.0,
                    "station_id": "station-a",
                    "port_id": "port-a",
                    "connector_type": "CCS2",
                    "port_max_power_kw": 50.0,
                    "observation_hour_local": 7,
                    "observation_weekday_local": 2,
                    "is_drawing_power": 1,
                    RDM_TARGET_COLUMN: target,
                }
            )
    dataset = tmp_path / "rdm_live_safe.parquet"
    artifact_dir = tmp_path / "artifact"
    pd.DataFrame(rows).to_parquet(dataset, index=False)
    monkeypatch.setattr(
        train_rdm_quantile,
        "_build_live_safe_model",
        lambda quantile, seed: _ConstantQuantileModel(),
    )

    result = train_rdm_quantile.train_rdm(
        dataset, artifact_dir, feature_profile="live_safe"
    )

    assert result["feature_profile"] == "live_safe"
    assert result["feature_columns"] == list(RDM_LIVE_SAFE_FEATURE_COLUMNS)
