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
    from .feature_contract import (
        CONTRACT_VERSION,
        HORIZONS_MIN,
        LAG_FEATURES,
        SEASONAL_PRIOR_FEATURES,
        get_feature_profile,
        target_column,
    )
except ImportError:  # pragma: no cover - direct script invocation.
    from feature_contract import (
        CONTRACT_VERSION,
        HORIZONS_MIN,
        LAG_FEATURES,
        SEASONAL_PRIOR_FEATURES,
        get_feature_profile,
        target_column,
    )

ROOT_DIR = Path(__file__).resolve().parents[2]
PREDICTION_MODES = ("direct", "residual_to_persistence")


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


def _metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float | None]:
    """Point-error plus regression calibration diagnostics for bounded ratios."""
    observed = y_true.to_numpy(dtype=float)
    prediction = np.asarray(y_pred, dtype=float)
    bins = np.linspace(0.0, 1.0, 11)
    bucket = np.digitize(prediction, bins[1:-1], right=False)
    calibration_ece = 0.0
    for index in range(10):
        mask = bucket == index
        if mask.any():
            calibration_ece += float(
                mask.mean() * abs(observed[mask].mean() - prediction[mask].mean())
            )
    variance = float(np.var(prediction))
    slope = None
    intercept = None
    if variance > 1e-12:
        slope = float(
            np.mean((prediction - prediction.mean()) * (observed - observed.mean())) / variance
        )
        intercept = float(observed.mean() - slope * prediction.mean())
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 6),
        "rmse": round(float(mean_squared_error(y_true, y_pred) ** 0.5), 6),
        "calibration_ece_10bin": round(calibration_ece, 6),
        "calibration_slope": round(slope, 6) if slope is not None else None,
        "calibration_intercept": round(intercept, 6) if intercept is not None else None,
    }


def _persistence(frame: pd.DataFrame) -> np.ndarray:
    return frame["lag_1"].to_numpy(dtype=float)


def _model_features(profile_name: str, horizon: int) -> tuple[str, ...]:
    """Direct models receive only the seasonal value for their own target time."""
    if profile_name == "seasonal":
        return (*LAG_FEATURES, SEASONAL_PRIOR_FEATURES[HORIZONS_MIN.index(horizon)])
    return LAG_FEATURES


def _prediction_from_model(
    model_prediction: np.ndarray,
    frame: pd.DataFrame,
    *,
    prediction_mode: str,
) -> np.ndarray:
    """Recover bounded occupancy from a direct or persistence-residual model."""
    raw = np.asarray(model_prediction, dtype=float)
    if prediction_mode == "residual_to_persistence":
        raw = _persistence(frame) + raw
    return np.clip(raw, 0.0, 1.0)


