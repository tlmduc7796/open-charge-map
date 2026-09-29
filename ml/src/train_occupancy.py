#!/usr/bin/env python3
"""Reproducible Phase 04 trainer. It plans by default; pass --execute to train.

The command is deliberately cloud-friendly: data and artifact paths are CLI
arguments, so a Kaggle/Colab notebook can mount/upload data and invoke exactly
the same command without copying training logic into notebook cells.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

try:  # Supports both `python ml/src/...py` and package imports in notebooks.
    from .feature_contract import CONTRACT_VERSION, HORIZONS_MIN, get_feature_profile, target_column
except ImportError:  # pragma: no cover - direct script invocation.
    from feature_contract import CONTRACT_VERSION, HORIZONS_MIN, get_feature_profile, target_column

ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_metadata(dataset_path: Path) -> dict[str, object]:
    path = dataset_path.with_suffix(".meta.json")
    if not path.is_file():
        raise FileNotFoundError(f"Feature metadata not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_dataset(frame: pd.DataFrame, metadata: dict[str, object]) -> tuple[str, ...]:
    profile = get_feature_profile(str(metadata["profile"]))
    if metadata.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("Feature dataset contract version is incompatible with this trainer")
    expected = list(profile.feature_names)
    if metadata.get("feature_names") != expected:
        raise ValueError("Feature dataset metadata does not match the declared profile")
    required = {"split", *expected, *(target_column(h) for h in HORIZONS_MIN)}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Feature dataset misses columns: {sorted(missing)}")
    if set(frame["split"].unique()) != {"train", "val", "test"}:
        raise ValueError("Feature dataset must contain train, val and test rows")
    return tuple(expected)


def _metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 6),
        "rmse": round(float(mean_squared_error(y_true, y_pred) ** 0.5), 6),
    }


def _persistence(frame: pd.DataFrame) -> np.ndarray:
    return frame["lag_1"].to_numpy(dtype=float)


def train(
    dataset_path: Path,
    artifact_dir: Path,
    *,
    max_train_rows: int | None = None,
    seed: int = 42,
) -> dict[str, object]:
    """Train direct XGBoost models and emit a backend-compatible model bundle."""
    metadata = _load_metadata(dataset_path)
    if not metadata.get("serving_ready"):
        raise ValueError(
            "This feature profile is not deployment-ready: "
            f"{metadata.get('serving_reason', 'missing serving prerequisite')}"
        )
    frame = pd.read_parquet(dataset_path)
    feature_names = _validate_dataset(frame, metadata)
    train_frame = frame.loc[frame["split"] == "train"].copy()
    if max_train_rows is not None and max_train_rows > 0 and len(train_frame) > max_train_rows:
        # Deterministic thinning is for local smoke checks only.  Never use it
        # for the final benchmark because it changes the training distribution.
        train_frame = train_frame.sample(n=max_train_rows, random_state=seed).sort_index()
    val_frame = frame.loc[frame["split"] == "val"]
    test_frame = frame.loc[frame["split"] == "test"]

    try:
        from xgboost import XGBRegressor
    except ImportError as exc:  # Keeps backend-only installs lightweight.
        raise RuntimeError("Install ml/requirements.txt to train the XGBoost model") from exc

    models: dict[int, object] = {}
    metrics: dict[str, object] = {}
    for horizon in HORIZONS_MIN:
        target = target_column(horizon)
        model = XGBRegressor(
            objective="reg:squarederror",
            n_estimators=500,
            max_depth=8,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=seed,
            n_jobs=-1,
        )
        model.fit(train_frame.loc[:, feature_names], train_frame[target])
        test_pred = np.clip(model.predict(test_frame.loc[:, feature_names]), 0.0, 1.0)
        metrics[str(horizon)] = {
            "persistence": _metrics(test_frame[target], _persistence(test_frame)),
            "xgboost": _metrics(test_frame[target], test_pred),
            "validation": _metrics(
                val_frame[target], np.clip(model.predict(val_frame.loc[:, feature_names]), 0.0, 1.0)
            ),
        }
        models[horizon] = model

    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "occupancy_model.joblib"
    preprocessor_path = artifact_dir / "occupancy_preprocessor.joblib"
    meta_path = artifact_dir / "occupancy_model_meta.json"
    joblib.dump(
        {
            "format_version": CONTRACT_VERSION,
            "models": models,
            "feature_names": list(feature_names),
        },
        model_path,
    )
    # There is no scaler for bounded occupancy ratios.  Keep this explicit
    # artifact so backend loading can validate one complete release bundle.
    joblib.dump(
        {"format_version": CONTRACT_VERSION, "feature_names": list(feature_names)},
        preprocessor_path,
    )
    release_meta = {
        "format_version": CONTRACT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "model_type": "xgboost_direct_multi_horizon",
        "profile": metadata["profile"],
        "feature_names": list(feature_names),
        "lookback_steps": 12,
        "horizons_min": list(HORIZONS_MIN),
        "target": "occupancy_ratio",
        "metrics": metrics,
        "source_feature_metadata": str(dataset_path.with_suffix(".meta.json")),
        "serving_ready": True,
        "limitations": [
            "UrbanEV is German historical data and must not be treated as Vietnamese ground truth.",
            "A retrain requires a temporal backtest and approval before replacing this bundle.",
        ],
    }
    meta_path.write_text(json.dumps(release_meta, indent=2) + "\n", encoding="utf-8")
    return {
        "model": str(model_path),
        "preprocessor": str(preprocessor_path),
        "metadata": str(meta_path),
        "metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT_DIR / "ml/artifacts/occupancy_features_baseline.parquet",
    )
    parser.add_argument("--artifact-dir", type=Path, default=ROOT_DIR / "ml/artifacts")
    parser.add_argument("--max-train-rows", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--execute", action="store_true", help="Actually train and write artifacts."
    )
    args = parser.parse_args()
    plan = {
        "dataset": str(args.dataset),
        "artifact_dir": str(args.artifact_dir),
        "will_train": args.execute,
        "max_train_rows": args.max_train_rows,
    }
    if not args.execute:
        print(
            json.dumps(
                {**plan, "next_step": "Review data, then rerun with --execute."}, indent=2
            )
        )
        return
    result = train(
        args.dataset,
        args.artifact_dir,
        max_train_rows=args.max_train_rows,
        seed=args.seed,
    )
    print(json.dumps({**plan, **result}, indent=2))


if __name__ == "__main__":
    main()
