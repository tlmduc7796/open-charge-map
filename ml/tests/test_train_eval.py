from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ml import build_dataset as bd
from ml import features as ft
from ml import train_eval as te

pytest.importorskip("xgboost")


def test_error_metrics_and_gain():
    metrics = te.error_metrics(np.array([0.0, 1.0]), np.array([0.5, 0.5]))
    assert metrics["mae"] == pytest.approx(0.5)
    assert metrics["rmse"] == pytest.approx(0.5)
    assert te.gain_pct(0.1, 0.08) == pytest.approx(20.0)
    assert te.gain_pct(0.0, 0.1) is None


def test_evaluate_split_groups_and_persistence():
    frame = pd.DataFrame(
        {
            "total_ports": [4, 4, 20, 20],
            "lag_1": [0.0, 1.0, 0.5, 0.5],
            "y1": [0.0, 1.0, 0.7, 0.3],
        }
    )
    prediction = np.array([0.0, 1.0, 0.5, 0.5])
    result = te.evaluate_split(frame, prediction, "y1", small_ports=4)
    assert result["all"]["n"] == 4
    assert result["small"]["n"] == 2 and result["large"]["n"] == 2
    # nhóm small: persistence đã hoàn hảo (MAE = 0) nên không tính được % cải thiện
    assert result["small"]["persistence"]["mae"] == 0.0
    assert result["small"]["mae_gain_pct"] is None
    # nhóm large: model trùng persistence nên cải thiện bằng 0
    assert result["large"]["persistence"]["mae"] == pytest.approx(0.2)
    assert result["large"]["mae_gain_pct"] == pytest.approx(0.0, abs=1e-9)


def test_train_eval_smoke(tmp_path, random_raw):
    csv_path = tmp_path / "occupancy.csv"
    random_raw.to_csv(csv_path, index=False)
    data_dir = tmp_path / "out"
    bd.main(
        [
            "--input", str(csv_path),
            "--out-dir", str(data_dir),
            "--warmup-hours", "0",
            "--val-start", "2026-09-13",
            "--test-start", "2026-09-15",
        ]
    )

    model_dir = tmp_path / "model"
    out_dir = tmp_path / "results"
    code = te.main(
        [
            "--data-dir", str(data_dir),
            "--model-dir", str(model_dir),
            "--out-dir", str(out_dir),
            "--n-estimators", "8",
            "--early-stopping-rounds", "3",
            "--max-depth", "3",
        ]
    )
    assert code == 0

    for horizon in ft.HORIZONS_MIN:
        assert (model_dir / f"model_h{horizon}.json").is_file()
        # model nằm riêng, không lẫn vào thư mục dữ liệu hay kết quả
        assert not (data_dir / f"model_h{horizon}.json").exists()
        assert not (out_dir / f"model_h{horizon}.json").exists()
    report = json.loads((out_dir / "metrics.json").read_text(encoding="utf-8"))
    assert report["serving_ready"] is False
    assert set(report["horizons"]) == {str(h) for h in ft.HORIZONS_MIN}
    cell = report["horizons"]["5"]["test"]["all"]
    assert cell["n"] > 0
    assert cell["model"]["mae"] >= 0 and cell["persistence"]["rmse"] >= 0

    importance = pd.read_csv(out_dir / "feature_importance.csv")
    assert len(importance) == ft.N_HORIZONS * 26
    assert set(importance["horizon_min"]) == set(ft.HORIZONS_MIN)
