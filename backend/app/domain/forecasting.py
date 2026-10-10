"""Occupancy inference interface with an explicit persistence fallback."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from backend.app.domain.model_contract import SUPPORTED_HORIZONS_MIN
from backend.app.domain.models import OccupancyForecastResult, StationStatus


class OccupancyPredictor(Protocol):
    """Adapter contract for the future Phase 04 model artifact."""

    def predict(
        self,
        occupancy_history: tuple[float, ...],
        horizon_min: int,
        *,
        station_id: str | None = None,
        forecast_at: object | None = None,
    ) -> float: ...


class OccupancyForecastCache(Protocol):
    """Small cache contract; cache failures must never prevent forecasting."""

    def get(self, key: str) -> OccupancyForecastResult | None: ...

    def set(self, key: str, result: OccupancyForecastResult, ttl_s: int) -> None: ...


class OccupancyForecastService:
    def __init__(
        self,
        predictor: OccupancyPredictor | None = None,
        *,
        lookback_steps: int = 12,
        model_horizons_min: tuple[int, ...] = SUPPORTED_HORIZONS_MIN,
        require_observed_history: bool = False,
        model_version: str | None = None,
        on_forecast: Callable[[OccupancyForecastResult], None] | None = None,
        cache: OccupancyForecastCache | None = None,
        cache_namespace: str = "default",
        cache_ttl_s: int = 300,
    ) -> None:
        if (
            lookback_steps <= 0
            or not model_horizons_min
            or any(value <= 0 for value in model_horizons_min)
        ):
            raise ValueError("forecast lookback and horizon must be positive")
        self._predictor = predictor
        self._lookback_steps = lookback_steps
        self._require_observed_history = require_observed_history
        self._model_version = model_version
        self._on_forecast = on_forecast
        if cache_ttl_s <= 0:
            raise ValueError("cache_ttl_s must be positive")
        self._cache = cache
        self._cache_namespace = cache_namespace
        self._cache_ttl_s = cache_ttl_s
        self._model_horizons_min = tuple(sorted(set(model_horizons_min)))
        self._max_model_horizon_min = self._model_horizons_min[-1]

    @property
    def model_loaded(self) -> bool:
        return self._predictor is not None

    @property
    def lookback_steps(self) -> int:
        return self._lookback_steps

    def forecast_occupancy(
        self,
        status: StationStatus,
        *,
        horizon_min: int,
        occupancy_history: tuple[float, ...] | None = None,
        forecast_at: datetime | None = None,
    ) -> OccupancyForecastResult:
        target_at = forecast_at or status.timestamp + timedelta(minutes=horizon_min)
        if target_at.tzinfo is None:
            raise ValueError("forecast target must include a timezone")
        cache_key = self._cache_key(status, horizon_min, occupancy_history, target_at)
        if self._cache is not None:
            try:
                cached = self._cache.get(cache_key)
            except Exception:
                cached = None
            if (
                cached is not None
                and cached.prediction_source == "model"
                and self._model_version is not None
                and cached.model_version != self._model_version
            ):
                cached = None
            if cached is not None:
                if self._on_forecast is not None:
                    self._on_forecast(cached)
                return cached
        result = self._forecast_occupancy(
            status,
            horizon_min=horizon_min,
            occupancy_history=occupancy_history,
            target_at=target_at,
        )
        if result.prediction_source == "model" and self._model_version is not None:
            result = result.model_copy(update={"model_version": self._model_version})
        if self._on_forecast is not None:
            self._on_forecast(result)
        if self._cache is not None and result.prediction_source == "model":
            try:
                self._cache.set(cache_key, result, self._cache_ttl_s)
            except Exception:
                pass
        return result

    def _cache_key(
        self,
        status: StationStatus,
        horizon_min: int,
        occupancy_history: tuple[float, ...] | None,
        target_at: datetime,
    ) -> str:
        payload = {
            "namespace": self._cache_namespace,
            "model_version": self._model_version,
            "status": status.model_dump(mode="json"),
            "horizon_min": horizon_min,
            "history": occupancy_history,
            "target_at": target_at.replace(second=0, microsecond=0).isoformat(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return f"smart-ev:occupancy:v1:{digest}"

    def _forecast_occupancy(
        self,
        status: StationStatus,
        *,
        horizon_min: int,
        occupancy_history: tuple[float, ...] | None = None,
        target_at: datetime,
    ) -> OccupancyForecastResult:
        if horizon_min <= 0:
            raise ValueError("horizon_min must be positive")

        used_horizon = self._aligned_horizon(horizon_min)
        flags: list[str] = []
        if status.unknown_ports:
            flags.append("UNKNOWN_PORTS_PRESENT")
        if horizon_min > self._max_model_horizon_min:
            flags.append("BEYOND_MODEL_HORIZON")
        elif used_horizon != horizon_min:
            flags.append("HORIZON_ALIGNED_TO_MODEL")

        if status.operational_ports == 0:
            if status.unknown_ports:
                flags.append("UNKNOWN_PORT_STATUS")
            else:
                flags.append("STATION_OFFLINE")
            flags.append("PERSISTENCE_FALLBACK")
            return OccupancyForecastResult(
                station_id=status.station_id,
                generated_at=datetime.now(UTC),
                target_at=target_at,
                requested_horizon_min=horizon_min,
                used_horizon_min=used_horizon,
                predicted_occupancy_ratio=None,
                predicted_occupied_ports=0,
                operational_ports=0,
                prediction_source="persistence",
                flags=tuple(flags),
            )

        if self._require_observed_history and occupancy_history is None:
            flags.extend(("OBSERVED_HISTORY_UNAVAILABLE", "PERSISTENCE_FALLBACK"))
            return self._result(
                status,
                horizon_min,
                used_horizon,
                status.occupancy_ratio,
                "persistence",
                flags,
                target_at=target_at,
            )
        if occupancy_history is None:
            flags.append("SYNTHETIC_HISTORY")

        history = self._prepare_history(status, occupancy_history)
        if self._predictor is not None and horizon_min <= self._max_model_horizon_min:
            try:
                raw_prediction = float(
                    self._predict(
                        history,
                        used_horizon,
                        status.station_id,
                        target_at,
                    )
                )
                if not math.isfinite(raw_prediction):
                    raise ValueError("model prediction must be finite")
                prediction = min(1.0, max(0.0, float(raw_prediction)))
                if prediction != raw_prediction:
                    flags.append("PREDICTION_CLAMPED")
                return self._result(
                    status,
                    horizon_min,
                    used_horizon,
                    prediction,
                    "model",
                    flags,
                    target_at=target_at,
                )
            except Exception:  # Model adapter errors must degrade to the declared fallback.
                flags.append("MODEL_INFERENCE_FAILED")

        flags.append("PERSISTENCE_FALLBACK")
        return self._result(
            status,
            horizon_min,
            used_horizon,
            history[-1],
            "persistence",
            flags,
            target_at=target_at,
        )

    def _aligned_horizon(self, requested_horizon_min: int) -> int:
        for horizon in self._model_horizons_min:
            if requested_horizon_min <= horizon:
                return horizon
        return self._max_model_horizon_min

    def _predict(
        self,
        history: tuple[float, ...],
        horizon: int,
        station_id: str,
        forecast_at: object,
    ) -> float:
        """Pass serving context to newer predictors without breaking old adapters."""
        assert self._predictor is not None
        parameters = inspect.signature(self._predictor.predict).parameters
        if "station_id" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
        ):
            return float(
                self._predictor.predict(
                    history, horizon, station_id=station_id, forecast_at=forecast_at
                )
            )
        return float(self._predictor.predict(history, horizon))

    def _prepare_history(
        self,
        status: StationStatus,
        occupancy_history: tuple[float, ...] | None,
    ) -> tuple[float, ...]:
        if occupancy_history is None:
            if status.occupancy_ratio is None:
                raise ValueError("online station must have an occupancy ratio")
            return (status.occupancy_ratio,) * self._lookback_steps
        if len(occupancy_history) != self._lookback_steps:
            raise ValueError(
                f"occupancy_history must contain exactly {self._lookback_steps} values"
            )
        if any(not 0 <= value <= 1 for value in occupancy_history):
            raise ValueError("occupancy history values must be between 0 and 1")
        return occupancy_history

    @staticmethod
    def _result(
        status: StationStatus,
        requested_horizon: int,
        used_horizon: int,
        ratio: float,
        source: str,
        flags: list[str],
        *,
        target_at: datetime,
    ) -> OccupancyForecastResult:
        return OccupancyForecastResult(
            station_id=status.station_id,
            generated_at=datetime.now(UTC),
            target_at=target_at,
            requested_horizon_min=requested_horizon,
            used_horizon_min=used_horizon,
            predicted_occupancy_ratio=ratio,
            predicted_occupied_ports=ratio * status.operational_ports,
            operational_ports=status.operational_ports,
            prediction_source=source,
            flags=tuple(flags),
        )
