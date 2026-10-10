"""Strict loader for Phase 04 model release bundles.

Loading is opt-in and fail-closed: an incomplete or incompatible artifact never
changes a journey recommendation.  The forecast service then uses its existing
persistence fallback and exposes the reason through /model/status.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.domain.forecasting import OccupancyPredictor
from backend.app.domain.model_contract import CONTRACT_VERSION, SUPPORTED_HORIZONS_MIN
from shared.occupancy_contract import LAG_FEATURES
from shared.seasonal_profile import seasonal_prior

SUPPORTED_HORIZONS = SUPPORTED_HORIZONS_MIN
SUPPORTED_FEATURES = LAG_FEATURES


class ArtifactValidationError(ValueError):
    """An artifact exists but is not safe for this serving runtime."""


class JoblibOccupancyPredictor(OccupancyPredictor):
    def __init__(
        self,
        models: dict[int, Any],
        feature_names_by_horizon: dict[int, tuple[str, ...]],
        seasonal_profile: dict[str, Any] | None = None,
        prediction_mode: str = "direct",
    ) -> None:
        self._models = models
        self._feature_names_by_horizon = feature_names_by_horizon
        self._seasonal_profile = seasonal_profile
        self._prediction_mode = prediction_mode

    @classmethod
    def from_files(
        cls,
        model_path: Path,
        preprocessor_path: Path,
        metadata_path: Path,
        *,
        require_serving_ready: bool = True,
    ) -> tuple[JoblibOccupancyPredictor, dict[str, Any]]:
        try:
            import joblib
        except ImportError as exc:
            raise ArtifactValidationError(
                "joblib is unavailable; install backend requirements with ML serving extras"
            ) from exc
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            model_bundle = joblib.load(model_path)
            preprocessor = joblib.load(preprocessor_path)
        except Exception as exc:
            raise ArtifactValidationError("cannot read model release bundle") from exc
        if not isinstance(model_bundle, dict) or not isinstance(preprocessor, dict):
            raise ArtifactValidationError("model and preprocessor artifacts must be dictionaries")
        if not isinstance(metadata, dict):
            raise ArtifactValidationError("model metadata must be a JSON object")
        for payload in (metadata, model_bundle, preprocessor):
            if payload.get("format_version") != CONTRACT_VERSION:
                raise ArtifactValidationError("model release has an incompatible contract version")
        if require_serving_ready and metadata.get("serving_ready") is not True:
            raise ArtifactValidationError("model metadata is not approved for serving")
        model_version = metadata.get("model_version") or metadata.get("release_id")
        if (
            not isinstance(model_version, str)
            or not model_version.strip()
            or len(model_version.strip()) > 128
            or any(character.isspace() for character in model_version.strip())
        ):
            raise ArtifactValidationError(
                "model metadata must declare a non-empty model_version or release_id"
            )
        metadata["model_version"] = model_version.strip()
        if require_serving_ready:
            cls._validate_evaluation_evidence(
                model_path, preprocessor_path, metadata_path, metadata
            )
        prediction_mode = str(metadata.get("prediction_mode", "direct"))
        if prediction_mode not in {"direct", "residual_to_persistence"}:
            raise ArtifactValidationError("model release has an unsupported prediction mode")
        for payload in (model_bundle, preprocessor):
            declared_mode = str(payload.get("prediction_mode", "direct"))
            if declared_mode != prediction_mode:
                raise ArtifactValidationError(
                    "model prediction mode does not match release metadata"
                )
        declared_horizons = tuple(metadata.get("horizons_min", ()))
        if declared_horizons != SUPPORTED_HORIZONS:
            raise ArtifactValidationError(
                "model release must provide every +5 to +30 minute horizon"
            )
        raw_feature_names = metadata.get("feature_names_by_horizon")
        if not isinstance(raw_feature_names, dict):
            raise ArtifactValidationError("model release has no per-horizon feature contract")
        if model_bundle.get("feature_names_by_horizon") != raw_feature_names:
            raise ArtifactValidationError("model feature names do not match metadata")
        if preprocessor.get("feature_names_by_horizon") != raw_feature_names:
            raise ArtifactValidationError("preprocessor feature names do not match metadata")
        raw_models = model_bundle.get("models")
        if not isinstance(raw_models, dict):
            raise ArtifactValidationError("model bundle has no horizon models")
        models: dict[int, Any] = {}
        feature_names_by_horizon: dict[int, tuple[str, ...]] = {}
        for horizon in SUPPORTED_HORIZONS:
            model = raw_models.get(horizon)
            if model is None or not callable(getattr(model, "predict", None)):
                raise ArtifactValidationError(f"model bundle misses usable {horizon}-minute model")
            names = tuple(raw_feature_names.get(str(horizon), ()))
            seasonal_name = f"seasonal_prior_t_plus_{horizon}m"
            if names not in (SUPPORTED_FEATURES, (*SUPPORTED_FEATURES, seasonal_name)):
                raise ArtifactValidationError(
                    f"unsupported feature contract for {horizon}-minute model"
                )
            models[horizon] = model
            feature_names_by_horizon[horizon] = names
        uses_seasonal = any(
            len(names) > len(SUPPORTED_FEATURES) for names in feature_names_by_horizon.values()
        )
        seasonal_profile = preprocessor.get("seasonal_profile")
        if uses_seasonal and not isinstance(seasonal_profile, dict):
            raise ArtifactValidationError("seasonal model release has no frozen seasonal profile")
        if not uses_seasonal:
            seasonal_profile = None
        return cls(models, feature_names_by_horizon, seasonal_profile, prediction_mode), metadata

    @staticmethod
    def _validate_evaluation_evidence(
        model_path: Path,
        preprocessor_path: Path,
        metadata_path: Path,
        metadata: dict[str, Any],
    ) -> None:
        report_hash = metadata.get("evaluation_report_sha256")
        if not isinstance(report_hash, str) or re.fullmatch(r"[0-9a-f]{64}", report_hash) is None:
            raise ArtifactValidationError("serving bundle has no valid evaluation report hash")
        report_path = metadata_path.with_name("occupancy_evaluation_report.json")
        try:
            report_bytes = report_path.read_bytes()
            report = json.loads(report_bytes)
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactValidationError(
                "serving bundle evaluation report is unavailable"
            ) from exc
        if hashlib.sha256(report_bytes).hexdigest() != report_hash:
            raise ArtifactValidationError("serving bundle evaluation report hash does not match")
        if not isinstance(report, dict):
            raise ArtifactValidationError("serving bundle evaluation report is invalid")

        def parse_report_time(field: str) -> datetime:
            value = report.get(field)
            if not isinstance(value, str):
                raise ArtifactValidationError(
                    f"evaluation report is missing {field} provenance"
                )
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ArtifactValidationError(
                    f"evaluation report has invalid {field} provenance"
                ) from exc
            if parsed.tzinfo is None:
                raise ArtifactValidationError(
                    f"evaluation report {field} must include a timezone"
                )
            return parsed

        evaluation_start = parse_report_time("evaluation_start")
        evaluation_end = parse_report_time("evaluation_end")
        model_frozen_at = parse_report_time("model_frozen_at")
        training_max_at = parse_report_time("training_data_max_timestamp")
        if (
            evaluation_end <= evaluation_start
            or model_frozen_at >= evaluation_start
            or training_max_at >= evaluation_start
            or training_max_at > model_frozen_at
            or report.get("model_frozen_at") != metadata.get("model_frozen_at")
            or report.get("training_data_max_timestamp")
            != metadata.get("training_data_max_timestamp")
        ):
            raise ArtifactValidationError("evaluation report temporal provenance is invalid")
        report_training_hashes = report.get("training_data_sha256s")
        metadata_training_hashes = metadata.get("training_data_sha256s")
        if (
            not isinstance(report_training_hashes, list)
            or not isinstance(metadata_training_hashes, list)
            or not report_training_hashes
            or not metadata_training_hashes
            or any(
                not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None
                for value in report_training_hashes
            )
            or any(
                not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None
                for value in metadata_training_hashes
            )
            or sorted(value.lower() for value in report_training_hashes)
            != sorted(value.lower() for value in metadata_training_hashes)
        ):
            raise ArtifactValidationError(
                "evaluation report training data provenance does not match"
            )
        dataset_hash = report.get("dataset_sha256")
        manifest_hash = report.get("holdout_manifest_sha256")
        if (
            not isinstance(dataset_hash, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", dataset_hash) is None
            or not isinstance(manifest_hash, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", manifest_hash) is None
            or any(value.lower() == dataset_hash.lower() for value in report_training_hashes)
        ):
            raise ArtifactValidationError(
                "evaluation report holdout dataset or manifest provenance is invalid"
            )
        if (
            report.get("evaluation_type") != "independent_temporal_holdout"
            or report.get("holdout_status") != "independent_untouched"
            or report.get("data_domain") != "hcmc_operational"
            or not isinstance(report.get("holdout_id"), str)
            or not report["holdout_id"].strip()
            or not isinstance(report.get("source_record"), str)
            or not report["source_record"].strip()
            or not isinstance(report.get("timezone"), str)
            or not report["timezone"].strip()
            or report.get("model_version") != metadata["model_version"]
            or report.get("serving_contract_version") != CONTRACT_VERSION
            or report.get("quality_gate_passed") is not True
            or report.get("deployment_eligible") is not True
            or report.get("evidence_gaps") != []
            or report.get("promotion_performed") is not False
        ):
            raise ArtifactValidationError(
                "serving bundle evaluation report did not pass release gates"
            )
        per_horizon = report.get("per_horizon")
        if not isinstance(per_horizon, dict):
            raise ArtifactValidationError("evaluation report has no per-horizon gate results")
        if report.get("required_relative_mae_gain") != 0.05:
            raise ArtifactValidationError("evaluation report has an incompatible MAE release gate")
        calibration_policy = report.get("approved_calibration_policy")
        sample_policy = report.get("approved_sample_policy")
        if not isinstance(calibration_policy, dict) or not isinstance(sample_policy, dict):
            raise ArtifactValidationError("evaluation report has no approved release policies")
        for policy in (calibration_policy, sample_policy):
            if not all(
                isinstance(policy.get(key), str) and policy[key].strip()
                for key in ("approved_by", "approval_reference")
            ):
                raise ArtifactValidationError("evaluation report release policies are unapproved")
        try:
            max_ece = float(calibration_policy["max_ece_10bin"])
            min_slope = float(calibration_policy["min_slope"])
            max_slope = float(calibration_policy["max_slope"])
            max_intercept = float(calibration_policy["max_abs_intercept"])
            min_stations = sample_policy["minimum_stations"]
            min_samples = sample_policy["minimum_samples_per_horizon"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactValidationError("evaluation report release policies are invalid") from exc
        if (
            not all(
                math.isfinite(value)
                for value in (max_ece, min_slope, max_slope, max_intercept)
            )
            or not 0 <= max_ece <= 1
            or not 0 <= min_slope <= max_slope
            or not 0 <= max_intercept <= 1
            or type(min_stations) is not int
            or min_stations < 1
            or type(min_samples) is not int
            or min_samples < 1
        ):
            raise ArtifactValidationError("evaluation report release policies are invalid")
        if set(per_horizon) != {str(horizon) for horizon in SUPPORTED_HORIZONS}:
            raise ArtifactValidationError(
                "evaluation report horizons do not match serving contract"
            )
        for horizon in SUPPORTED_HORIZONS:
            result = per_horizon.get(str(horizon))
            relative_gain = (
                result.get("relative_mae_gain") if isinstance(result, dict) else None
            )
            if (
                not isinstance(result, dict)
                or type(result.get("sample_count")) is not int
                or result["sample_count"] <= 0
                or result["sample_count"] < min_samples
                or type(result.get("station_count")) is not int
                or result["station_count"] < min_stations
                or result.get("mae_gate_passed") is not True
                or result.get("calibration_gate_passed") is not True
                or result.get("sample_coverage_gate_passed") is not True
                or type(relative_gain) not in (int, float)
                or not math.isfinite(relative_gain)
                or not 0.05 <= relative_gain <= 1.0
                or not isinstance(result.get("candidate_calibration"), dict)
            ):
                raise ArtifactValidationError(
                    f"evaluation report did not pass the {horizon}-minute horizon"
                )
            calibration = result["candidate_calibration"]
            ece = calibration.get("ece_10bin")
            slope = calibration.get("slope")
            intercept = calibration.get("intercept")
            if (
                type(ece) not in (int, float)
                or type(slope) not in (int, float)
                or type(intercept) not in (int, float)
                or not all(math.isfinite(value) for value in (ece, slope, intercept))
                or ece > max_ece
                or not min_slope <= slope <= max_slope
                or abs(intercept) > max_intercept
            ):
                raise ArtifactValidationError(
                    f"evaluation report calibration failed at {horizon} minutes"
                )
        artifact_hashes = report.get("artifact_sha256s")
        if not isinstance(artifact_hashes, dict):
            raise ArtifactValidationError("evaluation report has no candidate artifact hashes")
        for artifact_path in (model_path, preprocessor_path):
            try:
                expected = artifact_hashes[artifact_path.name]
            except KeyError as exc:
                raise ArtifactValidationError(
                    "evaluation report does not identify the serving artifacts"
                ) from exc
            if not isinstance(expected, str) or hashlib.sha256(
                artifact_path.read_bytes()
            ).hexdigest() != expected:
                raise ArtifactValidationError(
                    "serving artifact differs from the evaluated candidate"
                )

    def predict(
        self,
        occupancy_history: tuple[float, ...],
        horizon_min: int,
        *,
        station_id: str | None = None,
        forecast_at: datetime | None = None,
    ) -> float:
        if horizon_min not in self._models:
            raise ValueError(f"unsupported model horizon: {horizon_min}")
        feature_names = self._feature_names_by_horizon[horizon_min]
        if len(occupancy_history) != len(SUPPORTED_FEATURES):
            raise ValueError("occupancy history does not match model feature contract")
        values = {
            name: value
            for name, value in zip(SUPPORTED_FEATURES, reversed(occupancy_history), strict=True)
        }
        seasonal_name = f"seasonal_prior_t_plus_{horizon_min}m"
        if seasonal_name in feature_names:
            if station_id is None or forecast_at is None:
                raise ValueError("seasonal model requires station ID and forecast timestamp")
            values[seasonal_name] = self._seasonal_prior(station_id, forecast_at, horizon_min)
        row = [[values[name] for name in feature_names]]
        prediction = self._models[horizon_min].predict(row)
        raw_prediction = float(prediction[0])
        if self._prediction_mode == "residual_to_persistence":
            return occupancy_history[-1] + raw_prediction
        return raw_prediction

    def _seasonal_prior(self, station_id: str, forecast_at: datetime, horizon_min: int) -> float:
        assert self._seasonal_profile is not None
        return seasonal_prior(self._seasonal_profile, station_id, forecast_at, horizon_min)
