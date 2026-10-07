#!/usr/bin/env python3
"""Run one exploratory, leakage-safe Gold occupancy leaderboard.

This is a research/demo benchmark. It is intentionally separate from serving
artifacts and labels its test metrics exploratory because Gold test has been
inspected in earlier experiments.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

try:
    from .feature_contract import HORIZONS_MIN, LAG_FEATURES, target_column
except ImportError:  # pragma: no cover - direct CLI invocation.
    from feature_contract import HORIZONS_MIN, LAG_FEATURES, target_column

ROOT = Path(__file__).resolve().parents[2]
REPORT_HORIZONS = (5, 15, 30, 45, 60)
INTERVAL_MIN = 5


def _metric(y_true: pd.Series, prediction: np.ndarray, total_ports: pd.Series) -> dict[str, float]:
    actual = y_true.to_numpy(dtype=float)
    predicted = np.clip(np.asarray(prediction, dtype=float), 0.0, 1.0)
    actual_has_space = actual < 1.0
    predicted_has_space = predicted < 1.0
    return {
        "mae": round(float(mean_absolute_error(actual, predicted)), 6),
        "rmse": round(float(mean_squared_error(actual, predicted) ** 0.5), 6),
        "availability_accuracy": round(float((actual_has_space == predicted_has_space).mean()), 6),
        "mean_predicted_occupied_ports": round(
            float(np.mean(predicted * total_ports.to_numpy(dtype=float))), 4
        ),
    }


def _load_features(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    required = {"timestamp", "entity_id", "split", *LAG_FEATURES}
    required.update(target_column(horizon) for horizon in HORIZONS_MIN)
    if missing := required - set(frame):
        raise ValueError(f"Feature dataset misses columns: {sorted(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if set(frame["split"]) != {"train", "val", "test"}:
        raise ValueError("Feature dataset must have train, val and test splits")
    return frame


def _load_occupancy(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    required = {
        "timestamp",
        "entity_id",
        "occupancy_ratio",
        "occupied_ports",
        "total_ports",
        "split",
    }
    if missing := required - set(frame):
        raise ValueError(f"Occupancy dataset misses columns: {sorted(missing)}")
    frame = frame.loc[:, list(required)].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values(["entity_id", "timestamp"])
    if frame.duplicated(["entity_id", "timestamp"]).any():
        raise ValueError("Occupancy data has duplicate station snapshots")
    return frame


def _historical_baseline(
    rows: pd.DataFrame, occupancy: pd.DataFrame, horizon: int, period: pd.Timedelta
) -> np.ndarray:
    target_at = rows["timestamp"] + pd.Timedelta(minutes=horizon)
    lookup = occupancy.set_index(["entity_id", "timestamp"])["occupancy_ratio"]
    keys = pd.MultiIndex.from_arrays(
        [rows["entity_id"].astype(str), target_at - period], names=lookup.index.names
    )
    prediction = lookup.reindex(keys).to_numpy(dtype=float)
    if np.isnan(prediction).any():
        raise ValueError(
            "Historical baseline needs a contiguous history before every evaluated target"
        )
    return prediction


def _fit_markov(occupancy: pd.DataFrame) -> dict[str, tuple[np.ndarray, int]]:
    """Fit one smoothed five-minute occupancy-count transition matrix per station."""
    models: dict[str, tuple[np.ndarray, int]] = {}
    for station_id, group in occupancy.loc[occupancy["split"] == "train"].groupby("entity_id"):
        group = group.sort_values("timestamp")
        capacity = int(group["total_ports"].mode().iloc[0])
        transition = np.full((capacity + 1, capacity + 1), 0.1, dtype=float)
        states = group["occupied_ports"].to_numpy(dtype=int)
        stamps = group["timestamp"].to_numpy()
        for previous, current, before, after in zip(
            states[:-1], states[1:], stamps[:-1], stamps[1:], strict=True
        ):
            if pd.Timestamp(after) - pd.Timestamp(before) == pd.Timedelta(minutes=INTERVAL_MIN):
                transition[np.clip(previous, 0, capacity), np.clip(current, 0, capacity)] += 1
        models[str(station_id)] = (transition / transition.sum(axis=1, keepdims=True), capacity)
    return models


def _markov_predict(
    rows: pd.DataFrame,
    models: dict[str, tuple[np.ndarray, int]],
    horizon: int,
) -> np.ndarray:
    steps = horizon // INTERVAL_MIN + 1  # lag_1 is one observation before the origin timestamp.
    values: list[float] = []
    for row in rows.itertuples(index=False):
        transition, capacity = models[str(row.entity_id)]
        state = int(np.clip(round(float(row.lag_1) * capacity), 0, capacity))
        future = np.linalg.matrix_power(transition, steps)[state]
        values.append(float(np.dot(np.arange(capacity + 1), future) / capacity))
    return np.asarray(values)


def _fit_xgboost(train: pd.DataFrame, target: str):
    from xgboost import XGBRegressor

    if len(train) > 50_000:
        train = train.sample(n=50_000, random_state=42).sort_index()
    model = XGBRegressor(
        objective="reg:squarederror",
        n_estimators=220,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(train.loc[:, LAG_FEATURES], train[target])
    return model


def _train_lstm(train: pd.DataFrame, *, epochs: int = 4):
    """Train one small multi-horizon LSTM, deliberately bounded for local reproducibility."""
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError as exc:  # pragma: no cover - environment dependent.
        raise RuntimeError("Install torch to include LSTM in the benchmark") from exc

    class OccupancyLSTM(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=16, batch_first=True)
            self.head = nn.Sequential(nn.Linear(16, len(HORIZONS_MIN)), nn.Sigmoid())

        def forward(self, value):
            _, (hidden, _) = self.lstm(value)
            return self.head(hidden[-1])

    torch.manual_seed(42)
    torch.set_num_threads(4)
    if len(train) > 40_000:
        train = train.sample(n=40_000, random_state=42).sort_index()
    # lag_12 ... lag_1 restores chronological order for the recurrent model.
    input_values = train.loc[:, list(reversed(LAG_FEATURES))].to_numpy(dtype=np.float32)[..., None]
    target_values = train.loc[:, [target_column(item) for item in HORIZONS_MIN]].to_numpy(
        dtype=np.float32
    )
    loader = DataLoader(
        TensorDataset(torch.from_numpy(input_values), torch.from_numpy(target_values)),
        batch_size=1024,
        shuffle=True,
        generator=torch.Generator().manual_seed(42),
    )
    model = OccupancyLSTM()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.002)
    loss_fn = nn.L1Loss()
    model.train()
    for _ in range(epochs):
        for features, targets in loader:
            optimizer.zero_grad()
            loss_fn(model(features), targets).backward()
            optimizer.step()

    def predict(rows: pd.DataFrame) -> np.ndarray:
        values = rows.loc[:, list(reversed(LAG_FEATURES))].to_numpy(dtype=np.float32)[..., None]
        model.eval()
        with torch.no_grad():
            return model(torch.from_numpy(values)).numpy()

    return predict


def run(feature_path: Path, occupancy_path: Path, report_path: Path) -> dict[str, object]:
    features = _load_features(feature_path)
    occupancy = _load_occupancy(occupancy_path)
    train = features.loc[features["split"] == "train"]
    val = features.loc[features["split"] == "val"]
    test = features.loc[features["split"] == "test"]
    markov = _fit_markov(occupancy)
    lstm_predict = _train_lstm(train)
    capacity_by_station = occupancy.groupby("entity_id")["total_ports"].max()
    report: dict[str, object] = {
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "gold_synthetic_exploratory_not_for_serving",
        "test_status": "exploratory; this Gold test window was inspected before protocol freeze",
        "models": ["persistence", "daily", "weekly", "markov", "xgboost", "lstm"],
        "training_budget": {
            "xgboost_max_train_rows_per_horizon": 50_000,
            "lstm_max_train_rows": 40_000,
            "lstm_epochs": 4,
        },
        "horizons_min": list(REPORT_HORIZONS),
        "records": {"train": int(len(train)), "val": int(len(val)), "test": int(len(test))},
        "per_horizon": {},
    }
    for horizon in REPORT_HORIZONS:
        target = target_column(horizon)
        model = _fit_xgboost(train, target)
        horizon_report: dict[str, object] = {}
        lstm_index = HORIZONS_MIN.index(horizon)
        for label, rows in (("validation", val), ("test_exploratory", test)):
            total_ports = rows["entity_id"].map(capacity_by_station)
            predictions = {
                "persistence": rows["lag_1"].to_numpy(),
                "daily": _historical_baseline(rows, occupancy, horizon, pd.Timedelta(days=1)),
                "weekly": _historical_baseline(rows, occupancy, horizon, pd.Timedelta(days=7)),
                "markov": _markov_predict(rows, markov, horizon),
                "xgboost": model.predict(rows.loc[:, LAG_FEATURES]),
                "lstm": lstm_predict(rows)[:, lstm_index],
            }
            horizon_report[label] = {
                name: _metric(rows[target], prediction, total_ports)
                for name, prediction in predictions.items()
            }
        validation_mae = horizon_report["validation"]
        winner = min(validation_mae, key=lambda name: validation_mae[name]["mae"])
        horizon_report["validation_winner"] = winner
        report["per_horizon"][str(horizon)] = horizon_report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--features",
        type=Path,
        default=ROOT / "ml/data/gold/hcmc_ctgan_q1_2026/occupancy_features_baseline.parquet",
    )
    parser.add_argument(
        "--occupancy",
        type=Path,
        default=ROOT / "ml/data/gold/hcmc_ctgan_q1_2026/occupancy_5min.parquet",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "ml/results/occupancy/gold_model_benchmark/report.json",
    )
    args = parser.parse_args()
    outcome = run(args.features, args.occupancy, args.report)
    print(json.dumps({"report": str(args.report), "horizons": outcome["horizons_min"]}, indent=2))
