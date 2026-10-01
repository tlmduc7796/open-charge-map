"""Occupancy inference interface with an explicit persistence fallback."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Protocol

from backend.app.domain.models import OccupancyForecastResult, StationStatus


class OccupancyPredictor(Protocol):
    """Adapter contract for the Phase 04 model (see ``occupancy_model.py``).

    ``predict`` gets 12 occupancy ratios (oldest first) and a horizon of 5, 10 or 15
    minutes. A predictor whose features include time-of-day sets ``uses_timestamp = True``
    and must then also accept ``observed_at`` (the time of the newest observation).
    """

    def predict(self, occupancy_history: tuple[float, ...], horizon_min: int) -> float: ...


class OccupancyForecastService:
    def __init__(
        self,
        predictor: OccupancyPredictor | None = None,
        *,
        lookback_steps: int = 12,
        max_model_horizon_min: int = 15,
    ) -> None:
        if lookback_steps <= 0 or max_model_horizon_min <= 0:
            raise ValueError("forecast lookback and horizon must be positive")
        self._predictor = predictor
        self._lookback_steps = lookback_steps
        self._max_model_horizon_min = max_model_horizon_min

    @property
    def model_loaded(self) -> bool:
        return self._predictor is not None

    def forecast_occupancy(
        self,
        status: StationStatus,
        *,
        horizon_min: int,
        occupancy_history: tuple[float, ...] | None = None,
        observed_at: datetime | None = None,
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
                raw_prediction = float(self._call_predictor(history, used_horizon, observed_at))
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

    def _call_predictor(
        self,
        history: tuple[float, ...],
        horizon_min: int,
        observed_at: datetime | None,
    ) -> float:
        assert self._predictor is not None
        if getattr(self._predictor, "uses_timestamp", False):
            if observed_at is None:
                raise ValueError("this model needs observed_at for its time features")
            predict = self._predictor.predict
            return predict(history, horizon_min, observed_at=observed_at)  # type: ignore[call-arg]
        return self._predictor.predict(history, horizon_min)

    def _aligned_horizon(self, requested_horizon_min: int) -> int:
        if requested_horizon_min <= 5:
            return 5
        if requested_horizon_min <= 10:
            return 10
        return self._max_model_horizon_min

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
