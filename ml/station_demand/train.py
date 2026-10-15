"""Train and evaluate an M2A candidate/cell demand model.

Run from the repository root with ``python -m ml.station_demand.train --synthetic-demo`` for a
clearly labeled pipeline demonstration, or pass an M1 training-table CSV/Parquet with observed
charging-session or energy labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ml.station_demand.data import (
    FEATURE_COLUMNS,
    TARGET_UNITS,
    feature_matrix,
    generate_synthetic_dataset,
    make_temporal_spatial_splits,
    validate_training_table,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "ml" / "artifacts" / "station_demand"


def _error_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = np.asarray(predicted, dtype=float) - np.asarray(actual, dtype=float)
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(np.square(error)))),
    }


def _evaluate(
    model_prediction: np.ndarray,
    baseline_prediction: np.ndarray,
    actual: np.ndarray,
) -> dict[str, Any]:
    model = _error_metrics(actual, model_prediction)
    baseline = _error_metrics(actual, baseline_prediction)
    return {
        "n": int(len(actual)),
        "model": model,
        "spatial_group_mean_baseline": baseline,
        "mae_reduction_percent": (
            100.0 * (baseline["mae"] - model["mae"]) / baseline["mae"]
            if baseline["mae"] > 0
            else None
        ),
        "rmse_reduction_percent": (
            100.0 * (baseline["rmse"] - model["rmse"]) / baseline["rmse"]
            if baseline["rmse"] > 0
            else None
        ),
    }


def _group_mean_baseline(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    means = train.groupby("spatial_group", observed=True)["value"].mean()
    fallback = float(train["value"].mean())
    return test["spatial_group"].map(means).fillna(fallback).to_numpy(dtype=float)


def _source_summary(frame: pd.DataFrame) -> list[dict[str, Any]]:
    grouped = frame.groupby(["source_id", "data_snapshot_id", "status"], observed=True).size()
    return [
        {
            "source_id": str(source),
            "data_snapshot_id": str(snapshot),
            "status": str(status),
            "rows": int(count),
        }
        for (source, snapshot, status), count in grouped.items()
    ]


def train_model(
    frame: pd.DataFrame,
    *,
    target: str,
    output_dir: Path,
    validation_start: str = "2025-06-01T00:00:00+07:00",
    test_start: str = "2025-08-01T00:00:00+07:00",
    seed: int = 42,
    n_estimators: int = 1000,
    early_stopping_rounds: int = 50,
    max_depth: int = 6,
    learning_rate: float = 0.05,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    """Validate, split, fit, evaluate, and write a model plus lineage card."""
    if n_estimators < 1 or early_stopping_rounds < 1 or max_depth < 1:
        raise ValueError("estimator count, early stopping rounds, and max_depth must be positive")
    if not 0 < learning_rate <= 1:
        raise ValueError("learning_rate must be in (0, 1]")
    validated = validate_training_table(frame, target=target, allow_synthetic=allow_synthetic)
    enriched = validated.copy()
    splits = make_temporal_spatial_splits(
        enriched,
        validation_start=validation_start,
        test_start=test_start,
        seed=seed,
    )
    train = splits.train
    validation = splits.validation
    if target == "charging_sessions":
        objective = "count:poisson"
        eval_metric = "mae"
    else:
        objective = "reg:squarederror"
        eval_metric = "mae"

    try:
        import xgboost as xgb
    except ImportError as exc:  # pragma: no cover - exercised on minimal installs
        raise RuntimeError("M2A training requires xgboost; install ml/requirements.txt") from exc

    train_matrix = xgb.DMatrix(
        feature_matrix(train),
        label=train["value"].to_numpy(dtype=np.float32),
        feature_names=list(FEATURE_COLUMNS),
    )
    validation_matrix = xgb.DMatrix(
        feature_matrix(validation),
        label=validation["value"].to_numpy(dtype=np.float32),
        feature_names=list(FEATURE_COLUMNS),
    )
    model = xgb.train(
        params={
            "objective": objective,
            "eval_metric": eval_metric,
            "tree_method": "hist",
            "max_depth": max_depth,
            "eta": learning_rate,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "seed": seed,
            "nthread": 2,
        },
        dtrain=train_matrix,
        num_boost_round=n_estimators,
        evals=[(validation_matrix, "validation")],
        early_stopping_rounds=early_stopping_rounds,
        verbose_eval=False,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "demand_model.json"
    model.save_model(model_path)

    split_frames = {
        "validation": splits.validation,
        "temporal_test": splits.temporal_test,
        "spatial_test": splits.spatial_test,
    }
    split_metrics: dict[str, Any] = {}
    for name, part in split_frames.items():
        x = feature_matrix(part)
        matrix = xgb.DMatrix(x, feature_names=list(FEATURE_COLUMNS))
        predicted = np.maximum(
            model.predict(matrix, iteration_range=(0, int(model.best_iteration) + 1)), 0.0
        )
        baseline = _group_mean_baseline(train, part)
        split_metrics[name] = _evaluate(
            predicted,
            baseline,
            part["value"].to_numpy(dtype=float),
        )

    source_rows = _source_summary(validated)
    model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    model_version = f"demand-xgb-v0.1-{model_hash[:12]}"
    synthetic = bool(validated["is_synthetic"].any())
    report: dict[str, Any] = {
        "pipeline_version": "m2a-demand-0.1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "model_version": model_version,
        "target": target,
        "unit": TARGET_UNITS[target],
        "model_file": model_path.name,
        "model_sha256": model_hash,
        "model_family": "xgboost_gradient_boosted_trees",
        "objective": objective,
        "feature_columns": list(FEATURE_COLUMNS),
        "data_snapshot_ids": sorted(validated["data_snapshot_id"].astype(str).unique()),
        "sources": source_rows,
        "is_synthetic": synthetic,
        "serving_ready": False,
        "split_protocol": {
            "temporal": "full target windows assigned by time; boundary-crossing rows excluded",
            "validation_start": validation_start,
            "test_start": test_start,
            "spatial_holdout_groups": list(splits.spatial_holdout_groups),
            "spatial_holdout_seed": seed,
            "spatial_holdout_fraction": 0.20,
            "early_stopping_split": "validation",
            "test_used_for_tuning": False,
        },
        "row_counts": {
            "input": int(len(validated)),
            "train": int(len(splits.train)),
            "validation": int(len(splits.validation)),
            "temporal_test": int(len(splits.temporal_test)),
            "spatial_test": int(len(splits.spatial_test)),
        },
        "parameters": {
            "n_estimators": n_estimators,
            "early_stopping_rounds": early_stopping_rounds,
            "max_depth": max_depth,
            "learning_rate": learning_rate,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": seed,
        },
        "best_iteration": int(model.best_iteration),
        "metrics": split_metrics,
        "note": (
            "Synthetic demonstration metrics measure recovery of the synthetic generator only; "
            "they are not HCMC demand accuracy."
            if synthetic
            else "Prediction quality requires domain review and a qualified observed-data backtest."
        ),
    }
    (output_dir / "model_card.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    gains = model.get_score(importance_type="gain")
    importance = pd.DataFrame(
        {
            "feature": FEATURE_COLUMNS,
            "gain": [float(gains.get(name, 0.0)) for name in FEATURE_COLUMNS],
        }
    )
    importance.to_csv(output_dir / "feature_importance.csv", index=False)
    return report


def _read_input(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"training table not found: {path}")
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, help="M1 training-table CSV or Parquet")
    parser.add_argument(
        "--synthetic-demo", action="store_true", help="generate clearly labeled synthetic data"
    )
    parser.add_argument("--target", choices=tuple(TARGET_UNITS), default="charging_sessions")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR / "charging_sessions")
    parser.add_argument("--validation-start", default="2025-06-01T00:00:00+07:00")
    parser.add_argument("--test-start", default="2025-08-01T00:00:00+07:00")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-estimators", type=int, default=1000)
    parser.add_argument("--early-stopping-rounds", type=int, default=50)
    parser.add_argument("--max-depth", type=int, default=6)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if bool(args.input) == bool(args.synthetic_demo):
        raise SystemExit("provide exactly one of --input or --synthetic-demo")
    if args.synthetic_demo:
        frame = generate_synthetic_dataset(seed=args.seed, target=args.target)
    else:
        frame = _read_input(args.input)
    report = train_model(
        frame,
        target=args.target,
        output_dir=args.output_dir,
        validation_start=args.validation_start,
        test_start=args.test_start,
        seed=args.seed,
        n_estimators=args.n_estimators,
        early_stopping_rounds=args.early_stopping_rounds,
        max_depth=args.max_depth,
        learning_rate=args.learning_rate,
        allow_synthetic=args.synthetic_demo,
    )
    print(f"model_version: {report['model_version']}")
    print(f"model_card  : {args.output_dir / 'model_card.json'}")
    print(f"metrics     : {json.dumps(report['metrics'], ensure_ascii=False)}")
    if report["is_synthetic"]:
        print("WARNING: synthetic demonstration only; not HCMC operating evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
