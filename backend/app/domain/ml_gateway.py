"""Single boundary for every backend -> ML call, with fixed default values.

The real models (occupancy forecast, wait distribution, anti-herding correction) are not
integrated yet. Until they are, `DefaultMlGateway` answers every call with a deterministic
default and labels it `source="default"` so no result can be mistaken for a model output.
A real adapter only has to implement `MlGateway`.
"""

from __future__ import annotations

from typing import Protocol

from backend.app.domain.models import WaitDistribution

DEFAULT_OCCUPANCY_RATIO = 0.5


class MlGateway(Protocol):
    def predict_occupancy_ratio(
        self,
        station_id: str,
        occupancy_history: tuple[float, ...] | None,
        horizon_min: int,
    ) -> float:
        """Occupancy ratio in [0, 1] expected `horizon_min` minutes ahead (B1)."""
        ...

    def wait_distribution(
        self, station_id: str, *, point_estimate_min: float
    ) -> WaitDistribution:
        """P(W>0), E[W] and W90 for an arrival at the station (B2)."""
        ...

    def adjust_for_herding(
        self,
        station_id: str,
        predicted_occupied_ports: float,
        *,
        horizon_min: int,
    ) -> float:
        """Occupied ports after correcting for load induced by our own advice (B3)."""
        ...


class DefaultMlGateway:
    """Fixed answers: constant occupancy, point-mass wait, no herding correction."""

    def predict_occupancy_ratio(
        self,
        station_id: str,
        occupancy_history: tuple[float, ...] | None,
        horizon_min: int,
    ) -> float:
        return DEFAULT_OCCUPANCY_RATIO

    def wait_distribution(
        self, station_id: str, *, point_estimate_min: float
    ) -> WaitDistribution:
        # A constant would contradict the wait estimate shipped in the same payload, so the
        # default distribution is a point mass on that estimate.
        wait = max(0.0, point_estimate_min)
        return WaitDistribution(
            p_wait=1.0 if wait > 0 else 0.0,
            expected_wait_min=wait,
            p90_wait_min=wait,
            source="default",
        )

    def adjust_for_herding(
        self,
        station_id: str,
        predicted_occupied_ports: float,
        *,
        horizon_min: int,
    ) -> float:
        return predicted_occupied_ports
