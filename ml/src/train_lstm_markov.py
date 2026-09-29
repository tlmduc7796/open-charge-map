#!/usr/bin/env python3
"""Train the Phase 2 LSTM + Markov transition-head experiment.

Nothing trains unless ``--execute`` is supplied.  The produced PyTorch release
is experimental: it is intentionally not accepted by the current FastAPI
serving adapter until real Vietnamese data and calibration gates are approved.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]


def build_sequences(
    frame: pd.DataFrame,
    *,
    split: str,
    lookback_steps: int = 12,
    forecast_steps: int = 6,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build leakage-safe full/available-state trajectories for one split."""
    required = {"timestamp", "entity_id", "occupied_ports", "total_ports", "split"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Processed occupancy dataset misses: {sorted(missing)}")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    states: list[np.ndarray] = []
    contexts: list[np.ndarray] = []
    current_states: list[float] = []
    future_states: list[np.ndarray] = []
    for _, station in frame.groupby("entity_id", sort=False):
        station = station.sort_values("timestamp").reset_index(drop=True)
        full = (station["occupied_ports"] >= station["total_ports"]).astype(np.float32).to_numpy()
        for index in range(lookback_steps - 1, len(station) - forecast_steps):
            # All inputs and all labels must belong to the requested split. The
            # initial validation/test context may still look back to earlier
            # observations, but its labels never cross a later split boundary.
            window_splits = station["split"].iloc[index + 1 : index + forecast_steps + 1]
            if station["split"].iloc[index] != split or not (window_splits == split).all():
                continue
            timestamp = station["timestamp"].iloc[index]
            hour = timestamp.hour + timestamp.minute / 60
            dow = timestamp.dayofweek
            states.append(full[index - lookback_steps + 1 : index + 1])
            contexts.append(
                np.asarray(
                    [
                        np.sin(2 * np.pi * hour / 24),
                        np.cos(2 * np.pi * hour / 24),
                        np.sin(2 * np.pi * dow / 7),
                        np.cos(2 * np.pi * dow / 7),
                        float(dow >= 5),
                    ],
                    dtype=np.float32,
                )
            )
            current_states.append(full[index])
            future_states.append(full[index + 1 : index + forecast_steps + 1])
    if not states:
        raise ValueError(f"No valid {split} LSTM-Markov sequences were built")
    return (
        np.stack(states),
        np.stack(contexts),
        np.asarray(current_states, dtype=np.float32),
        np.stack(future_states),
    )


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

    torch.manual_seed(seed)
    frame = pd.read_parquet(dataset_path)
    train_parts = build_sequences(frame, split="train")
    val_parts = build_sequences(frame, split="val")

    class LSTMMarkovNet(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(input_size=1, hidden_size=32, batch_first=True)
            self.context = nn.Sequential(nn.Linear(5, 16), nn.ReLU())
            self.head = nn.Sequential(
                nn.Linear(48, 32), nn.ReLU(), nn.Dropout(0.2), nn.Linear(32, 12)
            )

        def forward(self, sequence, context):
            _, (hidden, _) = self.lstm(sequence.unsqueeze(-1))
            joined = torch.cat((hidden[-1], self.context(context)), dim=1)
            logits = self.head(joined).reshape(-1, 2, 6)
            return logits[:, 0, :], logits[:, 1, :]

    def markov_loss(release_logits, occupy_logits, current_state, future_state):
        previous_state = torch.cat((current_state.unsqueeze(1), future_state[:, :-1]), dim=1)
        release_mask = previous_state == 1
        occupy_mask = previous_state == 0
        loss = torch.zeros((), device=release_logits.device)
        if release_mask.any():
            loss = loss + functional.binary_cross_entropy_with_logits(
                release_logits[release_mask], 1 - future_state[release_mask]
            )
        if occupy_mask.any():
            loss = loss + functional.binary_cross_entropy_with_logits(
                occupy_logits[occupy_mask], future_state[occupy_mask]
            )
        return loss

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = LSTMMarkovNet().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    train_loader = DataLoader(
        TensorDataset(*(torch.from_numpy(part) for part in train_parts)),
        batch_size=batch_size,
        shuffle=True,
    )
    val_tensors = tuple(torch.from_numpy(part).to(device) for part in val_parts)
    history: list[dict[str, float]] = []
    for epoch in range(1, epochs + 1):
        model.train()
        losses: list[float] = []
        for sequence, context, current, future in train_loader:
            optimizer.zero_grad()
            release_logits, occupy_logits = model(sequence.to(device), context.to(device))
            loss = markov_loss(release_logits, occupy_logits, current.to(device), future.to(device))
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        model.eval()
        with torch.no_grad():
            val_release, val_occupy = model(val_tensors[0], val_tensors[1])
            val_loss = markov_loss(val_release, val_occupy, val_tensors[2], val_tensors[3])
        history.append(
            {
                "epoch": epoch,
                "train_loss": float(np.mean(losses)),
                "val_loss": float(val_loss.cpu()),
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "lstm_markov_experiment.pt"
    metadata_path = output_dir / "lstm_markov_experiment_meta.json"
    torch.save(model.state_dict(), model_path)
    metadata = {
        "created_at": datetime.now(UTC).isoformat(),
        "status": "experimental_not_serving_ready",
        "dataset": str(dataset_path),
        "state_target": "is_full = occupied_ports >= total_ports",
        "lookback_steps": 12,
        "forecast_steps": 6,
        "interval_min": 5,
        "context_features": ["hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend"],
        "history": history,
        "device": str(device),
        "limitations": [
            "UrbanEV is not Vietnamese production data.",
            "No calibration, life-table baseline, or serving adapter is approved yet.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"model": str(model_path), "metadata": str(metadata_path), "final": history[-1]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT_DIR / "ml/artifacts/urbanev_processed.parquet"
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT_DIR / "ml/artifacts")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "will_train": False,
                    "profile": "LSTM + Markov head",
                    "next_step": "Review data gates, then add --execute.",
                },
                indent=2,
            )
        )
        return
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
