"""Strict loader for Phase 04 model release bundles.

Loading is opt-in and fail-closed: an incomplete or incompatible artifact never
changes a journey recommendation.  The forecast service then uses its existing
persistence fallback and exposes the reason through /model/status.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.domain.forecasting import OccupancyPredictor
from shared.seasonal_profile import seasonal_prior

CONTRACT_VERSION = "2.1"
SUPPORTED_HORIZONS = tuple(range(5, 61, 5))
SUPPORTED_FEATURES = tuple(f"lag_{step}" for step in range(1, 13))


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
        cls, model_path: Path, preprocessor_path: Path, metadata_path: Path
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
        for payload in (metadata, model_bundle, preprocessor):
            if payload.get("format_version") != CONTRACT_VERSION:
                raise ArtifactValidationError("model release has an incompatible contract version")
        if metadata.get("serving_ready") is not True:
            raise ArtifactValidationError("model metadata is not approved for serving")
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
                "model release must provide every +5 to +60 minute horizon"
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
