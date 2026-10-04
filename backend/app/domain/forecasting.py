"""Occupancy inference interface with an explicit persistence fallback."""

from __future__ import annotations

import inspect
import math
from typing import Protocol

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


class OccupancyForecastService:
    def __init__(
        self,
        predictor: OccupancyPredictor | None = None,
        *,
        lookback_steps: int = 12,
        model_horizons_min: tuple[int, ...] = tuple(range(5, 61, 5)),
    ) -> None:
        if (
            lookback_steps <= 0
            or not model_horizons_min
            or any(value <= 0 for value in model_horizons_min)
        ):
            raise ValueError("forecast lookback and horizon must be positive")
        self._predictor = predictor
        self._lookback_steps = lookback_steps
        self._model_horizons_min = tuple(sorted(set(model_horizons_min)))
        self._max_model_horizon_min = self._model_horizons_min[-1]

    @property
    def model_loaded(self) -> bool:
        return self._predictor is not None

    def forecast_occupancy(
        self,
        status: StationStatus,
        *,
        horizon_min: int,
        occupancy_history: tuple[float, ...] | None = None,
    ) -> OccupancyForecastResult:
        if horizon_min <= 0:
            raise ValueError("horizon_min must be positive")

        used_horizon = self._aligned_horizon(horizon_min)
        flags: list[str] = []
        if horizon_min > self._max_model_horizon_min:
            flags.append("BEYOND_MODEL_HORIZON")
        elif used_horizon != horizon_min:
            flags.append("HORIZON_ALIGNED_TO_MODEL")

        if status.operational_ports == 0:
            return OccupancyForecastResult(
                station_id=status.station_id,
                requested_horizon_min=horizon_min,
                used_horizon_min=used_horizon,
                predicted_occupancy_ratio=None,
                predicted_occupied_ports=0,
                operational_ports=0,
                prediction_source="persistence",
                flags=tuple([*flags, "STATION_OFFLINE", "PERSISTENCE_FALLBACK"]),
            )

        history = self._prepare_history(status, occupancy_history)
        if self._predictor is not None:
            if occupancy_history is None:
                flags.append("SYNTHETIC_HISTORY")
            try:
                raw_prediction = float(
                    self._predict(history, used_horizon, status.station_id, status.timestamp)
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
    ) -> OccupancyForecastResult:
        return OccupancyForecastResult(
            station_id=status.station_id,
            requested_horizon_min=requested_horizon,
            used_horizon_min=used_horizon,
            predicted_occupancy_ratio=ratio,
            predicted_occupied_ports=ratio * status.operational_ports,
            operational_ports=status.operational_ports,
            prediction_source=source,
            flags=tuple(flags),
        )
