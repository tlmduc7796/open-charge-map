"""Deterministic Erlang C wait estimation."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Protocol

from backend.app.domain.ml_gateway import MlGateway
from backend.app.domain.models import (
    OccupancyForecastResult,
    StationStatus,
    WaitEstimateResult,
)

DEFAULT_WAIT_MIN = 5


class ArrivalRateProvider(Protocol):
    def baseline_rate(self, station_id: str) -> float: ...

    def baseline_source(self, station_id: str) -> str: ...


class WaitEstimator:
    def __init__(
        self,
        assumptions: ArrivalRateProvider,
        *,
        scoring_wait_cap_min: float = 120,
        default_wait_min: float = DEFAULT_WAIT_MIN,
        ml_gateway: MlGateway | None = None,
    ) -> None:
        if scoring_wait_cap_min <= 0:
            raise ValueError("scoring_wait_cap_min must be positive")
        if default_wait_min < 0:
            raise ValueError("default_wait_min must be non-negative")
        self._gateway = ml_gateway
        self._assumptions = assumptions
        self._scoring_wait_cap_min = scoring_wait_cap_min
        self._default_wait_min = default_wait_min

    def baseline_source(self, station_id: str) -> str:
        return self._assumptions.baseline_source(station_id)

    def estimate_wait(
        self,
        status: StationStatus,
        forecast: OccupancyForecastResult,
        *,
        evaluation_at: datetime,
    ) -> WaitEstimateResult:
        if evaluation_at.tzinfo is None:
            raise ValueError("evaluation_at must include a timezone")
        if status.station_id != forecast.station_id:
            raise ValueError("status and forecast must reference the same station")
        if forecast.predicted_occupied_ports > status.operational_ports:
            raise ValueError("predicted occupied ports exceed current operational capacity")

        flags: list[str] = []
        arrival_rate = self._assumptions.baseline_rate(status.station_id)
        if status.queue_length is None or status.avg_session_duration_min is None:
            return self._result(
                status,
                forecast,
                evaluation_at,
                arrival_rate,
                total_arrival_rate=arrival_rate,
                service_rate=None,
                traffic_intensity=None,
                probability_wait=None,
                erlang_wait=None,
                current_state_wait=None,
                estimated_wait=self._default_wait_min,
                flags=("WAIT_DEFAULTED_MISSING_INPUTS",),
            )

        service_rate = 60 / status.avg_session_duration_min

        if status.operational_ports == 0:
            return self._result(
                status,
                forecast,
                evaluation_at,
                arrival_rate,
                service_rate,
                traffic_intensity=None,
                probability_wait=None,
                erlang_wait=0,
                current_state_wait=self._scoring_wait_cap_min,
                estimated_wait=self._scoring_wait_cap_min,
                flags=tuple([*flags, "STATION_OFFLINE", "CAPPED_WAIT"]),
            )

        servers = status.operational_ports
        capacity_rate = servers * service_rate
        traffic_intensity = arrival_rate / capacity_rate
        current_state_wait = self._current_state_wait(
            forecast.predicted_occupied_ports,
            status.queue_length,
            servers,
            status.avg_session_duration_min,
        )

        if arrival_rate >= capacity_rate:
            return self._result(
                status,
                forecast,
                evaluation_at,
                arrival_rate,
                service_rate,
                traffic_intensity=traffic_intensity,
                probability_wait=1,
                erlang_wait=self._scoring_wait_cap_min,
                current_state_wait=current_state_wait,
                estimated_wait=self._scoring_wait_cap_min,
                flags=tuple([*flags, "OVERLOADED", "CAPPED_WAIT"]),
            )

        probability_wait, erlang_wait = self._erlang_c(arrival_rate, service_rate, servers)
        projected_available_ports = servers - forecast.predicted_occupied_ports
        if projected_available_ports >= 1 and status.queue_length == 0:
            uncapped_wait = 0.0
        else:
            uncapped_wait = max(current_state_wait, erlang_wait)
        estimated_wait = min(uncapped_wait, self._scoring_wait_cap_min)
        if estimated_wait < uncapped_wait:
            flags.append("CAPPED_WAIT")

        return self._result(
            status,
            forecast,
            evaluation_at,
            arrival_rate,
            service_rate,
            traffic_intensity=traffic_intensity,
            probability_wait=probability_wait,
            erlang_wait=erlang_wait,
            current_state_wait=current_state_wait,
            estimated_wait=estimated_wait,
            flags=tuple(flags),
        )

    @staticmethod
    def _current_state_wait(
        predicted_occupied_ports: float,
        queue_length: int,
        servers: int,
        avg_session_duration_min: float,
    ) -> float:
        projected_available_ports = max(0.0, servers - predicted_occupied_ports)
        required_releases = max(0.0, queue_length + 1 - projected_available_ports)
        return required_releases * avg_session_duration_min / servers

    @staticmethod
    def _erlang_c(
        arrival_rate_per_hour: float,
        service_rate_per_server: float,
        servers: int,
    ) -> tuple[float, float]:
        if arrival_rate_per_hour == 0:
            return 0.0, 0.0
        offered_load = arrival_rate_per_hour / service_rate_per_server
        traffic_intensity = offered_load / servers
        finite_sum = sum(
            offered_load**customers / math.factorial(customers)
            for customers in range(servers)
        )
        wait_term = offered_load**servers / (
            math.factorial(servers) * (1 - traffic_intensity)
        )
        probability_wait = wait_term / (finite_sum + wait_term)
        expected_wait_hours = probability_wait / (
            servers * service_rate_per_server - arrival_rate_per_hour
        )
        return probability_wait, expected_wait_hours * 60

    def _result(
        self,
        status: StationStatus,
        forecast: OccupancyForecastResult,
        evaluation_at: datetime,
        arrival_rate: float,
        service_rate: float | None = None,
        *,
        total_arrival_rate: float | None = None,
        traffic_intensity: float | None,
        probability_wait: float | None,
        erlang_wait: float | None,
        current_state_wait: float | None,
        estimated_wait: float,
        flags: tuple[str, ...],
    ) -> WaitEstimateResult:
        return WaitEstimateResult(
            station_id=status.station_id,
            evaluation_at=evaluation_at,
            operational_ports=status.operational_ports,
            predicted_occupied_ports=forecast.predicted_occupied_ports,
            current_queue_length=status.queue_length,
            avg_session_duration_min=status.avg_session_duration_min,
            baseline_arrival_rate_per_hour=arrival_rate,
            total_arrival_rate_per_hour=(
                arrival_rate if total_arrival_rate is None else total_arrival_rate
            ),
            service_rate_per_server_per_hour=service_rate,
            traffic_intensity=traffic_intensity,
            erlang_c_probability_wait=probability_wait,
            erlang_expected_wait_min=erlang_wait,
            current_state_wait_min=current_state_wait,
            estimated_wait_min=estimated_wait,
            scoring_wait_cap_min=self._scoring_wait_cap_min,
            wait_distribution=(
                self._gateway.wait_distribution(
                    status.station_id, point_estimate_min=estimated_wait
                )
                if self._gateway is not None
                else None
            ),
            flags=flags,
        )
