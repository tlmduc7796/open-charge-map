"""Occupancy forecasts: model up to T+30, profile-anchored beyond, explicit persistence fallback."""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from backend.app.domain.far_horizon import (
    DEFAULT_TAU_MIN,
    MAX_FORECAST_HORIZON_MIN,
    MODEL_HORIZON_MIN,
    blend_with_profile,
)
from backend.app.domain.ml_gateway import MlGateway
from backend.app.domain.models import (
    ArrivalForecast,
    OccupancyForecastResult,
    OccupancyWindow,
    StationStatus,
)

logger = logging.getLogger("smart_ev.forecasting")

MODEL_HORIZONS_MIN = (5, 10, 15, 20, 25, 30)
# Milestone grid of the wait rule: five-minute steps, six of them after the arrival.
MILESTONE_STEP_MIN = 5
MILESTONES_AFTER_ARRIVAL = 6
# The newest bucket may be a few minutes old; stale ones already make the station unknown.
MAX_OBSERVATION_AGE_MIN = 15


class OccupancyPredictor(Protocol):
    """Real occupancy model: `horizon_min` minutes after the newest bucket of the window."""

    def predict(self, window: OccupancyWindow, horizon_min: int) -> float: ...


class OccupancyWindowProvider(Protocol):
    def window(self, station_id: str) -> OccupancyWindow | None: ...


class OccupancyProfileProvider(Protocol):
    def ratio_at(self, station_id: str, at: datetime) -> float | None:
        """Typical occupancy ratio of the station at wall-clock time `at`."""
        ...


def available_ports(operational_ports: int, predicted_occupied_ports: float) -> int:
    """Whole free ports; a fractional occupied port is rounded up (the pessimistic side)."""
    return max(0, operational_ports - math.ceil(predicted_occupied_ports))