def train(
    dataset_path: Path,
    artifact_dir: Path,
    *,
    max_train_rows: int | None = None,
    seed: int = 42,
    prediction_mode: str = "direct",
    evaluate_test: bool = False,
) -> dict[str, object]:
    """Train a source-domain artifact for format checks, never UrbanEV serving."""
    if prediction_mode not in PREDICTION_MODES:
        raise ValueError(f"Unknown prediction mode: {prediction_mode}")
    metadata = _load_metadata(dataset_path)
    if not metadata.get("serving_ready"):
        raise ValueError(
            "This feature profile is not deployment-ready: "
            f"{metadata.get('serving_reason', 'missing serving prerequisite')}"
        )
    frame = pd.read_parquet(dataset_path)
    _validate_dataset(frame, metadata)
    profile_name = str(metadata["profile"])
    train_frame = frame.loc[frame["split"] == "train"].copy()
    if max_train_rows is not None and max_train_rows > 0 and len(train_frame) > max_train_rows:
        # Deterministic thinning is for local smoke checks only.  Never use it
        # for the final benchmark because it changes the training distribution.
        train_frame = train_frame.sample(n=max_train_rows, random_state=seed).sort_index()
    val_frame = frame.loc[frame["split"] == "val"]
    test_frame = frame.loc[frame["split"] == "test"] if evaluate_test else None

    try:
        from xgboost import XGBRegressor
    except ImportError as exc:  # Keeps backend-only installs lightweight.
        raise RuntimeError("Install ml/requirements.txt to train the XGBoost model") from exc

    models: dict[int, object] = {}
    features_by_horizon: dict[int, tuple[str, ...]] = {}
    metrics: dict[str, object] = {}
    for horizon in HORIZONS_MIN:
        target = target_column(horizon)
        feature_names = _model_features(profile_name, horizon)
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
        train_target = train_frame[target]
        if prediction_mode == "residual_to_persistence":
            train_target = train_target - train_frame["lag_1"]
        model.fit(train_frame.loc[:, feature_names], train_target)
        val_pred = _prediction_from_model(
            model.predict(val_frame.loc[:, feature_names]),
            val_frame,
            prediction_mode=prediction_mode,
        )
        horizon_metrics: dict[str, object] = {
            "validation": {
                "persistence": _metrics(val_frame[target], _persistence(val_frame)),
                "xgboost": _metrics(val_frame[target], val_pred),
            }
        }
        seasonal_column = SEASONAL_PRIOR_FEATURES[HORIZONS_MIN.index(horizon)]
        if seasonal_column in frame:
            horizon_metrics["validation"]["seasonal_naive"] = _metrics(
                val_frame[target], val_frame[seasonal_column].to_numpy(dtype=float)
            )
        if evaluate_test:
            assert test_frame is not None
            test_pred = _prediction_from_model(
                model.predict(test_frame.loc[:, feature_names]),
                test_frame,
                prediction_mode=prediction_mode,
            )
            test_metrics: dict[str, object] = {
                "persistence": _metrics(test_frame[target], _persistence(test_frame)),
                "xgboost": _metrics(test_frame[target], test_pred),
            }
            if seasonal_column in frame:
                test_metrics["seasonal_naive"] = _metrics(
                    test_frame[target], test_frame[seasonal_column].to_numpy(dtype=float)
                )
            horizon_metrics["test_exploratory"] = test_metrics
        metrics[str(horizon)] = horizon_metrics
        models[horizon] = model
        features_by_horizon[horizon] = feature_names

    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "occupancy_model.joblib"
    preprocessor_path = artifact_dir / "occupancy_preprocessor.joblib"
    meta_path = artifact_dir / "occupancy_model_meta.json"
    model_bundle = {
        "format_version": CONTRACT_VERSION,
        "prediction_mode": prediction_mode,
        "models": models,
        "feature_names_by_horizon": {
            str(horizon): list(names) for horizon, names in features_by_horizon.items()
        },
    }
    preprocessor_bundle: dict[str, object] = {
        "format_version": CONTRACT_VERSION,
        "prediction_mode": prediction_mode,
        "feature_names_by_horizon": {
            str(horizon): list(names) for horizon, names in features_by_horizon.items()
        },
    }
    if profile_name == "seasonal":
        profile_path = Path(str(metadata.get("seasonal_profile_path") or ""))
        if not profile_path.is_file():
            raise ValueError("Seasonal profile file is required for a seasonal model release")
        preprocessor_bundle["seasonal_profile"] = json.loads(
            profile_path.read_text(encoding="utf-8")
        )
    joblib.dump(
        model_bundle,
        model_path,
    )
    # There is no scaler for bounded occupancy ratios.  Keep this explicit
    # artifact so backend loading can validate one complete release bundle.
    joblib.dump(preprocessor_bundle, preprocessor_path)
    release_meta = {
        "format_version": CONTRACT_VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "model_type": f"xgboost_{prediction_mode}_multi_horizon",
        "prediction_mode": prediction_mode,
        "profile": metadata["profile"],
        "feature_names": list(metadata["feature_names"]),
        "feature_names_by_horizon": {
            str(horizon): list(names) for horizon, names in features_by_horizon.items()
        },
        "lookback_steps": 12,
        "horizons_min": list(HORIZONS_MIN),
        "target": "occupancy_ratio",
        "calibration": "10-bin reliability ECE plus OLS observed-on-predicted slope/intercept",
        "metrics": metrics,
        "test_accessed": evaluate_test,
        "test_status": (
            "exploratory_until_protocol_is_frozen" if evaluate_test else "not_accessed"
        ),
        "source_feature_metadata": str(dataset_path.with_suffix(".meta.json")),
        "serving_ready": False,
        "release_status": "exploratory_source_domain_only",
        "limitations": [
            (
                "UrbanEV is Shenzhen, China historical data and must not be treated "
                "as Vietnamese ground truth."
            ),
            "This artifact is intentionally rejected by backend serving.",
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
        default=ROOT_DIR / "ml/data/features/occupancy_features_baseline.parquet",
    )
    parser.add_argument("--artifact-dir", type=Path, default=ROOT_DIR / "ml/artifacts")
    parser.add_argument("--max-train-rows", type=int)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--prediction-mode", choices=PREDICTION_MODES, default="direct")
    parser.add_argument(
        "--evaluate-test",
        action="store_true",
        help="Explicitly access test and label the run exploratory until the protocol is frozen.",
    )
    parser.add_argument(
        "--execute", action="store_true", help="Actually train and write artifacts."
    )
    args = parser.parse_args()
    plan = {
        "dataset": str(args.dataset),
        "artifact_dir": str(args.artifact_dir),
        "will_train": args.execute,
        "max_train_rows": args.max_train_rows,
        "prediction_mode": args.prediction_mode,
        "test_will_be_accessed": args.evaluate_test,
    }
    if not args.execute:
        print(
            json.dumps({**plan, "next_step": "Review data, then rerun with --execute."}, indent=2)
        )
        return
    result = train(
        args.dataset,
        args.artifact_dir,
        max_train_rows=args.max_train_rows,
        seed=args.seed,
        prediction_mode=args.prediction_mode,
        evaluate_test=args.evaluate_test,
    )
    print(json.dumps({**plan, **result}, indent=2))


if __name__ == "__main__":
    main()
