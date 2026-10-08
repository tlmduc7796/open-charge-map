"""Deterministic Erlang C wait estimation with runtime state kept separate."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Protocol

from backend.app.domain.models import (
    OccupancyForecastResult,
    PlannedArrival,
    StationStatus,
    WaitEstimateResult,
)


class ArrivalRateProvider(Protocol):
    @property
    def planned_arrival_window_min(self) -> int: ...

    def baseline_rate(self, station_id: str, scenario_id: str | None = None) -> float: ...

    def has_override(self, scenario_id: str, station_id: str) -> bool: ...


class WaitEstimator:
    def __init__(
        self,
        assumptions: ArrivalRateProvider,
        *,
        scoring_wait_cap_min: float = 120,
    ) -> None:
        if scoring_wait_cap_min <= 0:
            raise ValueError("scoring_wait_cap_min must be positive")
        self._assumptions = assumptions
        self._scoring_wait_cap_min = scoring_wait_cap_min

    def estimate_wait(
        self,
        status: StationStatus,
        forecast: OccupancyForecastResult,
        *,
        evaluation_at: datetime,
        planned_arrivals: tuple[PlannedArrival, ...] = (),
        include_planned_arrivals: bool = True,
        scenario_id: str | None = None,
        excluded_arrival_id: str | None = None,
    ) -> WaitEstimateResult:
        if evaluation_at.tzinfo is None:
            raise ValueError("evaluation_at must include a timezone")
        if status.station_id != forecast.station_id:
            raise ValueError("status and forecast must reference the same station")
        if status.queue_length is None or status.avg_session_duration_min is None:
            raise ValueError("wait estimation requires queue and session-duration telemetry")
        if forecast.predicted_occupied_ports > status.operational_ports:
            raise ValueError("predicted occupied ports exceed current operational capacity")

        flags: list[str] = []
        baseline_rate = self._assumptions.baseline_rate(status.station_id, scenario_id)
        if scenario_id is not None and self._assumptions.has_override(
            scenario_id, status.station_id
        ):
            flags.append("SCENARIO_OVERRIDE_APPLIED")

        planned_rate = 0.0
        if include_planned_arrivals:
            planned_rate = self._planned_arrival_rate(
                status.station_id,
                evaluation_at,
                planned_arrivals,
                excluded_arrival_id,
            )
            if planned_rate > 0:
                flags.append("PLANNED_ARRIVALS_INCLUDED")
        total_arrival_rate = baseline_rate + planned_rate
        service_rate = 60 / status.avg_session_duration_min

        if status.operational_ports == 0:
            return self._result(
                status,
                forecast,
                evaluation_at,
                baseline_rate,
                planned_rate,
                total_arrival_rate,
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
        traffic_intensity = total_arrival_rate / capacity_rate
        current_state_wait = self._current_state_wait(
            forecast.predicted_occupied_ports,
            status.queue_length,
            servers,
            status.avg_session_duration_min,
        )

        if total_arrival_rate >= capacity_rate:
            return self._result(
                status,
                forecast,
                evaluation_at,
                baseline_rate,
                planned_rate,
                total_arrival_rate,
                service_rate,
                traffic_intensity=traffic_intensity,
                probability_wait=1,
                erlang_wait=self._scoring_wait_cap_min,
                current_state_wait=current_state_wait,
                estimated_wait=self._scoring_wait_cap_min,
                flags=tuple([*flags, "OVERLOADED", "CAPPED_WAIT"]),
            )

        probability_wait, erlang_wait = self._erlang_c(
            total_arrival_rate, service_rate, servers
        )
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
            baseline_rate,
            planned_rate,
            total_arrival_rate,
            service_rate,
            traffic_intensity=traffic_intensity,
            probability_wait=probability_wait,
            erlang_wait=erlang_wait,
            current_state_wait=current_state_wait,
            estimated_wait=estimated_wait,
            flags=tuple(flags),
        )

    def _planned_arrival_rate(
        self,
        station_id: str,
        evaluation_at: datetime,
        arrivals: tuple[PlannedArrival, ...],
        excluded_arrival_id: str | None,
    ) -> float:
        window_min = self._assumptions.planned_arrival_window_min
        window_end = evaluation_at + timedelta(minutes=window_min)
        probability_sum = sum(
            arrival.arrival_probability
            for arrival in arrivals
            if arrival.station_id == station_id
            and arrival.arrival_id != excluded_arrival_id
            and arrival.status == "planned"
            and arrival.expires_at > evaluation_at
            and evaluation_at <= arrival.eta_at < window_end
        )
        return probability_sum * 60 / window_min

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
        baseline_rate: float,
        planned_rate: float,
        total_arrival_rate: float,
        service_rate: float,
        *,
        traffic_intensity: float | None,
        probability_wait: float | None,
        erlang_wait: float,
        current_state_wait: float,
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
            baseline_arrival_rate_per_hour=baseline_rate,
            planned_arrival_rate_per_hour=planned_rate,
            total_arrival_rate_per_hour=total_arrival_rate,
            service_rate_per_server_per_hour=service_rate,
            traffic_intensity=traffic_intensity,
            erlang_c_probability_wait=probability_wait,
            erlang_expected_wait_min=erlang_wait,
            current_state_wait_min=current_state_wait,
            estimated_wait_min=estimated_wait,
            scoring_wait_cap_min=self._scoring_wait_cap_min,
            flags=flags,
        )
