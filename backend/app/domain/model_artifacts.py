"""Strict loader for Phase 04 model release bundles.

Loading is opt-in and fail-closed: an incomplete or incompatible artifact never
changes a journey recommendation.  The forecast service then uses its existing
persistence fallback and exposes the reason through /model/status.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.domain.forecasting import OccupancyPredictor

CONTRACT_VERSION = "1.0"
SUPPORTED_HORIZONS = (5, 10, 15)
SUPPORTED_FEATURES = tuple(f"lag_{step}" for step in range(1, 13))


class ArtifactValidationError(ValueError):
    """An artifact exists but is not safe for this serving runtime."""


class JoblibOccupancyPredictor(OccupancyPredictor):
    def __init__(self, models: dict[int, Any], feature_names: tuple[str, ...]) -> None:
        self._models = models
        self._feature_names = feature_names

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
        feature_names = tuple(metadata.get("feature_names", ()))
        if feature_names != SUPPORTED_FEATURES:
            raise ArtifactValidationError(
                "backend currently supports only the baseline lag_1..lag_12 profile"
            )
        if model_bundle.get("feature_names") != list(feature_names):
            raise ArtifactValidationError("model feature names do not match metadata")
        if preprocessor.get("feature_names") != list(feature_names):
            raise ArtifactValidationError("preprocessor feature names do not match metadata")
        raw_models = model_bundle.get("models")
        if not isinstance(raw_models, dict):
            raise ArtifactValidationError("model bundle has no horizon models")
        models: dict[int, Any] = {}
        for horizon in SUPPORTED_HORIZONS:
            model = raw_models.get(horizon)
            if model is None or not callable(getattr(model, "predict", None)):
                raise ArtifactValidationError(f"model bundle misses usable {horizon}-minute model")
            models[horizon] = model
        return cls(models, feature_names), metadata

    def predict(self, occupancy_history: tuple[float, ...], horizon_min: int) -> float:
        if horizon_min not in self._models:
            raise ValueError(f"unsupported model horizon: {horizon_min}")
        if len(occupancy_history) != len(self._feature_names):
            raise ValueError("occupancy history does not match model feature contract")
        # lag_1 is the newest known occupancy; the forecast service history is
        # chronological, so reverse it before passing the model's feature row.
        row = [list(reversed(occupancy_history))]
        prediction = self._models[horizon_min].predict(row)
        return float(prediction[0])
