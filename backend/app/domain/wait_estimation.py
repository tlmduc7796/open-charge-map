"""Wait estimation from forecast free ports at the milestones around the arrival.

Forecasts exist on a five-minute grid. A driver arriving between two milestones (say at
minute 12, between 10 and 15) is judged by the worse of the two surrounding milestones:

- if `min(free(before), free(after))` already offers the required free ports, there is no wait;
- otherwise the wait is the time from the arrival to the first later milestone that does;
- when none of the six milestones after the arrival qualifies, the wait is 30 minutes.

This is a deterministic rule on top of the occupancy forecast, not a queueing model.
"""

from __future__ import annotations

from datetime import datetime

from backend.app.domain.forecasting import (
    MILESTONE_STEP_MIN,
    MILESTONES_AFTER_ARRIVAL,
    available_ports,
)
from backend.app.domain.ml_gateway import MlGateway
from backend.app.domain.models import ArrivalForecast, StationStatus, WaitEstimateResult

MAX_WAIT_MIN = MILESTONE_STEP_MIN * MILESTONES_AFTER_ARRIVAL
REQUIRED_FREE_PORTS = 1


class WaitEstimator:
    def __init__(
        self,
        *,
        scoring_wait_cap_min: float = MAX_WAIT_MIN,
        required_free_ports: int = REQUIRED_FREE_PORTS,
        ml_gateway: MlGateway | None = None,
    ) -> None:
        if scoring_wait_cap_min <= 0:
            raise ValueError("scoring_wait_cap_min must be positive")
        if required_free_ports <= 0:
            raise ValueError("required_free_ports must be positive")
        self._gateway = ml_gateway
        # The rule never waits longer than the last milestone, whatever the configured cap.
        self._cap_min = min(float(scoring_wait_cap_min), float(MAX_WAIT_MIN))
        self._required_free_ports = required_free_ports

    def estimate_wait(
        self,
        status: StationStatus,
        arrival: ArrivalForecast,
        *,
        evaluation_at: datetime,
    ) -> WaitEstimateResult:
        if evaluation_at.tzinfo is None:
            raise ValueError("evaluation_at must include a timezone")
        if len(arrival.forecasts) != MILESTONES_AFTER_ARRIVAL + 1:
            raise ValueError(
                f"arrival forecast must hold {MILESTONES_AFTER_ARRIVAL + 1} milestones"
            )
        for forecast in arrival.forecasts:
            if forecast.station_id != status.station_id:
                raise ValueError("status and forecast must reference the same station")
            if forecast.predicted_occupied_ports > status.operational_ports:
                raise ValueError("predicted occupied ports exceed current operational capacity")

        at_arrival = arrival.at_arrival
        if status.operational_ports == 0 or at_arrival.predicted_occupancy_ratio is None:
            return self._result(
                status,
                at_arrival.predicted_occupied_ports,
                evaluation_at,
                required=0,
                free_at_arrival=None,
                satisfied_at_min=None,
                estimated_wait=self._cap_min,
                flags=("STATION_OFFLINE", "CAPPED_WAIT"),
            )

        # Guards a configured requirement above the station's size (e.g. 2 on a 1-port station).
        required = min(self._required_free_ports, status.operational_ports)
        free = [
            available_ports(status.operational_ports, forecast.predicted_occupied_ports)
            for forecast in arrival.forecasts
        ]
        # Index 0 is the milestone at or before the arrival, index 1 the first one after it
        # (the same milestone as index 0 when the arrival lies exactly on the grid).
        before = free[0]
        after = free[0] if arrival.arrival_lead_min == arrival.milestones_min[0] else free[1]
        free_at_arrival = min(before, after)
        if free_at_arrival >= required:
            return self._result(
                status,
                at_arrival.predicted_occupied_ports,
                evaluation_at,
                required=required,
                free_at_arrival=free_at_arrival,
                satisfied_at_min=0.0,
                estimated_wait=0.0,
                flags=(),
            )

        for index in range(1, len(free)):
            if free[index] < required:
                continue
            wait = float(arrival.milestones_min[index]) - arrival.arrival_lead_min
            capped = min(wait, self._cap_min)
            return self._result(
                status,
                at_arrival.predicted_occupied_ports,
                evaluation_at,
                required=required,
                free_at_arrival=free_at_arrival,
                satisfied_at_min=wait,
                estimated_wait=capped,
                flags=("CAPPED_WAIT",) if capped < wait else (),
            )
        return self._result(
            status,
            at_arrival.predicted_occupied_ports,
            evaluation_at,
            required=required,
            free_at_arrival=free_at_arrival,
            satisfied_at_min=None,
            estimated_wait=self._cap_min,
            flags=("WAIT_NO_FREE_PORT_WITHIN_30MIN", "CAPPED_WAIT"),
        )

    def _result(
        self,
        status: StationStatus,
        predicted_occupied_ports: float,
        evaluation_at: datetime,
        *,
        required: int,
        free_at_arrival: int | None,
        satisfied_at_min: float | None,
        estimated_wait: float,
        flags: tuple[str, ...],
    ) -> WaitEstimateResult:
        return WaitEstimateResult(
            station_id=status.station_id,
            evaluation_at=evaluation_at,
            operational_ports=status.operational_ports,
            predicted_occupied_ports=predicted_occupied_ports,
            required_free_ports=required,
            free_ports_at_arrival=free_at_arrival,
            satisfied_at_min=satisfied_at_min,
            estimated_wait_min=estimated_wait,
            scoring_wait_cap_min=self._cap_min,
            wait_distribution=(
                self._gateway.wait_distribution(
                    status.station_id, point_estimate_min=estimated_wait
                )
                if self._gateway is not None
                else None
            ),
            flags=flags,
        )