class OccupancyForecastService:
    def __init__(
        self,
        predictor: OccupancyPredictor | None = None,
        *,
        supported_model_horizons: tuple[int, ...] = (5, 10, 15),
        ml_gateway: MlGateway | None = None,
        window_provider: OccupancyWindowProvider | None = None,
        profile_provider: OccupancyProfileProvider | None = None,
        profile_tau_min: float = DEFAULT_TAU_MIN,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not supported_model_horizons:
            raise ValueError("forecast horizons must not be empty")
        if any(horizon not in MODEL_HORIZONS_MIN for horizon in supported_model_horizons):
            raise ValueError("model horizons must use supported five-minute offsets")
        if profile_tau_min <= 0:
            raise ValueError("profile_tau_min must be positive")
        self._predictor = predictor
        self._gateway = ml_gateway
        self._window_provider = window_provider
        self._profile_provider = profile_provider
        self._profile_tau_min = profile_tau_min
        self._clock = clock or (lambda: datetime.now(UTC))
        self._supported_model_horizons = tuple(sorted(set(supported_model_horizons)))
        # station_id -> (status key the window was read for, window or None)
        self._window_cache: dict[str, tuple[tuple, OccupancyWindow | None]] = {}

    @property
    def model_loaded(self) -> bool:
        return self._predictor is not None

    @property
    def model_version(self) -> str | None:
        return getattr(self._predictor, "model_version", None)

    @property
    def prediction_source(self) -> str:
        """Source reported for forecasts when the station is online and has no history."""
        if self._predictor is not None:
            return "model"
        return "default" if self._gateway is not None else "persistence"

    def forecast_occupancy(
        self,
        status: StationStatus,
        *,
        horizon_min: int,
        as_of: datetime | None = None,
    ) -> OccupancyForecastResult:
        """Forecast `horizon_min` minutes from now (`as_of`, default the service clock)."""
        if horizon_min <= 0:
            raise ValueError("horizon_min must be positive")
        window, age_min = self._context(status, as_of)
        return self._forecast(status, horizon_min + age_min, horizon_min, window)

    def forecast_arrival(
        self,
        status: StationStatus,
        *,
        arrival_min: float,
        as_of: datetime | None = None,
    ) -> ArrivalForecast:
        """Forecasts at the milestones around an arrival `arrival_min` minutes from now.

        The grid is five-minute steps after the newest observation (the training convention).
        The result starts at the milestone at or before the arrival and spans the
        `MILESTONES_AFTER_ARRIVAL` milestones that follow it.
        """
        if not math.isfinite(arrival_min) or arrival_min < 0:
            raise ValueError("arrival_min must be a non-negative number")
        window, age_min = self._context(status, as_of)
        lead_min = arrival_min + age_min
        first = int(lead_min // MILESTONE_STEP_MIN) * MILESTONE_STEP_MIN
        milestones = tuple(
            first + MILESTONE_STEP_MIN * index for index in range(MILESTONES_AFTER_ARRIVAL + 1)
        )
        return ArrivalForecast(
            arrival_lead_min=lead_min,
            milestones_min=milestones,
            forecasts=tuple(
                self._forecast(status, milestone, max(0, milestone - age_min), window)
                for milestone in milestones
            ),
        )

    def _context(
        self, status: StationStatus, as_of: datetime | None
    ) -> tuple[OccupancyWindow | None, int]:
        window = self._window_for(status)
        if window is None:
            return None, 0
        now = as_of if as_of is not None else self._clock()
        if now.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        age_min = int((now - window.t_last).total_seconds() // 60)
        return window, min(MAX_OBSERVATION_AGE_MIN, max(0, age_min))

    def _window_for(self, status: StationStatus) -> OccupancyWindow | None:
        if self._predictor is None or self._window_provider is None:
            return None
        # A report may overwrite the newest bucket, so the counts are part of the key.
        key = (status.timestamp, status.operational_ports, status.occupied_ports)
        cached = self._window_cache.get(status.station_id)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            window = self._window_provider.window(status.station_id)
        except Exception:  # A history outage must degrade to persistence, not fail the search.
            logger.exception("occupancy_window_unavailable station=%s", status.station_id)
            return None
        self._window_cache[status.station_id] = (key, window)
        return window

    def _forecast(
        self,
        status: StationStatus,
        lead_min: int,
        requested_min: int,
        window: OccupancyWindow | None,
    ) -> OccupancyForecastResult:
        """Forecast `lead_min` minutes after the newest observation (0 = the observation)."""
        if lead_min == 0:
            return self._observation(status, requested_min)
        cap_min = MAX_FORECAST_HORIZON_MIN if self._predictor is not None else MODEL_HORIZON_MIN
        used = self._aligned_horizon(lead_min, cap_min)
        flags: list[str] = []
        if lead_min > cap_min:
            flags.append("BEYOND_FORECAST_HORIZON")
        if used > max(self._supported_model_horizons):
            flags.append("BEYOND_MODEL_HORIZON")
        elif used != lead_min:
            flags.append("HORIZON_ALIGNED_TO_MODEL")

        if status.operational_ports == 0:
            return OccupancyForecastResult(
                station_id=status.station_id,
                requested_horizon_min=requested_min,
                used_horizon_min=used,
                predicted_occupancy_ratio=None,
                predicted_occupied_ports=0,
                operational_ports=0,
                prediction_source="persistence",
                flags=tuple([*flags, "STATION_OFFLINE", "PERSISTENCE_FALLBACK"]),
            )

        if self._predictor is None:
            if self._gateway is not None:
                raw_ratio = float(
                    self._gateway.predict_occupancy_ratio(status.station_id, None, used)
                )
                if not math.isfinite(raw_ratio):
                    raise ValueError("default occupancy ratio must be finite")
                return self._result(
                    status,
                    requested_min,
                    used,
                    min(1.0, max(0.0, raw_ratio)),
                    "default",
                    [*flags, "ML_DEFAULT_VALUE"],
                )
            return self._persistence(status, requested_min, used, flags)

        if used <= MODEL_HORIZON_MIN:
            return self._near_horizon(status, requested_min, used, window, flags)
        return self._far_horizon(status, requested_min, used, window, flags)

    @staticmethod
    def _observation(status: StationStatus, requested_min: int) -> OccupancyForecastResult:
        """The newest reading itself, used as the milestone at lead 0."""
        online = status.operational_ports > 0
        flags = ("CURRENT_OBSERVATION",) if online else ("CURRENT_OBSERVATION", "STATION_OFFLINE")
        return OccupancyForecastResult(
            station_id=status.station_id,
            requested_horizon_min=requested_min,
            used_horizon_min=0,
            predicted_occupancy_ratio=status.occupancy_ratio if online else None,
            predicted_occupied_ports=status.occupied_ports,
            operational_ports=status.operational_ports,
            prediction_source="persistence",
            flags=flags,
        )

    def _near_horizon(
        self,
        status: StationStatus,
        requested_min: int,
        used: int,
        window: OccupancyWindow | None,
        flags: list[str],
    ) -> OccupancyForecastResult:
        if used not in self._supported_model_horizons:
            flags.append("MODEL_HORIZON_UNSUPPORTED")
        elif window is None:
            flags.append("HISTORY_UNAVAILABLE")
        else:
            prediction = self._predict(window, used, flags)
            if prediction is not None:
                return self._result(
                    status, requested_min, used, prediction, "model", flags, self.model_version
                )
        return self._persistence(status, requested_min, used, flags)

    def _far_horizon(
        self,
        status: StationStatus,
        requested_min: int,
        used: int,
        window: OccupancyWindow | None,
        flags: list[str],
    ) -> OccupancyForecastResult:
        if MODEL_HORIZON_MIN not in self._supported_model_horizons:
            flags.append("MODEL_HORIZON_UNSUPPORTED")
            return self._persistence(status, requested_min, used, flags)
        if window is None:
            flags.append("HISTORY_UNAVAILABLE")
            return self._persistence(status, requested_min, used, flags)
        anchor = self._predict(window, MODEL_HORIZON_MIN, flags)
        if anchor is None:
            return self._persistence(status, requested_min, used, flags)

        anchor_at = window.t_last + timedelta(minutes=MODEL_HORIZON_MIN)
        target_at = window.t_last + timedelta(minutes=used)
        profile_at_anchor = self._profile_ratio(status.station_id, anchor_at)
        profile_at_target = self._profile_ratio(status.station_id, target_at)
        if profile_at_anchor is None or profile_at_target is None:
            flags.append("PROFILE_UNAVAILABLE")
            return self._result(
                status, requested_min, used, anchor, "model", flags, self.model_version
            )
        ratio = blend_with_profile(
            anchor,
            profile_at_anchor,
            profile_at_target,
            used,
            tau_min=self._profile_tau_min,
        )
        flags.append("PROFILE_BLEND")
        return self._result(
            status, requested_min, used, ratio, "model_profile", flags, self.model_version
        )

    def _predict(
        self, window: OccupancyWindow, horizon_min: int, flags: list[str]
    ) -> float | None:
        """Clamped model prediction, or None (with a flag) when the adapter fails."""
        try:
            raw = float(self._predictor.predict(window, horizon_min))
            if not math.isfinite(raw):
                raise ValueError("model prediction must be finite")
        except Exception:  # Model adapter errors must degrade to the declared fallback.
            logger.exception(
                "occupancy_model_failed station=%s horizon=%d", window.station_id, horizon_min
            )
            flags.append("MODEL_INFERENCE_FAILED")
            return None
        clamped = min(1.0, max(0.0, raw))
        if clamped != raw and "PREDICTION_CLAMPED" not in flags:
            flags.append("PREDICTION_CLAMPED")
        return clamped

    def _profile_ratio(self, station_id: str, at: datetime) -> float | None:
        if self._profile_provider is None:
            return None
        try:
            return self._profile_provider.ratio_at(station_id, at)
        except Exception:
            logger.exception("occupancy_profile_failed station=%s", station_id)
            return None

    @staticmethod
    def _aligned_horizon(requested_horizon_min: int, cap_min: int) -> int:
        bounded = min(requested_horizon_min, cap_min)
        aligned = -(-bounded // 5) * 5
        return max(5, min(aligned, cap_min))

    def _persistence(
        self,
        status: StationStatus,
        requested_min: int,
        used: int,
        flags: list[str],
    ) -> OccupancyForecastResult:
        if status.occupancy_ratio is None:
            raise ValueError("online station must have an occupancy ratio")
        return self._result(
            status,
            requested_min,
            used,
            status.occupancy_ratio,
            "persistence",
            [*flags, "PERSISTENCE_FALLBACK"],
        )

    def _result(
        self,
        status: StationStatus,
        requested_horizon: int,
        used_horizon: int,
        ratio: float,
        source: str,
        flags: list[str],
        model_version: str | None = None,
    ) -> OccupancyForecastResult:
        occupied = ratio * status.operational_ports
        if self._gateway is not None:
            occupied = min(
                float(status.operational_ports),
                max(
                    0.0,
                    self._gateway.adjust_for_herding(
                        status.station_id, occupied, horizon_min=used_horizon
                    ),
                ),
            )
            ratio = occupied / status.operational_ports
        return OccupancyForecastResult(
            station_id=status.station_id,
            requested_horizon_min=requested_horizon,
            used_horizon_min=used_horizon,
            predicted_occupancy_ratio=ratio,
            predicted_occupied_ports=occupied,
            operational_ports=status.operational_ports,
            prediction_source=source,
            model_version=model_version,
            flags=tuple(flags),
        )
