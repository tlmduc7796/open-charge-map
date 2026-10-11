"""Writes the occupancy forecast and the derived wait of each station to `predictions`."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import Engine, text

from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.models import StationStatus
from backend.app.domain.wait_estimation import WaitEstimator

PREDICTION_HORIZONS_MIN = (5, 10, 15, 20, 25, 30)
logger = logging.getLogger("smart_ev.predictions")

# `public.prediction_source` only knows these labels; the profile blend is stored as `model`.
_STORED_SOURCE = {
    "model": "model",
    "model_profile": "model",
    "persistence": "persistence",
    "default": "default",
}


_FALLBACK_VERSION = {
    "model": "xgb-occupancy",
    "persistence": "persistence",
    "default": "fixed-default-v1",
}


class StatusReader(Protocol):
    def get(self, station_id: str) -> StationStatus: ...

    def all(self) -> tuple[StationStatus, ...]: ...


class PredictionWriter:
    """Computes forecast + wait for T+5..T+30 and upserts one row per station and horizon."""

    def __init__(
        self,
        engine: Engine,
        statuses: StatusReader,
        forecasting: OccupancyForecastService,
        wait_estimator: WaitEstimator,
    ) -> None:
        self._engine = engine
        self._statuses = statuses
        self._forecasting = forecasting
        self._wait_estimator = wait_estimator

    def refresh(
        self, station_codes: Iterable[str] | None = None, *, run_at: datetime | None = None
    ) -> int:
        """Rewrite the slots of the given stations (all when None); returns rows written."""
        now = run_at or datetime.now(UTC)
        if station_codes is None:
            statuses = list(self._statuses.all())
        else:
            statuses = []
            for code in dict.fromkeys(station_codes):
                try:
                    statuses.append(self._statuses.get(code))
                except KeyError:
                    logger.warning("prediction_station_unknown station=%s", code)
        rows = [row for status in statuses for row in self._rows(status, now)]
        if not rows:
            return 0
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO predictions (
                        station_id, horizon_min, run_at, predicted_occupancy_ratio,
                        operational_ports_at_run, wait_probability, mean_wait_minutes,
                        p90_wait_minutes, prediction_source, model_version
                    )
                    SELECT s.id, :horizon_min, :run_at, :ratio, :operational_ports,
                           :wait_probability, :mean_wait_minutes, :p90_wait_minutes,
                           CAST(:prediction_source AS prediction_source), :model_version
                    FROM stations s WHERE s.code = :station_id
                    ON CONFLICT (station_id, horizon_min) DO UPDATE SET
                        run_at=EXCLUDED.run_at,
                        predicted_occupancy_ratio=EXCLUDED.predicted_occupancy_ratio,
                        operational_ports_at_run=EXCLUDED.operational_ports_at_run,
                        wait_probability=EXCLUDED.wait_probability,
                        mean_wait_minutes=EXCLUDED.mean_wait_minutes,
                        p90_wait_minutes=EXCLUDED.p90_wait_minutes,
                        prediction_source=EXCLUDED.prediction_source,
                        model_version=EXCLUDED.model_version
                    """
                ),
                rows,
            )
        return len(rows)

    def _rows(self, status: StationStatus, run_at: datetime) -> list[dict]:
        rows: list[dict] = []
        for horizon in PREDICTION_HORIZONS_MIN:
            try:
                forecast = self._forecasting.forecast_occupancy(
                    status, horizon_min=horizon, as_of=run_at
                )
                arrival = self._forecasting.forecast_arrival(
                    status, arrival_min=horizon, as_of=run_at
                )
                wait = self._wait_estimator.estimate_wait(
                    status, arrival, evaluation_at=run_at + timedelta(minutes=horizon)
                )
            except Exception:
                logger.exception(
                    "prediction_failed station=%s horizon=%d", status.station_id, horizon
                )
                continue
            distribution = wait.wait_distribution
            mean_wait = (
                distribution.expected_wait_min
                if distribution is not None
                else wait.estimated_wait_min
            )
            p90_wait = (
                distribution.p90_wait_min if distribution is not None else wait.estimated_wait_min
            )
            source = _STORED_SOURCE[forecast.prediction_source]
            rows.append(
                {
                    "station_id": status.station_id,
                    "horizon_min": horizon,
                    "run_at": run_at,
                    "ratio": forecast.predicted_occupancy_ratio,
                    "operational_ports": status.operational_ports,
                    "wait_probability": (
                        distribution.p_wait
                        if distribution is not None
                        else (1.0 if wait.estimated_wait_min > 0 else 0.0)
                    ),
                    "mean_wait_minutes": mean_wait,
                    "p90_wait_minutes": max(p90_wait, mean_wait),
                    "prediction_source": source,
                    "model_version": forecast.model_version or _FALLBACK_VERSION[source],
                }
            )
        return rows
