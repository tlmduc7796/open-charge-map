"""Serving contract and loader for the Phase 04 occupancy model artifacts.

This module is the single boundary between the ML work (``ml/``) and the backend. The ML
owner only has to produce the three artifacts described in ``docs/ML_INTEGRATION.md`` and
check them with ``scripts/validate_model_artifacts.py``; no backend code changes needed.

Artifacts (paths come from ``MODEL_ARTIFACT_PATH`` / ``MODEL_PREPROCESSOR_PATH`` /
``MODEL_META_PATH``):

* ``occupancy_model.joblib``: a mapping ``{horizon_min: estimator}`` with one direct model
  per horizon (+5, +10, +15 min). ``estimator.predict(rows)`` takes a 2-D list and returns
  the future ``occupancy_ratio`` for each row.
* ``occupancy_preprocessor.joblib``: an object with ``transform(rows)`` fitted on the train
  split only, or ``None`` when no scaling is used.
* ``occupancy_model_meta.json``: validated by :class:`OccupancyModelMeta`.

Feature rows are built by name, in the order ``meta.features`` lists them:

* ``lag_12`` ... ``lag_1``: occupancy ratios, ``lag_12`` oldest, ``lag_1`` newest
  (5-minute steps). All twelve are required.
* ``hour_sin``, ``hour_cos``: ``sin/cos(2*pi*h/24)`` with ``h = hour + minute/60`` of the
  *newest observation* in UTC+7 wall-clock time.
* ``dow_sin``, ``dow_cos``: ``sin/cos(2*pi*d/7)`` with ``d = weekday`` (Monday = 0), same
  clock.

Station/entity IDs, queue and wait values are deliberately not available as features.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import joblib
from pydantic import Field, ValidationError, model_validator

from backend.app.config import Settings
from backend.app.domain.models import DomainModel

logger = logging.getLogger("smart_ev.model")

SUPPORTED_HORIZONS_MIN = (5, 10, 15)
LOOKBACK_STEPS = 12
RESOLUTION_MIN = 5
LAG_FEATURES = tuple(f"lag_{step}" for step in range(LOOKBACK_STEPS, 0, -1))
TIME_FEATURES = ("hour_sin", "hour_cos", "dow_sin", "dow_cos")
SUPPORTED_FEATURES = frozenset((*LAG_FEATURES, *TIME_FEATURES))
# Vietnam has no DST, so a fixed offset avoids needing the tzdata package on Windows.
LOCAL_TZ = timezone(timedelta(hours=7))


class ModelContractError(RuntimeError):
    """Artifacts exist but do not satisfy the serving contract."""


class OccupancyModelMeta(DomainModel):
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    task: Literal["occupancy_forecasting"]
    training_dataset: str = Field(min_length=1)
    training_level: Literal["station", "zone"]
    temporal_resolution_min: int
    lookback_steps: int
    forecast_steps: int
    features: tuple[str, ...]
    target: Literal["occupancy_ratio"]
    metrics: dict[str, Any]
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_serving_contract(self) -> OccupancyModelMeta:
        if self.temporal_resolution_min != RESOLUTION_MIN:
            raise ValueError(f"temporal_resolution_min must be {RESOLUTION_MIN}")
        if self.lookback_steps != LOOKBACK_STEPS:
            raise ValueError(f"lookback_steps must be {LOOKBACK_STEPS}")
        if self.forecast_steps != len(SUPPORTED_HORIZONS_MIN):
            raise ValueError(
                f"forecast_steps must be {len(SUPPORTED_HORIZONS_MIN)} "
                f"(direct models for +{', +'.join(map(str, SUPPORTED_HORIZONS_MIN))} min)"
            )
        if len(set(self.features)) != len(self.features):
            raise ValueError("features must not contain duplicates")
        unknown = sorted(set(self.features) - SUPPORTED_FEATURES)
        if unknown:
            raise ValueError(
                f"unsupported features {unknown}; allowed: {sorted(SUPPORTED_FEATURES)}"
            )
        missing_lags = [name for name in LAG_FEATURES if name not in self.features]
        if missing_lags:
            raise ValueError(f"features must include all lag features; missing {missing_lags}")
        return self

    @property
    def uses_timestamp(self) -> bool:
        return any(name in TIME_FEATURES for name in self.features)


def build_feature_row(
    feature_names: tuple[str, ...],
    occupancy_history: tuple[float, ...],
    observed_at: datetime | None,
) -> list[float]:
    """Build one model input row. ``occupancy_history`` is oldest first."""
    if len(occupancy_history) != LOOKBACK_STEPS:
        raise ValueError(f"occupancy_history must contain {LOOKBACK_STEPS} values")
    values: dict[str, float] = {
        name: float(value) for name, value in zip(LAG_FEATURES, occupancy_history, strict=True)
    }
    if any(name in TIME_FEATURES for name in feature_names):
        if observed_at is None or observed_at.tzinfo is None:
            raise ValueError("a timezone-aware observed_at is required for time features")
        local = observed_at.astimezone(LOCAL_TZ)
        hour_angle = 2 * math.pi * (local.hour + local.minute / 60) / 24
        dow_angle = 2 * math.pi * local.weekday() / 7
        values.update(
            hour_sin=math.sin(hour_angle),
            hour_cos=math.cos(hour_angle),
            dow_sin=math.sin(dow_angle),
            dow_cos=math.cos(dow_angle),
        )
    return [values[name] for name in feature_names]


class JoblibOccupancyPredictor:
    """Implements ``OccupancyPredictor`` on top of per-horizon estimators."""

    def __init__(
        self,
        models: dict[int, Any],
        preprocessor: Any | None,
        meta: OccupancyModelMeta,
    ) -> None:
        missing = [h for h in SUPPORTED_HORIZONS_MIN if h not in models]
        if missing:
            raise ModelContractError(f"model artifact has no estimator for horizons {missing}")
        for horizon in SUPPORTED_HORIZONS_MIN:
            if not callable(getattr(models[horizon], "predict", None)):
                raise ModelContractError(f"estimator for +{horizon} min has no predict() method")
        if preprocessor is not None and not callable(getattr(preprocessor, "transform", None)):
            raise ModelContractError("preprocessor must have a transform() method (or be None)")
        self._models = models
        self._preprocessor = preprocessor
        self.meta = meta
        self.uses_timestamp = meta.uses_timestamp

    def predict(
        self,
        occupancy_history: tuple[float, ...],
        horizon_min: int,
        observed_at: datetime | None = None,
    ) -> float:
        if horizon_min not in self._models:
            raise ValueError(f"unsupported horizon: {horizon_min}")
        rows = [build_feature_row(self.meta.features, occupancy_history, observed_at)]
        if self._preprocessor is not None:
            rows = self._preprocessor.transform(rows)
        prediction = float(self._models[horizon_min].predict(rows)[0])
        if not math.isfinite(prediction):
            raise ValueError("model returned a non-finite prediction")
        return prediction


def load_meta(path: Path) -> OccupancyModelMeta:
    try:
        with path.open(encoding="utf-8") as source:
            return OccupancyModelMeta.model_validate(json.load(source))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise ModelContractError(f"invalid model metadata {path.name}: {exc}") from exc


_PROBE_HISTORIES = (
    (0.0,) * LOOKBACK_STEPS,
    (1.0,) * LOOKBACK_STEPS,
    tuple(step / (LOOKBACK_STEPS - 1) for step in range(LOOKBACK_STEPS)),
)
_PROBE_TIME = datetime(2026, 9, 30, 6, 0, tzinfo=LOCAL_TZ)


def smoke_check(predictor: JoblibOccupancyPredictor) -> list[str]:
    """Run probe inferences. Raises on failure; returns non-fatal warnings."""
    warnings: list[str] = []
    for horizon in SUPPORTED_HORIZONS_MIN:
        for history in _PROBE_HISTORIES:
            try:
                value = predictor.predict(history, horizon, observed_at=_PROBE_TIME)
            except Exception as exc:
                raise ModelContractError(
                    f"inference failed for +{horizon} min: {type(exc).__name__}: {exc}"
                ) from exc
            if not 0.0 <= value <= 1.0:
                warnings.append(
                    f"+{horizon} min returned {value:.4f} outside [0, 1] "
                    "(the backend clamps it, but check the training target)"
                )
    return list(dict.fromkeys(warnings))


def load_predictor_strict(
    model_path: Path, preprocessor_path: Path, meta_path: Path
) -> JoblibOccupancyPredictor:
    """Load and smoke-test artifacts; raise :class:`ModelContractError` with the reason."""
    meta = load_meta(meta_path)
    try:
        models = joblib.load(model_path)
        preprocessor = joblib.load(preprocessor_path)
    except Exception as exc:  # unpickling can raise almost anything (e.g. missing xgboost)
        raise ModelContractError(
            f"cannot unpickle artifacts: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(models, dict):
        raise ModelContractError("model artifact must be a {horizon_min: estimator} mapping")
    predictor = JoblibOccupancyPredictor(models, preprocessor, meta)
    for warning in smoke_check(predictor):
        logger.warning("occupancy model warning: %s", warning)
    return predictor


@dataclass(frozen=True)
class ModelLoadResult:
    """Outcome of the startup load. ``absent`` is normal before Phase 04 is delivered."""

    state: Literal["absent", "loaded", "invalid"]
    predictor: JoblibOccupancyPredictor | None = None
    error: str | None = None


def load_occupancy_model(settings: Settings) -> ModelLoadResult:
    """Never raises: any problem keeps the declared persistence fallback."""
    paths = (
        settings.model_artifact_path,
        settings.model_preprocessor_path,
        settings.model_meta_path,
    )
    if not all(path.is_file() for path in paths):
        logger.info("occupancy artifacts not complete; using persistence fallback")
        return ModelLoadResult("absent")
    try:
        predictor = load_predictor_strict(*paths)
    except ModelContractError as exc:
        logger.error("occupancy model rejected; using persistence fallback: %s", exc)
        return ModelLoadResult("invalid", error=str(exc))
    logger.info(
        "occupancy model loaded name=%s version=%s",
        predictor.meta.model_name,
        predictor.meta.model_version,
    )
    return ModelLoadResult("loaded", predictor=predictor)


class PersistenceEstimator:
    """Reference estimator: predicts the newest lag. Used by the example artifacts."""

    def __init__(self, newest_lag_index: int) -> None:
        self.newest_lag_index = newest_lag_index

    def predict(self, rows: list[list[float]]) -> list[float]:
        return [row[self.newest_lag_index] for row in rows]
