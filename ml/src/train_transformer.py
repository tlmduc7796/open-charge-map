#!/usr/bin/env python3
"""Generic multi-horizon Transformer experiment controlled by the domain schema.

The architecture is present for review; execution is blocked until the team
approves the transformer profile and builds an enriched dataset matching it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .domain_schema import DEFAULT_SCHEMA_PATH, load_domain_schema
    from .feature_contract import HORIZONS_MIN
except ImportError:  # pragma: no cover - direct script invocation.
    from domain_schema import DEFAULT_SCHEMA_PATH, load_domain_schema
    from feature_contract import HORIZONS_MIN

ROOT_DIR = Path(__file__).resolve().parents[2]
HORIZONS = HORIZONS_MIN


def build_transformer_samples(
    frame: pd.DataFrame,
    *,
    sequence_features: tuple[str, ...],
    context_features: tuple[str, ...],
    target: str,
    lookback_steps: int = 12,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Create numeric, no-leakage samples after the enriched schema is approved."""
    required = {"timestamp", "entity_id", "split", target, *sequence_features, *context_features}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Enriched dataset misses approved columns: {sorted(missing)}")
    selected_columns = list((*sequence_features, *context_features, target))
    if frame[selected_columns].select_dtypes(exclude="number").shape[1]:
        raise ValueError("Transformer adapter currently requires encoded numeric features")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    sequences: list[np.ndarray] = []
    contexts: list[np.ndarray] = []
    targets: list[np.ndarray] = []
    split_rows: list[str] = []
    for _, station in frame.groupby("entity_id", sort=False):
        station = station.sort_values("timestamp").reset_index(drop=True)
        for index in range(lookback_steps - 1, len(station) - max(HORIZONS) // 5):
            horizon_rows = [index + horizon // 5 for horizon in HORIZONS]
            current_split = station["split"].iloc[index]
            if not all(station["split"].iloc[row] == current_split for row in horizon_rows):
                continue
            sequences.append(
                station.loc[index - lookback_steps + 1 : index, list(sequence_features)].to_numpy()
            )
            contexts.append(station.loc[index, list(context_features)].to_numpy(dtype=float))
            targets.append(station.loc[horizon_rows, target].to_numpy(dtype=float))
            split_rows.append(current_split)
    if not sequences:
        raise ValueError("No valid Transformer samples after temporal-boundary filtering")
    return (
        np.stack(sequences).astype(np.float32),
        np.stack(contexts).astype(np.float32),
        np.stack(targets).astype(np.float32),
        np.asarray(split_rows),
    )


def execute_training(dataset_path: Path, schema_path: Path, output_dir: Path) -> dict[str, object]:
    schema = load_domain_schema(schema_path)
    profile = schema.profile("transformer")
    if not profile.enabled:
        raise ValueError(
            "Transformer profile is disabled; complete DATA_HANDOFF.md before enabling it"
        )
    try:
        import torch
        from torch import nn
    except ImportError as exc:
        raise RuntimeError(
            "Install ml/requirements-deep-learning.txt in a GPU environment"
        ) from exc

    frame = pd.read_parquet(dataset_path)
    sequence, context, target, split = build_transformer_samples(
        frame,
        sequence_features=profile.sequence_features,
        context_features=profile.context_features,
        target=schema.target_name,
    )

    # The code below is intentionally small and inspectable; hyperparameter
    # tuning, graph topology and categorical embeddings are data-review tasks.
    class MultiDomainTransformer(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            width = 64
            self.sequence_projection = nn.Linear(sequence.shape[2], width)
            layer = nn.TransformerEncoderLayer(d_model=width, nhead=4, batch_first=True)
            self.encoder = nn.TransformerEncoder(layer, num_layers=2)
            self.context_projection = nn.Linear(context.shape[1], width)
            self.output = nn.Linear(width * 2, len(HORIZONS))

        def forward(self, sequence_tensor, context_tensor):
            encoded = self.encoder(self.sequence_projection(sequence_tensor))[:, -1]
            return self.output(torch.cat((encoded, self.context_projection(context_tensor)), dim=1))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MultiDomainTransformer().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    train = split == "train"
    for _ in range(20):
        optimizer.zero_grad()
        prediction = model(
            torch.from_numpy(sequence[train]).to(device),
            torch.from_numpy(context[train]).to(device),
        )
        loss = nn.functional.mse_loss(prediction, torch.from_numpy(target[train]).to(device))
        loss.backward()
        optimizer.step()
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "transformer_experiment.pt"
    torch.save(model.state_dict(), model_path)
    return {
        "model": str(model_path),
        "status": "experimental_not_serving_ready",
        "device": str(device),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA_PATH)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT_DIR / "ml/data/features/enriched_training.parquet"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT_DIR / "ml/results/foundation/candidates",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    schema = load_domain_schema(args.schema)
    plan = schema.training_requirements("transformer")
    if not args.execute:
        print(json.dumps({"will_train": False, **plan}, indent=2))
        return
    print(json.dumps(execute_training(args.dataset, args.schema, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
