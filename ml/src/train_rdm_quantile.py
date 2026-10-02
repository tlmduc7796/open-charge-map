#!/usr/bin/env python3
"""Train a quantile RDM from a canonical, session-safe dataset.

The command fits on train, chooses/report on validation, and intentionally
does not access test unless ``--evaluate-test`` is explicitly supplied.  This
makes a test access an auditable promotion action instead of a hidden tuning
loop.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

try:  # Supports package import and `python ml/src/...py`.
    from .data_pipeline.rdm import RDM_FEATURE_COLUMNS, RDM_TARGET_COLUMN
except ImportError:  # pragma: no cover - direct CLI invocation.
    from data_pipeline.rdm import RDM_FEATURE_COLUMNS, RDM_TARGET_COLUMN

ROOT_DIR = Path(__file__).resolve().parents[2]
QUANTILES = (0.1, 0.5, 0.9)
NUMERIC_FEATURES = ("session_elapsed_min", "energy_delivered_kwh", "current_power_kw")
CATEGORICAL_FEATURES = ("station_id", "port_id", "connector_type")


def _build_model(quantile: float, seed: int) -> Pipeline:
    try:
        from xgboost import XGBRegressor
    except ImportError as exc:
        raise RuntimeError("Install ml/requirements.txt to train quantile RDM") from exc
    preprocessor = ColumnTransformer(
        [
            ("numeric", SimpleImputer(strategy="median"), list(NUMERIC_FEATURES)),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        ("one_hot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
                    ]
                ),
                list(CATEGORICAL_FEATURES),
            ),
        ],
        sparse_threshold=0,
    )
    model = XGBRegressor(
        objective="reg:quantileerror",
        quantile_alpha=quantile,
        n_estimators=350,
        max_depth=6,
        learning_rate=0.04,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=seed,
        n_jobs=-1,
    )
    return Pipeline([("features", preprocessor), ("model", model)])


def _validate_dataset(frame: pd.DataFrame) -> None:
    required = {"session_id", "observed_at", "split", *RDM_FEATURE_COLUMNS, RDM_TARGET_COLUMN}
    if missing := required - set(frame.columns):
        raise ValueError(f"RDM dataset misses columns: {sorted(missing)}")
    if not {"train", "val", "test"}.issubset(set(frame["split"])):
        raise ValueError("RDM dataset must contain train, val and test splits")
    if (frame.groupby("session_id")["split"].nunique() != 1).any():
        raise ValueError("RDM dataset has a session split across train/val/test")
    if (frame[RDM_TARGET_COLUMN] <= 0).any():
        raise ValueError("RDM target must remain strictly positive")


def _metrics(observed: pd.Series, predictions: dict[float, np.ndarray]) -> dict[str, float]:
    median = predictions[0.5]
    result = {
        "mae_p50": round(float(mean_absolute_error(observed, median)), 6),
        "median_absolute_error_p50": round(
            float(np.median(np.abs(observed.to_numpy() - median))), 6
        ),
        "rmse_p50": round(float(mean_squared_error(observed, median) ** 0.5), 6),
        "coverage_p10": round(float(np.mean(observed.to_numpy() <= predictions[0.1])), 6),
        "coverage_p50": round(float(np.mean(observed.to_numpy() <= median)), 6),
        "coverage_p90": round(float(np.mean(observed.to_numpy() <= predictions[0.9])), 6),
        "quantile_crossing_rate": round(
            float(np.mean((predictions[0.1] > median) | (median > predictions[0.9]))), 6
        ),
    }
    return result


def train_rdm(
    dataset_path: Path,
    artifact_dir: Path,
    *,
    seed: int = 42,
    evaluate_test: bool = False,
) -> dict[str, object]:
    """Fit RDM models and return validation metrics; test is opt-in only."""
    frame = pd.read_parquet(dataset_path)
    _validate_dataset(frame)
    train = frame.loc[frame["split"] == "train"]
    validation = frame.loc[frame["split"] == "val"]
    models: dict[float, Pipeline] = {}
    validation_predictions: dict[float, np.ndarray] = {}
    for quantile in QUANTILES:
        model = _build_model(quantile, seed)
        model.fit(train.loc[:, list(RDM_FEATURE_COLUMNS)], train[RDM_TARGET_COLUMN])
        models[quantile] = model
        validation_predictions[quantile] = model.predict(
            validation.loc[:, list(RDM_FEATURE_COLUMNS)]
        )
    metadata: dict[str, object] = {
        "format_version": "rdm-quantile-1",
        "created_at": datetime.now(UTC).isoformat(),
        "model_type": "xgboost_quantile_rdm",
        "status": "experimental_not_serving_ready",
        "dataset": str(dataset_path),
        "target": RDM_TARGET_COLUMN,
        "target_semantics": "disconnect_at - observed_at (physical port release)",
        "feature_columns": list(RDM_FEATURE_COLUMNS),
        "quantiles": list(QUANTILES),
        "split_policy": "all observations of a session assigned by disconnect_at",
        "validation_metrics": _metrics(validation[RDM_TARGET_COLUMN], validation_predictions),
        "test_accessed": False,
        "test_status": "not_accessed",
        "serving_rule": (
            "provider-reported duration wins; promote only after calibration/replay review"
        ),
    }
    if evaluate_test:
        test = frame.loc[frame["split"] == "test"]
        test_predictions = {
            quantile: model.predict(test.loc[:, list(RDM_FEATURE_COLUMNS)])
            for quantile, model in models.items()
        }
        metadata["test_metrics"] = _metrics(test[RDM_TARGET_COLUMN], test_predictions)
        metadata["test_accessed"] = True
        metadata["test_accessed_at"] = datetime.now(UTC).isoformat()
        metadata["test_status"] = "exploratory_until_protocol_is_frozen"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "rdm_quantile_models.joblib"
    metadata_path = artifact_dir / "rdm_quantile_meta.json"
    joblib.dump({str(quantile): model for quantile, model in models.items()}, model_path)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"model": str(model_path), "metadata": str(metadata_path), **metadata}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=ROOT_DIR / "ml/data/gold/rdm/rdm_observations.parquet"
    )
    parser.add_argument("--artifact-dir", type=Path, default=ROOT_DIR / "ml/artifacts/rdm")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--evaluate-test",
        action="store_true",
        help="Explicitly access the final test split and mark the run exploratory.",
    )
    args = parser.parse_args()
    plan = {
        "dataset": str(args.dataset),
        "artifact_dir": str(args.artifact_dir),
        "will_train": args.execute,
        "test_will_be_accessed": args.evaluate_test,
        "target": RDM_TARGET_COLUMN,
        "required_features": list(RDM_FEATURE_COLUMNS),
    }
    if not args.execute:
        print(
            json.dumps(
                {**plan, "next_step": "Build canonical ACN/operator data, then add --execute."},
                indent=2,
            )
        )
        return
    print(
        json.dumps(
            {
                **plan,
                **train_rdm(
                    args.dataset,
                    args.artifact_dir,
                    seed=args.seed,
                    evaluate_test=args.evaluate_test,
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
