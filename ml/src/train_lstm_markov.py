#!/usr/bin/env python3
"""Train the Phase 05A hybrid LSTM occupancy-ratio experiment.

Nothing trains unless ``--execute`` is supplied. The produced PyTorch release
is experimental: it is intentionally not accepted by the current FastAPI
serving adapter until real Vietnamese data and calibration gates are approved.
Markov transition training is a separate Phase 05B contract.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .domain_schema import DEFAULT_SCHEMA_PATH, load_domain_schema
    from .feature_contract import (
        CONTRACT_VERSION,
        HORIZONS_MIN,
        LAG_FEATURES,
        SEASONAL_PRIOR_FEATURES,
        get_feature_profile,
        target_column,
    )
except ImportError:  # pragma: no cover - direct script invocation.
    from domain_schema import DEFAULT_SCHEMA_PATH, load_domain_schema
    from feature_contract import (
        CONTRACT_VERSION,
        HORIZONS_MIN,
        LAG_FEATURES,
        SEASONAL_PRIOR_FEATURES,
        get_feature_profile,
        target_column,
    )

ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_seasonal_metadata(dataset_path: Path) -> dict[str, object]:
    """Require the same frozen seasonal contract as the XGBoost trainer."""
    metadata_path = dataset_path.with_suffix(".meta.json")
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Feature metadata not found: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    profile = get_feature_profile("seasonal")
    if metadata.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("Feature dataset contract version is incompatible with hybrid LSTM")
    if metadata.get("profile") != "seasonal":
        raise ValueError("Hybrid LSTM requires the seasonal feature dataset")
    if metadata.get("feature_names") != list(profile.feature_names):
        raise ValueError("Hybrid LSTM feature names do not match the seasonal contract")
    if not metadata.get("seasonal_profile_path"):
        raise ValueError("Hybrid LSTM feature dataset has no frozen seasonal profile")
    return metadata


def build_sequences(
    frame: pd.DataFrame,
    *,
    split: str,
    lookback_steps: int = 12,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build 12-lag inputs and target-time calendar/profile branch.

    The feature dataset already removes any row whose +5..+60 labels cross a
    temporal split.  This adapter therefore never creates a target from the
    future by slicing the raw station series itself.
    """
    required = {
        "timestamp",
        "entity_id",
        "split",
        *LAG_FEATURES,
        *SEASONAL_PRIOR_FEATURES,
        *(target_column(horizon) for horizon in HORIZONS_MIN),
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Processed occupancy dataset misses: {sorted(missing)}")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    selected = frame.loc[frame["split"] == split].copy()
    if selected.empty:
        raise ValueError(f"No valid {split} hybrid LSTM rows were built")
    states: list[np.ndarray] = []
    contexts: list[np.ndarray] = []
    future_states: list[np.ndarray] = []
    for _, row in selected.iterrows():
        # lag_12 is oldest and lag_1 newest, which is the chronological order
        # expected by the recurrent encoder.
        states.append(row.loc[list(reversed(LAG_FEATURES))].to_numpy(dtype=np.float32))
        branch: list[float] = []
        for horizon, seasonal_name in zip(HORIZONS_MIN, SEASONAL_PRIOR_FEATURES, strict=True):
            target_at = row["timestamp"] + pd.Timedelta(minutes=horizon)
            hour = target_at.hour + target_at.minute / 60
            dow = target_at.dayofweek
            branch.extend(
                [
                    np.sin(2 * np.pi * hour / 24),
                    np.cos(2 * np.pi * hour / 24),
                    np.sin(2 * np.pi * dow / 7),
                    np.cos(2 * np.pi * dow / 7),
                    float(dow >= 5),
                    float(row[seasonal_name]),
                ]
            )
        contexts.append(np.asarray(branch, dtype=np.float32))
        future_states.append(
            row.loc[[target_column(horizon) for horizon in HORIZONS_MIN]].to_numpy(dtype=np.float32)
        )
    return (
        np.stack(states),
        np.stack(contexts),
        np.stack(future_states),
    )


def _regression_metrics(model, tensors) -> dict[str, object]:
    """Return source-domain test metrics for the same horizons as XGBoost."""
    import torch

    model.eval()
    with torch.no_grad():
        prediction = model(tensors[0], tensors[1]).detach().cpu().numpy()
    observed = tensors[2].detach().cpu().numpy()
    error = prediction - observed
    per_horizon = {
        str(horizon): {
            "mae": round(float(np.mean(np.abs(error[:, index]))), 6),
            "rmse": round(float(np.sqrt(np.mean(np.square(error[:, index])))), 6),
        }
        for index, horizon in enumerate(HORIZONS_MIN)
    }
    return {
        "mae": round(float(np.mean(np.abs(error))), 6),
        "rmse": round(float(np.sqrt(np.mean(np.square(error)))), 6),
        "per_horizon": per_horizon,
    }


def run_training(
    dataset_path: Path,
    output_dir: Path,
    *,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    seed: int,
) -> dict[str, object]:
    try:
        import torch
        from torch import nn
        from torch.nn import functional as functional
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError as exc:
        raise RuntimeError(
            "Install ml/requirements-deep-learning.txt in Colab, Kaggle, or a GPU environment"
        ) from exc

    _load_seasonal_metadata(dataset_path)
    torch.manual_seed(seed)
    frame = pd.read_parquet(dataset_path)
    train_parts = build_sequences(frame, split="train")
    val_parts = build_sequences(frame, split="val")
    test_parts = build_sequences(frame, split="test")

    class HybridLSTMNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=32, batch_first=True)
            self.context = nn.Sequential(nn.Linear(6 * len(HORIZONS_MIN), 32), nn.ReLU())
            self.head = nn.Sequential(
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(32, len(HORIZONS_MIN)),
                nn.Sigmoid(),
            )

        def forward(self, sequence, context):
            _, (hidden, _) = self.lstm(sequence.unsqueeze(-1))
            joined = torch.cat((hidden[-1], self.context(context)), dim=1)
            return self.head(joined)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = HybridLSTMNet().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    train_loader = DataLoader(
        TensorDataset(*(torch.from_numpy(part) for part in train_parts)),
        batch_size=batch_size,
        shuffle=True,
    )
    val_tensors = tuple(torch.from_numpy(part).to(device) for part in val_parts)
    test_tensors = tuple(torch.from_numpy(part).to(device) for part in test_parts)
    history: list[dict[str, float]] = []
    for epoch in range(1, epochs + 1):
        model.train()
        losses: list[float] = []
        for sequence, context, future in train_loader:
            optimizer.zero_grad()
            prediction = model(sequence.to(device), context.to(device))
            loss = functional.smooth_l1_loss(prediction, future.to(device))
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        model.eval()
        with torch.no_grad():
            val_prediction = model(val_tensors[0], val_tensors[1])
            val_loss = functional.smooth_l1_loss(val_prediction, val_tensors[2])
        history.append(
            {
                "epoch": epoch,
                "train_loss": float(np.mean(losses)),
                "val_loss": float(val_loss.cpu()),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "hybrid_lstm_experiment.pt"
    metadata_path = output_dir / "hybrid_lstm_experiment_meta.json"
    torch.save(model.state_dict(), model_path)
    metadata = {
        "format_version": CONTRACT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "experimental_not_serving_ready",
        "phase": "05A_hybrid_lstm_occupancy",
        "dataset": str(dataset_path),
        "source_feature_metadata": str(dataset_path.with_suffix(".meta.json")),
        "profile": "seasonal",
        "target": "occupancy_ratio",
        "lookback_steps": 12,
        "forecast_steps": len(HORIZONS_MIN),
        "horizons_min": list(HORIZONS_MIN),
        "interval_min": 5,
        "context_features": [
            "target hour/day calendar features and seasonal prior for each horizon"
        ],
        "loss": "SmoothL1 regression loss on bounded occupancy_ratio",
        "history": history,
        "test_metrics": _regression_metrics(model, test_tensors),
        "device": str(device),
        "markov_status": (
            "not_trained; Phase 05B must train and calibrate transition probabilities separately"
        ),
        "limitations": [
            "UrbanEV is not Vietnamese production data.",
            "No calibration, seasonal-naive benchmark, or serving adapter is approved yet.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"model": str(model_path), "metadata": str(metadata_path), "final": history[-1]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT_DIR / "ml/data/features/occupancy_features_seasonal.parquet",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT_DIR / "ml/results/occupancy/research/lstm_markov",
    )
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    schema = load_domain_schema(args.schema)
    plan = schema.training_requirements("lstm_markov")
    if not args.execute:
        print(
            json.dumps(
                {
                    "will_train": False,
                    "profile": "Hybrid LSTM regression",
                    "next_step": "Review data gates, then add --execute.",
                    **plan,
                },
                indent=2,
            )
        )
        return
    if not schema.profile("lstm_markov").enabled:
        raise ValueError(
            "LSTM-Markov profile is disabled; complete DATA_HANDOFF.md before enabling it"
        )
    print(
        json.dumps(
            run_training(
                args.dataset,
                args.output_dir,
                epochs=args.epochs,
                batch_size=args.batch_size,
                learning_rate=args.learning_rate,
                seed=args.seed,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
