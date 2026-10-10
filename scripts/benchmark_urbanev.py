#!/usr/bin/env python3
"""Run the UrbanEV occupancy benchmark as an exploratory source-domain study.

This command deliberately does not create a serving bundle.  UrbanEV's test
window has already informed modelling decisions, so its metrics are useful for
comparison but are not an untouched final holdout or a deployment claim.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.occupancy_contract import (  # noqa: E402
    INTERVAL_MIN,
    LAG_FEATURES,
    SUPPORTED_HORIZONS_MIN,
    target_column,
)

HORIZONS_MIN = SUPPORTED_HORIZONS_MIN
DAILY_STEPS = 24 * 60 // INTERVAL_MIN
WEEKLY_STEPS = 7 * DAILY_STEPS
DEFAULT_ALPHAS = (0.0, 0.25, 0.5, 0.75, 1.0)
PHASE_04_TEST_MAE_GAIN = 0.05


def _load_processed(path: Path) -> pd.DataFrame:
    required = {"timestamp", "entity_id", "occupancy_ratio", "split", "interval_min"}
    frame = pd.read_parquet(path)
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Processed occupancy data misses columns: {sorted(missing)}")
    frame = frame.loc[:, list(required)].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="raise")
    if not (frame["interval_min"] == INTERVAL_MIN).all():
        raise ValueError(f"Benchmark requires {INTERVAL_MIN}-minute occupancy data")
    if not frame["occupancy_ratio"].between(0.0, 1.0).all():
        raise ValueError("occupancy_ratio must be bounded in [0, 1]")
    if frame.duplicated(["entity_id", "timestamp"]).any():
        raise ValueError("Duplicate station timestamps are not supported")
    frame = frame.sort_values(["entity_id", "timestamp"]).reset_index(drop=True)
    _require_regular_cadence(frame)
    return frame


def _require_regular_cadence(frame: pd.DataFrame) -> None:
    expected = pd.Timedelta(minutes=INTERVAL_MIN)
    differences = frame.groupby("entity_id", sort=False)["timestamp"].diff().dropna()
    if not differences.eq(expected).all():
        raise ValueError(
            "Daily/weekly naive offsets require a contiguous 5-minute series; "
            "resample or explicitly handle gaps before benchmarking."
        )


def build_horizon_frame(frame: pd.DataFrame, horizon_min: int) -> pd.DataFrame:
    """Build one direct-horizon frame without labels crossing a split boundary.

    At origin t and horizon h, daily-naive is occupancy at
    ``(t + h) - 24h`` and weekly-naive at ``(t + h) - 7d``.  Thus at +5
    minutes their offsets from t are 287 and 2015 five-minute rows.
    """
    if horizon_min not in HORIZONS_MIN:
        raise ValueError(f"Unsupported horizon: {horizon_min}")
    steps = horizon_min // INTERVAL_MIN
    daily_offset = DAILY_STEPS - steps
    weekly_offset = WEEKLY_STEPS - steps
    if daily_offset <= 0 or weekly_offset <= 0:
        raise ValueError("Horizon must be shorter than a day and a week")

    result = frame.loc[:, ["timestamp", "entity_id", "split"]].copy()
    grouped_value = frame.groupby("entity_id", sort=False)["occupancy_ratio"]
    grouped_split = frame.groupby("entity_id", sort=False)["split"]
    for step, name in enumerate(LAG_FEATURES, start=1):
        result[name] = grouped_value.shift(step)
    target_name = target_column(horizon_min)
    result[target_name] = grouped_value.shift(-steps)
    result["target_split"] = grouped_split.shift(-steps)
    result["persistence"] = grouped_value.shift(1)
    result["daily_naive"] = grouped_value.shift(daily_offset)
    result["weekly_naive"] = grouped_value.shift(weekly_offset)
    result = result.loc[result["target_split"] == result["split"]].copy()
    return result.dropna(
        subset=[*LAG_FEATURES, target_name, "persistence", "daily_naive", "weekly_naive"]
    ).drop(columns="target_split")


def regression_metrics(
    y_true: pd.Series | np.ndarray, y_pred: np.ndarray
) -> dict[str, float | None]:
    """Point metrics plus reliability diagnostics; these are not confidence."""
    observed = np.asarray(y_true, dtype=float)
    prediction = np.clip(np.asarray(y_pred, dtype=float), 0.0, 1.0)
    bins = np.linspace(0.0, 1.0, 11)
    bucket = np.digitize(prediction, bins[1:-1], right=False)
    ece = 0.0
    for index in range(10):
        mask = bucket == index
        if mask.any():
            ece += float(mask.mean() * abs(observed[mask].mean() - prediction[mask].mean()))
    variance = float(np.var(prediction))
    slope: float | None = None
    intercept: float | None = None
    if variance > 1e-12:
        slope = float(
            np.mean((prediction - prediction.mean()) * (observed - observed.mean())) / variance
        )
        intercept = float(observed.mean() - slope * prediction.mean())
    return {
        "mae": round(float(mean_absolute_error(observed, prediction)), 6),
        "median_absolute_error": round(float(np.median(np.abs(observed - prediction))), 6),
        "rmse": round(float(mean_squared_error(observed, prediction) ** 0.5), 6),
        "calibration_ece_10bin": round(ece, 6),
        "calibration_slope": round(slope, 6) if slope is not None else None,
        "calibration_intercept": round(intercept, 6) if intercept is not None else None,
    }


def apply_residual_gate(
    persistence: np.ndarray,
    residual: np.ndarray,
    *,
    alpha: float,
    threshold: float,
) -> np.ndarray:
    """Apply a residual-magnitude gate, not a model confidence gate."""
    accepted = np.where(np.abs(residual) >= threshold, alpha * residual, 0.0)
    return np.clip(np.asarray(persistence, dtype=float) + accepted, 0.0, 1.0)


def choose_residual_gate(
    y_true: pd.Series | np.ndarray,
    persistence: np.ndarray,
    residual_prediction: np.ndarray,
    *,
    alphas: tuple[float, ...] = DEFAULT_ALPHAS,
) -> dict[str, float]:
    """Choose alpha/tau only on validation, with persistence winning ties."""
    residual = np.asarray(residual_prediction, dtype=float)
    thresholds = tuple(
        sorted({0.0, *(float(np.quantile(abs(residual), q)) for q in (0.25, 0.5, 0.75, 0.9))})
    )
    baseline_mae = float(mean_absolute_error(y_true, persistence))
    best = {"alpha": 0.0, "threshold": 0.0, "validation_mae": baseline_mae}
    for alpha in alphas:
        if not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha candidates must be within [0, 1]")
        for threshold in thresholds:
            prediction = apply_residual_gate(
                persistence, residual, alpha=alpha, threshold=threshold
            )
            mae = float(mean_absolute_error(y_true, prediction))
            # Strictly better only: alpha=0 is retained for ties and must be
            # reported as persistence, never as an ML win.
            if mae < best["validation_mae"] - 1e-12:
                best = {"alpha": float(alpha), "threshold": float(threshold), "validation_mae": mae}
    return {key: round(value, 8) for key, value in best.items()}


def relative_mae_gain(persistence_mae: float, candidate_mae: float) -> float:
    if persistence_mae <= 0:
        raise ValueError("persistence MAE must be positive to calculate relative improvement")
    return (persistence_mae - candidate_mae) / persistence_mae


def _dataset_reference(dataset_path: Path) -> str:
    resolved = dataset_path.resolve()
    try:
        return resolved.relative_to(ROOT_DIR).as_posix()
    except ValueError:
        return dataset_path.name


def _fit_xgboost(
    train_frame: pd.DataFrame,
    target: str,
    *,
    seed: int,
    max_train_rows: int | None,
):
    try:
        from xgboost import XGBRegressor
    except ImportError as exc:  # pragma: no cover - dependency is environment-specific.
        raise RuntimeError("Install ml/requirements-benchmark.txt to run this benchmark") from exc
    if max_train_rows is not None and max_train_rows > 0 and len(train_frame) > max_train_rows:
        train_frame = train_frame.sample(n=max_train_rows, random_state=seed).sort_index()
    model = XGBRegressor(
        objective="reg:absoluteerror",
        n_estimators=500,
        max_depth=8,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=seed,
        tree_method="hist",
        n_jobs=1,
    )
    residual_target = train_frame[target] - train_frame["persistence"]
    model.fit(train_frame.loc[:, LAG_FEATURES], residual_target)
    return model


def run_benchmark(
    dataset_path: Path,
    report_path: Path,
    *,
    seed: int = 42,
    max_train_rows: int | None = None,
    required_winning_horizons: int = len(HORIZONS_MIN),
) -> dict[str, object]:
    """Fit and compare only the cheap occupancy candidates requested for UrbanEV."""
    if not 1 <= required_winning_horizons <= len(HORIZONS_MIN):
        raise ValueError("required_winning_horizons must be between 1 and the horizon count")
    frame = _load_processed(dataset_path)
    preprocessing_meta_path = dataset_path.parent / "preprocessing_meta.json"
    preprocessing_meta = (
        json.loads(preprocessing_meta_path.read_text(encoding="utf-8"))
        if preprocessing_meta_path.is_file()
        else {}
    )
    split_manifest_path = dataset_path.parent / "split_manifest.json"
    split_manifest = (
        json.loads(split_manifest_path.read_text(encoding="utf-8"))
        if split_manifest_path.is_file()
        else {}
    )
    per_horizon: dict[str, object] = {}
    residual_wins = 0
    historical_test_threshold_wins = 0
    for horizon in HORIZONS_MIN:
        sample = build_horizon_frame(frame, horizon)
        target = target_column(horizon)
        train = sample.loc[sample["split"] == "train"]
        validation = sample.loc[sample["split"] == "val"]
        test = sample.loc[sample["split"] == "test"]
        if train.empty or validation.empty or test.empty:
            raise ValueError(f"Horizon {horizon} has an empty temporal split")
        model = _fit_xgboost(train, target, seed=seed, max_train_rows=max_train_rows)
        validation_residual = model.predict(validation.loc[:, LAG_FEATURES])
        gate = choose_residual_gate(
            validation[target], validation["persistence"].to_numpy(), validation_residual
        )
        validation_prediction = apply_residual_gate(
            validation["persistence"].to_numpy(),
            validation_residual,
            alpha=gate["alpha"],
            threshold=gate["threshold"],
        )
        test_residual = model.predict(test.loc[:, LAG_FEATURES])
        test_prediction = apply_residual_gate(
            test["persistence"].to_numpy(),
            test_residual,
            alpha=gate["alpha"],
            threshold=gate["threshold"],
        )
        validation_baselines = {
            name: regression_metrics(validation[target], validation[name].to_numpy())
            for name in ("persistence", "daily_naive", "weekly_naive")
        }
        test_baselines = {
            name: regression_metrics(test[target], test[name].to_numpy())
            for name in ("persistence", "daily_naive", "weekly_naive")
        }
        best_baseline_mae = min(float(item["mae"]) for item in validation_baselines.values())
        residual_wins_this_horizon = (
            gate["alpha"] > 0 and gate["validation_mae"] < best_baseline_mae
        )
        residual_wins += int(residual_wins_this_horizon)
        persistence_test_mae = float(test_baselines["persistence"]["mae"])
        candidate_test_mae = float(
            regression_metrics(test[target], test_prediction)["mae"]
        )
        relative_test_gain = relative_mae_gain(persistence_test_mae, candidate_test_mae)
        historical_test_threshold_wins += int(
            relative_test_gain >= PHASE_04_TEST_MAE_GAIN
        )
        per_horizon[str(horizon)] = {
            "sample_counts": {
                name: int(len(part))
                for name, part in (("train", train), ("val", validation), ("test", test))
            },
            "daily_offset_steps": DAILY_STEPS - horizon // INTERVAL_MIN,
            "weekly_offset_steps": WEEKLY_STEPS - horizon // INTERVAL_MIN,
            "residual_magnitude_gate": {
                **gate,
                "description": (
                    "Gate on predicted residual magnitude; this is not confidence or uncertainty."
                ),
            },
            "validation": {
                **validation_baselines,
                "gated_residual_xgboost": regression_metrics(
                    validation[target], validation_prediction
                ),
            },
            "test_exploratory_only": {
                **test_baselines,
                "gated_residual_xgboost": regression_metrics(test[target], test_prediction),
            },
            "historical_test_gate_diagnostic": {
                "mae_gain_vs_persistence": round(relative_test_gain, 6),
                "required_gain": PHASE_04_TEST_MAE_GAIN,
                "meets_threshold": relative_test_gain >= PHASE_04_TEST_MAE_GAIN,
                "decision_use": "diagnostic_only_test_window_was_previously_inspected",
            },
            "decision": "RESIDUAL_WINS" if residual_wins_this_horizon else "BASELINE_WINS_OR_TIES",
        }
    if residual_wins < required_winning_horizons:
        verdict = "NO_GO_VALIDATION_IMPROVEMENT_REQUIREMENT"
    elif historical_test_threshold_wins < len(HORIZONS_MIN):
        verdict = "NO_GO_HISTORICAL_TEST_MAE_THRESHOLD"
    else:
        verdict = "GO_NEXT_INDEPENDENT_HOLDOUT_REQUIRED"
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "benchmark_scope": "exploratory_source_domain_benchmark",
        "dataset": _dataset_reference(dataset_path),
        "dataset_sha256": preprocessing_meta.get("parquet_sha256"),
        "source_archive_sha256": split_manifest.get("source_archive_sha256"),
        "serving_contract_version": "2.2",
        "horizons_min": list(HORIZONS_MIN),
        "deployment_eligible": False,
        "test_status": "Previously inspected; not an untouched final holdout.",
        "final_independent_holdout_required": True,
        "objective": "reg:absoluteerror",
        "models": ["persistence", "daily_naive", "weekly_naive", "gated_residual_xgboost"],
        "confidence_statement": (
            "No confidence estimate is produced. The gate is residual magnitude only."
        ),
        "daily_weekly_definition": "At target t+h, use occupancy at target-24h and target-7d.",
        "required_winning_horizons": required_winning_horizons,
        "residual_winning_horizons": residual_wins,
        "phase_04_test_mae_gain_threshold": PHASE_04_TEST_MAE_GAIN,
        "historical_test_horizons_meeting_threshold": historical_test_threshold_wins,
        "historical_test_all_horizons_meet_threshold": (
            historical_test_threshold_wins == len(HORIZONS_MIN)
        ),
        "training_config": {
            "seed": seed,
            "max_train_rows_per_horizon": max_train_rows,
            "objective": "reg:absoluteerror",
            "n_estimators": 500,
            "max_depth": 8,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "tree_method": "hist",
            "n_jobs": 1,
            "xgboost_version": importlib.metadata.version("xgboost"),
        },
        "verdict": verdict,
        "per_horizon": per_horizon,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT_DIR / "data/ml/urbanev/processed/urbanev_processed.parquet",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT_DIR
        / "data/ml/urbanev/processed/exploratory_benchmark_contract_2_2.json",
    )
    parser.add_argument("--max-train-rows", type=int)
    parser.add_argument("--required-winning-horizons", type=int, default=len(HORIZONS_MIN))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    plan = {
        "will_run": args.execute,
        "dataset": str(args.dataset),
        "report": str(args.report),
        "scope": "exploratory_source_domain_benchmark_not_deployable",
    }
    if not args.execute:
        print(json.dumps({**plan, "next_step": "Review, then rerun with --execute."}, indent=2))
        return
    result = run_benchmark(
        args.dataset,
        args.report,
        seed=args.seed,
        max_train_rows=args.max_train_rows,
        required_winning_horizons=args.required_winning_horizons,
    )
    print(json.dumps({**plan, "verdict": result["verdict"], "report": str(args.report)}, indent=2))


if __name__ == "__main__":
    main()
