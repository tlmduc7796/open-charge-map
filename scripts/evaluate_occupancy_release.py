#!/usr/bin/env python3
"""Evaluate a frozen serving bundle on a separately supplied temporal holdout.

This command never exports or promotes artifacts. Its holdout manifest is an
operator assertion and must be reviewed alongside the data collection record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.domain.model_artifacts import (  # noqa: E402
    SUPPORTED_HORIZONS,
    JoblibOccupancyPredictor,
)
from shared.occupancy_contract import INTERVAL_MIN, LOOKBACK_STEPS  # noqa: E402

HOLDOUT_STATUS = "independent_untouched"
CUSTOMER_DOMAIN = "hcmc_operational"
MINIMUM_RELATIVE_MAE_GAIN = 0.05


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp(value: Any, field: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"manifest {field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"manifest {field} must include a timezone")
    return parsed.tz_convert("UTC")


def _load_holdout(dataset_path: Path, manifest: dict[str, Any]) -> pd.DataFrame:
    frame = pd.read_parquet(dataset_path)
    required = {"timestamp", "entity_id", "occupancy_ratio", "data_origin"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"holdout is missing columns: {sorted(missing)}")
    if "split" in frame.columns:
        raise ValueError("release holdout must be a separate dataset without a split column")
    frame = frame.loc[:, ["timestamp", "entity_id", "occupancy_ratio", "data_origin"]].copy()
    timezone = manifest.get("timezone")
    if not isinstance(timezone, str) or not timezone:
        raise ValueError("manifest timezone is required")
    timestamps = pd.to_datetime(frame["timestamp"], errors="raise")
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    else:
        timestamps = timestamps.dt.tz_convert(timezone)
    frame["timestamp"] = timestamps.dt.tz_convert("UTC")
    if frame["entity_id"].isna().any():
        raise ValueError("holdout entity_id values cannot be null")
    frame["entity_id"] = frame["entity_id"].astype(str)
    frame["occupancy_ratio"] = pd.to_numeric(frame["occupancy_ratio"], errors="raise")
    if not frame["data_origin"].eq("observed").all():
        raise ValueError("release holdout may contain only data_origin=observed rows")
    if frame.empty or frame["entity_id"].str.strip().eq("").any():
        raise ValueError("holdout must contain rows with non-empty entity_id values")
    if frame["timestamp"].isna().any() or not np.isfinite(frame["occupancy_ratio"]).all():
        raise ValueError("holdout timestamps and occupancy values must be finite")
    if not frame["occupancy_ratio"].between(0.0, 1.0).all():
        raise ValueError("holdout occupancy_ratio must be in [0, 1]")
    if frame.duplicated(["entity_id", "timestamp"]).any():
        raise ValueError("holdout contains duplicate station timestamps")
    frame = frame.sort_values(["entity_id", "timestamp"]).reset_index(drop=True)
    expected = pd.Timedelta(minutes=INTERVAL_MIN)
    deltas = frame.groupby("entity_id", sort=False)["timestamp"].diff().dropna()
    if not deltas.eq(expected).all():
        raise ValueError("each holdout station series must have a contiguous 5-minute cadence")
    return frame


def validate_release_evidence(
    manifest: dict[str, Any],
    metadata: dict[str, Any],
    *,
    dataset_sha256: str,
    manifest_sha256: str,
) -> list[str]:
    """Return evidence gaps that prevent a customer-facing promotion decision."""
    gaps: list[str] = []
    if manifest.get("holdout_status") != HOLDOUT_STATUS:
        gaps.append("holdout_not_declared_independent_and_untouched")
    if manifest.get("model_selection_used") is not False:
        gaps.append("holdout_selection_independence_not_attested")
    if not isinstance(manifest.get("holdout_id"), str) or not manifest["holdout_id"].strip():
        gaps.append("holdout_id_missing")
    if not isinstance(manifest.get("source_record"), str) or not manifest["source_record"].strip():
        gaps.append("holdout_source_record_missing")
    manifest_dataset_hash = manifest.get("dataset_sha256")
    if (
        not isinstance(manifest_dataset_hash, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", manifest_dataset_hash) is None
    ):
        gaps.append("holdout_dataset_hash_missing_or_invalid")
    elif manifest_dataset_hash.lower() != dataset_sha256.lower():
        gaps.append("holdout_dataset_hash_mismatch")
    if re.fullmatch(r"[0-9a-fA-F]{64}", manifest_sha256) is None:
        gaps.append("holdout_manifest_hash_missing_or_invalid")
    calibration_policy = manifest.get("calibration_policy")
    if not isinstance(calibration_policy, dict):
        gaps.append("approved_calibration_policy_missing")
    elif not all(
        key in calibration_policy
        for key in (
            "max_ece_10bin",
            "min_slope",
            "max_slope",
            "max_abs_intercept",
            "approved_by",
            "approval_reference",
        )
    ):
        gaps.append("approved_calibration_policy_incomplete")
    else:
        try:
            max_ece = float(calibration_policy["max_ece_10bin"])
            min_slope = float(calibration_policy["min_slope"])
            max_slope = float(calibration_policy["max_slope"])
            max_intercept = float(calibration_policy["max_abs_intercept"])
            policy_valid = (
                all(
                    math.isfinite(value)
                    for value in (max_ece, min_slope, max_slope, max_intercept)
                )
                and 0 <= max_ece <= 1
                and 0 <= min_slope <= max_slope
                and 0 <= max_intercept <= 1
                and isinstance(calibration_policy["approved_by"], str)
                and bool(calibration_policy["approved_by"].strip())
                and isinstance(calibration_policy["approval_reference"], str)
                and bool(calibration_policy["approval_reference"].strip())
            )
        except (TypeError, ValueError):
            policy_valid = False
        if not policy_valid:
            gaps.append("approved_calibration_policy_invalid")
    sample_policy = manifest.get("sample_policy")
    if not isinstance(sample_policy, dict):
        gaps.append("approved_sample_policy_missing")
    elif not all(
        key in sample_policy
        for key in (
            "minimum_stations",
            "minimum_samples_per_horizon",
            "approved_by",
            "approval_reference",
        )
    ):
        gaps.append("approved_sample_policy_incomplete")
    elif (
        type(sample_policy["minimum_stations"]) is not int
        or sample_policy["minimum_stations"] < 1
        or type(sample_policy["minimum_samples_per_horizon"]) is not int
        or sample_policy["minimum_samples_per_horizon"] < 1
        or not isinstance(sample_policy["approved_by"], str)
        or not sample_policy["approved_by"].strip()
        or not isinstance(sample_policy["approval_reference"], str)
        or not sample_policy["approval_reference"].strip()
    ):
        gaps.append("approved_sample_policy_invalid")
    training_hashes = metadata.get("training_data_sha256s")
    if (
        not isinstance(training_hashes, list)
        or not training_hashes
        or any(
            not isinstance(value, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None
            for value in training_hashes
        )
    ):
        gaps.append("model_training_data_hashes_missing")
    elif any(value.lower() == dataset_sha256.lower() for value in training_hashes):
        gaps.append("holdout_dataset_hash_matches_training_data")
    evaluation_start = _timestamp(manifest.get("evaluation_start"), "evaluation_start")
    model_frozen_at_value = metadata.get("model_frozen_at")
    if model_frozen_at_value is None:
        gaps.append("model_frozen_at_missing")
    elif _timestamp(model_frozen_at_value, "model_frozen_at") >= evaluation_start:
        gaps.append("model_not_frozen_before_holdout")
    training_max_value = metadata.get("training_data_max_timestamp")
    if training_max_value is None:
        gaps.append("training_data_max_timestamp_missing")
    elif _timestamp(training_max_value, "training_data_max_timestamp") >= evaluation_start:
        gaps.append("training_data_overlaps_or_follows_holdout")
    return gaps


def _calibration_metrics(
    actual: np.ndarray, estimate: np.ndarray
) -> dict[str, float | None]:
    bins = np.linspace(0.0, 1.0, 11)
    bucket = np.digitize(estimate, bins[1:-1], right=False)
    ece = 0.0
    for index in range(10):
        mask = bucket == index
        if mask.any():
            ece += float(mask.mean() * abs(actual[mask].mean() - estimate[mask].mean()))
    variance = float(np.var(estimate))
    if variance <= 1e-12:
        return {"ece_10bin": round(ece, 6), "slope": None, "intercept": None}
    slope = float(
        np.mean((estimate - estimate.mean()) * (actual - actual.mean())) / variance
    )
    intercept = float(actual.mean() - slope * estimate.mean())
    return {
        "ece_10bin": round(ece, 6),
        "slope": round(slope, 6),
        "intercept": round(intercept, 6),
    }


def _passes_calibration_policy(
    metrics: dict[str, float | None], policy: dict[str, Any]
) -> bool:
    slope = metrics["slope"]
    intercept = metrics["intercept"]
    try:
        return (
            slope is not None
            and intercept is not None
            and metrics["ece_10bin"] is not None
            and metrics["ece_10bin"] <= float(policy["max_ece_10bin"])
            and float(policy["min_slope"]) <= slope <= float(policy["max_slope"])
            and abs(intercept) <= float(policy["max_abs_intercept"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def _passes_sample_policy(
    station_count: int, sample_count: int, policy: dict[str, Any] | None
) -> bool:
    if not isinstance(policy, dict):
        return False
    minimum_stations = policy.get("minimum_stations")
    minimum_samples = policy.get("minimum_samples_per_horizon")
    return (
        type(minimum_stations) is int
        and minimum_stations > 0
        and type(minimum_samples) is int
        and minimum_samples > 0
        and station_count >= minimum_stations
        and sample_count >= minimum_samples
    )


def evaluate_holdout(
    frame: pd.DataFrame,
    predictor: JoblibOccupancyPredictor,
    manifest: dict[str, Any],
    metadata: dict[str, Any],
    *,
    dataset_sha256: str,
    manifest_sha256: str,
) -> dict[str, Any]:
    """Score every eligible origin in the evaluation window for all MVP horizons."""
    evaluation_start = _timestamp(manifest.get("evaluation_start"), "evaluation_start")
    evaluation_end = _timestamp(manifest.get("evaluation_end"), "evaluation_end")
    if evaluation_end <= evaluation_start:
        raise ValueError("manifest evaluation_end must be after evaluation_start")

    observed: dict[int, list[float]] = {horizon: [] for horizon in SUPPORTED_HORIZONS}
    persistence: dict[int, list[float]] = {horizon: [] for horizon in SUPPORTED_HORIZONS}
    predicted: dict[int, list[float]] = {horizon: [] for horizon in SUPPORTED_HORIZONS}
    sampled_entities: dict[int, set[str]] = {horizon: set() for horizon in SUPPORTED_HORIZONS}
    grouped = frame.groupby("entity_id", sort=False)
    for entity_id, station in grouped:
        timestamps = station["timestamp"].tolist()
        values = station["occupancy_ratio"].to_numpy(dtype=float)
        for origin_index in range(LOOKBACK_STEPS - 1, len(station)):
            origin_at = timestamps[origin_index]
            if origin_at < evaluation_start:
                continue
            history = tuple(
                float(value)
                for value in values[origin_index - LOOKBACK_STEPS + 1 : origin_index + 1]
            )
            for horizon in SUPPORTED_HORIZONS:
                target_index = origin_index + horizon // INTERVAL_MIN
                if target_index >= len(station):
                    break
                target_at = timestamps[target_index]
                if target_at > evaluation_end:
                    continue
                target = float(values[target_index])
                baseline = history[-1]
                estimate = predictor.predict(
                    history,
                    horizon,
                    station_id=str(entity_id),
                    forecast_at=target_at.to_pydatetime(),
                )
                if not math.isfinite(estimate):
                    raise ValueError("candidate emitted NaN or infinite occupancy")
                observed[horizon].append(target)
                persistence[horizon].append(baseline)
                predicted[horizon].append(float(np.clip(estimate, 0.0, 1.0)))
                sampled_entities[horizon].add(str(entity_id))

    per_horizon: dict[str, Any] = {}
    all_mae_horizons_pass = True
    all_calibration_horizons_pass = True
    all_sample_horizons_pass = True
    calibration_policy = manifest.get("calibration_policy")
    sample_policy = manifest.get("sample_policy")
    for horizon in SUPPORTED_HORIZONS:
        actual = np.asarray(observed[horizon], dtype=float)
        baseline = np.asarray(persistence[horizon], dtype=float)
        estimate = np.asarray(predicted[horizon], dtype=float)
        if actual.size == 0:
            raise ValueError(f"holdout has no eligible samples for +{horizon} minute horizon")
        baseline_mae = float(np.mean(np.abs(actual - baseline)))
        candidate_mae = float(np.mean(np.abs(actual - estimate)))
        baseline_rmse = float(np.sqrt(np.mean(np.square(actual - baseline))))
        candidate_rmse = float(np.sqrt(np.mean(np.square(actual - estimate))))
        gain = (baseline_mae - candidate_mae) / baseline_mae if baseline_mae > 0 else None
        mae_passed = gain is not None and gain >= MINIMUM_RELATIVE_MAE_GAIN
        candidate_calibration = _calibration_metrics(actual, estimate)
        baseline_calibration = _calibration_metrics(actual, baseline)
        calibration_passed = (
            isinstance(calibration_policy, dict)
            and _passes_calibration_policy(candidate_calibration, calibration_policy)
        )
        sample_passed = _passes_sample_policy(
            len(sampled_entities[horizon]), int(actual.size), sample_policy
        )
        all_mae_horizons_pass &= mae_passed
        all_calibration_horizons_pass &= calibration_passed
        all_sample_horizons_pass &= sample_passed
        per_horizon[str(horizon)] = {
            "sample_count": int(actual.size),
            "station_count": len(sampled_entities[horizon]),
            "persistence_mae": round(baseline_mae, 6),
            "candidate_mae": round(candidate_mae, 6),
            "relative_mae_gain": round(gain, 6) if gain is not None else None,
            "persistence_rmse": round(baseline_rmse, 6),
            "candidate_rmse": round(candidate_rmse, 6),
            "mae_gate_passed": mae_passed,
            "candidate_calibration": candidate_calibration,
            "persistence_calibration": baseline_calibration,
            "calibration_gate_passed": calibration_passed,
            "sample_coverage_gate_passed": sample_passed,
        }

    evidence_gaps = validate_release_evidence(
        manifest,
        metadata,
        dataset_sha256=dataset_sha256,
        manifest_sha256=manifest_sha256,
    )
    data_domain = manifest.get("data_domain")
    if data_domain != CUSTOMER_DOMAIN:
        evidence_gaps.append("customer_release_requires_hcmc_operational_holdout")
    quality_passed = (
        all_mae_horizons_pass
        and all_calibration_horizons_pass
        and all_sample_horizons_pass
    )
    deployment_eligible = quality_passed and not evidence_gaps
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "evaluation_type": "independent_temporal_holdout",
        "holdout_id": manifest.get("holdout_id"),
        "holdout_status": manifest.get("holdout_status"),
        "source_record": manifest.get("source_record"),
        "timezone": manifest.get("timezone"),
        "evaluation_start": _timestamp(
            manifest.get("evaluation_start"), "evaluation_start"
        ).isoformat(),
        "evaluation_end": _timestamp(
            manifest.get("evaluation_end"), "evaluation_end"
        ).isoformat(),
        "independence_attestation": "operator_asserted_and_requires_review",
        "data_domain": data_domain,
        "dataset_sha256": dataset_sha256,
        "holdout_manifest_sha256": manifest_sha256,
        "model_version": metadata.get("model_version") or metadata.get("release_id"),
        "model_frozen_at": metadata.get("model_frozen_at"),
        "training_data_max_timestamp": metadata.get("training_data_max_timestamp"),
        "training_data_sha256s": metadata.get("training_data_sha256s"),
        "serving_contract_version": metadata.get("format_version"),
        "horizons_min": list(SUPPORTED_HORIZONS),
        "required_relative_mae_gain": MINIMUM_RELATIVE_MAE_GAIN,
        "approved_calibration_policy": calibration_policy,
        "mae_gate_passed": all_mae_horizons_pass,
        "calibration_gate_passed": all_calibration_horizons_pass,
        "sample_coverage_gate_passed": all_sample_horizons_pass,
        "approved_sample_policy": sample_policy,
        "quality_gate_passed": quality_passed,
        "evidence_gaps": evidence_gaps,
        "deployment_eligible": deployment_eligible,
        "promotion_performed": False,
        "per_horizon": per_horizon,
    }


def run_evaluation(
    dataset_path: Path,
    manifest_path: Path,
    artifact_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("holdout manifest must be a JSON object")
    frame = _load_holdout(dataset_path, manifest)
    paths = (
        artifact_dir / "occupancy_model.joblib",
        artifact_dir / "occupancy_preprocessor.joblib",
        artifact_dir / "occupancy_model_meta.json",
    )
    predictor, metadata = JoblibOccupancyPredictor.from_files(
        *paths, require_serving_ready=False
    )
    report = evaluate_holdout(
        frame,
        predictor,
        manifest,
        metadata,
        dataset_sha256=sha256_file(dataset_path),
        manifest_sha256=sha256_file(manifest_path),
    )
    report["artifact_sha256s"] = {
        path.name: sha256_file(path) for path in paths[:2]
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, required=True, help="separate holdout Parquet")
    parser.add_argument(
        "--manifest", type=Path, required=True, help="operator-reviewed holdout manifest"
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_evaluation(args.dataset, args.manifest, args.artifact_dir, args.report)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["deployment_eligible"] else 2


if __name__ == "__main__":
    sys.exit(main())
