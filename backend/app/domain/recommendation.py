"""Phase 07 candidate filtering and fixed-threshold recommendation scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.models import PlannedArrival
from backend.app.domain.phase7_models import (
    CandidateExclusion,
    DemoScenario,
    JourneyRecommendationResult,
    RecommendationItem,
    RouteWaypoint,
)
from backend.app.domain.repositories import DomainData
from backend.app.domain.routing import RoutingService, route_metrics_to_station
from backend.app.domain.runtime import RuntimeStateStore
from backend.app.domain.services import (
    check_compatibility,
    estimate_charging,
    estimate_reachability,
)
from backend.app.domain.wait_estimation import WaitEstimator


@dataclass(frozen=True)
class RecommendationThresholds:
    max_detour_min: float
    max_wait_min: float
    max_charge_min: float
    soc_risk_buffer: float

    def __post_init__(self) -> None:
        if min(
            self.max_detour_min,
            self.max_wait_min,
            self.max_charge_min,
            self.soc_risk_buffer,
        ) <= 0:
            raise ValueError("recommendation thresholds must be positive")


class PlannedArrivalReader(Protocol):
    def all(self) -> tuple[PlannedArrival, ...]: ...


class RecommendationService:
    def __init__(
        self,
        data: DomainData,
        runtime: RuntimeStateStore,
        planned_arrivals: PlannedArrivalReader,
        routing: RoutingService,
        forecasting: OccupancyForecastService,
        wait_estimator: WaitEstimator,
        thresholds: RecommendationThresholds,
    ) -> None:
        self._data = data
        self._runtime = runtime
        self._planned_arrivals = planned_arrivals
        self._routing = routing
        self._forecasting = forecasting
        self._wait_estimator = wait_estimator
        self._thresholds = thresholds

    def recommend(
        self,
        scenario_id: str,
        *,
        apply_scenario_events: bool = False,
    ) -> JourneyRecommendationResult:
        scenario = self._data.demo_scenarios.get(scenario_id)
        return self.recommend_scenario(
            scenario, apply_scenario_events=apply_scenario_events
        )

    def recommend_scenario(
        self,
        scenario: DemoScenario,
        *,
        apply_scenario_events: bool = False,
    ) -> JourneyRecommendationResult:
        if apply_scenario_events:
            for event_id in scenario.event_ids:
                self._runtime.apply(event_id)

        vehicle = self._data.vehicles.get(scenario.vehicle_id)
        cached_routes = tuple(
            self._routing.cached_route(route_id) for route_id in scenario.route_ids
        )
        cached_direct = next(route for route in cached_routes if not route.waypoints)
        use_scenario_cache = self._same_point(
            cached_direct.origin, scenario.origin
        ) and self._same_point(cached_direct.destination, scenario.destination)
        if use_scenario_cache:
            direct_route = cached_direct
            routes_by_station = {
                waypoint.station_id: route
                for route in cached_routes
                for waypoint in route.waypoints
                if waypoint.station_id is not None
            }
        else:
            direct_route = self._routing.route(scenario.origin, scenario.destination)
            routes_by_station = {}

        items: list[RecommendationItem] = []
        exclusions: list[CandidateExclusion] = []
        for station in self._data.stations.all():
            if station.properties.access != "public":
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("NON_PUBLIC_ACCESS",),
                    )
                )
                continue

            status = self._runtime.get(station.station_id)
            if status.operational_ports == 0:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("STATION_OFFLINE",),
                    )
                )
                continue

            compatibility = check_compatibility(vehicle, station)
            if not compatibility.compatible:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=compatibility.reason_codes,
                    )
                )
                continue

            route = routes_by_station.get(station.station_id)
            if route is None and not use_scenario_cache:
                try:
                    lon, lat = station.geometry.coordinates
                    route = self._routing.route(
                        scenario.origin,
                        scenario.destination,
                        (
                            RouteWaypoint(
                                lat=lat,
                                lon=lon,
                                label=station.properties.name,
                                station_id=station.station_id,
                            ),
                        ),
                    )
                except RuntimeError:
                    route = None
            if route is None:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("ROUTE_NOT_AVAILABLE",),
                    )
                )
                continue
            distance_to_station_m, duration_to_station_s = route_metrics_to_station(
                route, station.station_id
            )
            reachability = estimate_reachability(
                vehicle,
                station,
                route_distance_m=distance_to_station_m,
                initial_soc=scenario.initial_soc,
                route_id=route.route_id,
                route_duration_s=duration_to_station_s,
            )
            if not reachability.reachable:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("INSUFFICIENT_SOC_RESERVE",),
                    )
                )
                continue

            eta_at = scenario.departure_at + timedelta(seconds=duration_to_station_s)
            horizon_min = max(1, round(duration_to_station_s / 60))
            forecast = self._forecasting.forecast_occupancy(
                status, horizon_min=horizon_min
            )
            wait = self._wait_estimator.estimate_wait(
                status,
                forecast,
                evaluation_at=eta_at,
                planned_arrivals=self._planned_arrivals.all(),
                scenario_id=scenario.scenario_id,
            )
            charging = estimate_charging(
                vehicle,
                station,
                arrival_soc=reachability.estimated_arrival_soc,
                target_soc=scenario.target_soc,
                effective_power_kw=compatibility.effective_power_kw,
            )
            detour_min = max(0.0, (route.duration_s - direct_route.duration_s) / 60)
            wait_score = self._lower_is_better(
                wait.estimated_wait_min, self._thresholds.max_wait_min
            )
            detour_score = self._lower_is_better(
                detour_min, self._thresholds.max_detour_min
            )
            charge_score = self._lower_is_better(
                charging.estimated_charge_min, self._thresholds.max_charge_min
            )
            soc_score = min(
                1.0,
                max(
                    0.0,
                    (reachability.estimated_arrival_soc - vehicle.reserve_soc)
                    / self._thresholds.soc_risk_buffer,
                ),
            )
            preference = scenario.preference
            final_score = (
                wait_score * preference.wait_weight
                + detour_score * preference.detour_weight
                + charge_score * preference.charging_time_weight
                + soc_score * preference.soc_risk_weight
            )
            items.append(
                RecommendationItem(
                    station_id=station.station_id,
                    station_name=station.properties.name,
                    route_id=route.route_id,
                    route_provider=route.provider,
                    route=route,
                    matched_connectors=compatibility.matched_connectors,
                    effective_power_kw=compatibility.effective_power_kw,
                    route_distance_to_station_m=distance_to_station_m,
                    route_duration_to_station_s=duration_to_station_s,
                    detour_min=detour_min,
                    arrival_soc=reachability.estimated_arrival_soc,
                    predicted_occupied_ports=forecast.predicted_occupied_ports,
                    predicted_occupancy_ratio=forecast.predicted_occupancy_ratio,
                    prediction_source=forecast.prediction_source,
                    estimated_wait_min=wait.estimated_wait_min,
                    estimated_charge_min=charging.estimated_charge_min,
                    energy_to_add_kwh=charging.energy_to_add_kwh,
                    wait_score=wait_score,
                    detour_score=detour_score,
                    charging_time_score=charge_score,
                    soc_risk_score=soc_score,
                    final_score=final_score,
                    rank=1,
                    flags=tuple(
                        dict.fromkeys(
                            (
                                *compatibility.reason_codes,
                                *forecast.flags,
                                *wait.flags,
                            )
                        )
                    ),
                )
            )

        ordered = sorted(items, key=lambda item: (-item.final_score, item.station_id))
        ranked = tuple(
            item.model_copy(update={"rank": index})
            for index, item in enumerate(ordered, start=1)
        )
        return JourneyRecommendationResult(
            scenario_id=scenario.scenario_id,
            generated_at=scenario.departure_at,
            vehicle_id=vehicle.vehicle_id,
            direct_route=direct_route,
            recommendations=ranked,
            excluded_candidates=tuple(exclusions),
            active_event_ids=self._runtime.active_event_ids(),
        )

    @staticmethod
    def _lower_is_better(value: float, maximum: float) -> float:
        return 1 - min(1.0, max(0.0, value) / maximum)

    @staticmethod
    def _same_point(left, right) -> bool:
        return abs(left.lat - right.lat) < 1e-6 and abs(left.lon - right.lon) < 1e-6
