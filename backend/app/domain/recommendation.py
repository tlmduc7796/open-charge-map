"""Phase 07 candidate filtering and fixed-threshold recommendation scoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.geo import haversine_m
from backend.app.domain.models import OccupancyForecastResult, PlannedArrival, Station, Vehicle
from backend.app.domain.phase7_models import (
    CandidateExclusion,
    DemoScenario,
    JourneyRecommendationResult,
    RecommendationItem,
    RouteWaypoint,
    UnreachableStationFallback,
)
from backend.app.domain.repositories import DomainData
from backend.app.domain.routing import (
    RoutingService,
    has_complete_leg_metrics,
    route_metrics_to_station,
)
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

    def active_for_stations(
        self, station_ids: tuple[str, ...]
    ) -> tuple[PlannedArrival, ...]: ...


class VehicleReader(Protocol):
    def get(self, vehicle_id: str) -> Vehicle: ...


class StationCandidateReader(Protocol):
    def candidates(
        self,
        origin_lon: float,
        origin_lat: float,
        destination_lon: float,
        destination_lat: float,
        corridor_m: float,
        *,
        include_synthetic: bool,
        limit: int,
    ) -> tuple[Station, ...]: ...


class OccupancyHistoryReader(Protocol):
    def get_history(
        self, station_id: str, *, as_of, steps: int
    ) -> tuple[float, ...] | None: ...


class IncidentImpactReader(Protocol):
    def active_ranking_impacts(
        self, station_ids: tuple[str, ...]
    ) -> tuple[dict[str, str], ...]: ...


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
        *,
        vehicle_repository: VehicleReader | None = None,
        station_repository: StationCandidateReader | None = None,
        candidate_corridor_m: float = 5_000,
        max_candidates: int = 50,
        allow_synthetic_data: bool = True,
        occupancy_history: OccupancyHistoryReader | None = None,
        incident_impacts: IncidentImpactReader | None = None,
        prediction_writer: Callable[[tuple[OccupancyForecastResult, ...]], None]
        | None = None,
    ) -> None:
        if candidate_corridor_m <= 0:
            raise ValueError("candidate corridor must be positive")
        if not 1 <= max_candidates <= 500:
            raise ValueError("maximum candidates must be between 1 and 500")
        self._data = data
        self._vehicles = vehicle_repository or data.vehicles
        self._stations = station_repository or data.stations
        self._runtime = runtime
        self._planned_arrivals = planned_arrivals
        self._routing = routing
        self._forecasting = forecasting
        self._wait_estimator = wait_estimator
        self._thresholds = thresholds
        self._candidate_corridor_m = candidate_corridor_m
        self._max_candidates = max_candidates
        self._allow_synthetic_data = allow_synthetic_data
        self._occupancy_history = occupancy_history
        self._incident_impacts = incident_impacts
        self._prediction_writer = prediction_writer

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
        if self._allow_synthetic_data:
            self._runtime.refresh()
        if apply_scenario_events:
            for event_id in scenario.event_ids:
                self._runtime.apply(event_id)

        vehicle = self._vehicles.get(scenario.vehicle_id)
        if not self._allow_synthetic_data and not vehicle.is_release_eligible:
            raise ValueError("synthetic vehicle profiles are disabled outside demo mode")
        cached_routes = tuple(
            self._routing.cached_route(route_id) for route_id in scenario.route_ids
        )
        cached_direct = next(
            (route for route in cached_routes if not route.waypoints), None
        )
        use_scenario_cache = cached_direct is not None and self._same_point(
            cached_direct.origin, scenario.origin
        ) and self._same_point(cached_direct.destination, scenario.destination)
        if use_scenario_cache:
            assert cached_direct is not None
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
        forecasts_to_persist: list[OccupancyForecastResult] = []
        if hasattr(self._stations, "candidates"):
            stations = self._stations.candidates(
                scenario.origin.lon,
                scenario.origin.lat,
                scenario.destination.lon,
                scenario.destination.lat,
                self._candidate_corridor_m,
                include_synthetic=self._allow_synthetic_data,
                limit=self._max_candidates + 1,
            )
        else:
            stations = self._stations.all()
        candidates_truncated = len(stations) > self._max_candidates
        stations = stations[: self._max_candidates]
        active_incident_types_by_station: dict[str, set[str]] = {}
        if self._incident_impacts is not None and stations:
            for incident in self._incident_impacts.active_ranking_impacts(
                tuple(station.station_id for station in stations)
            ):
                active_incident_types_by_station.setdefault(
                    incident["station_id"], set()
                ).add(incident["incident_type"])
        status_by_station = (
            {
                status.station_id: status
                for status in self._runtime.get_many(
                    tuple(station.station_id for station in stations)
                )
            }
            if not self._allow_synthetic_data
            else None
        )
        planned_arrivals = self._planned_arrivals.active_for_stations(
            tuple(station.station_id for station in stations)
        )
        for station in stations:
            if not self._allow_synthetic_data and (
                station.properties.synthetic_fields
                or any(
                    "synthetic" in connector.source
                    for connector in station.properties.connectors
                )
            ):
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("SYNTHETIC_STATION_DATA",),
                    )
                )
                continue
            if station.properties.access != "public":
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("NON_PUBLIC_ACCESS",),
                    )
                )
                continue

            incident_reason_codes = tuple(
                reason
                for incident_type, reason in (
                    ("safety_concern", "ACTIVE_SAFETY_INCIDENT"),
                    ("access_problem", "ACTIVE_ACCESS_INCIDENT"),
                )
                if incident_type in active_incident_types_by_station.get(
                    station.station_id, set()
                )
            )
            if incident_reason_codes:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=incident_reason_codes,
                    )
                )
                continue

            try:
                status = (
                    status_by_station[station.station_id]
                    if status_by_station is not None
                    else self._runtime.get(station.station_id)
                )
            except KeyError:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("TELEMETRY_UNAVAILABLE",),
                    )
                )
                continue
            if status.operational_ports == 0:
                reason_code = (
                    "UNKNOWN_PORT_STATUS" if status.unknown_ports else "STATION_OFFLINE"
                )
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=(reason_code,),
                    )
                )
                continue
            if not self._allow_synthetic_data and status.is_stale:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("STALE_STATUS",),
                    )
                )
                continue
            if not self._allow_synthetic_data and status.data_source in {
                "synthetic",
                "simulated",
                "unknown",
                "runtime",
            }:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("SYNTHETIC_OR_UNVERIFIED_STATUS",),
                    )
                )
                continue
            unknown_status_flags = (
                ("UNKNOWN_PORTS_PRESENT",) if status.unknown_ports else ()
            )

            compatibility = check_compatibility(vehicle, station)
            if not compatibility.compatible:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=compatibility.reason_codes,
                    )
                )
                continue
            if status.port_runtime_statuses is not None:
                compatible_types = set(compatibility.matched_connectors)
                compatible_ports = tuple(
                    port
                    for port in status.port_runtime_statuses
                    if compatible_types.intersection(port.connector_types)
                )
                compatible_operational_ports = sum(
                    port.state in {"available", "charging"}
                    for port in compatible_ports
                )
                if compatible_operational_ports == 0:
                    if not compatible_ports:
                        reason_code = "COMPATIBLE_PORT_TELEMETRY_UNAVAILABLE"
                    elif any(port.state == "unknown" for port in compatible_ports):
                        reason_code = "COMPATIBLE_PORT_STATUS_UNKNOWN"
                    else:
                        reason_code = "NO_COMPATIBLE_PORT_AVAILABLE"
                    exclusions.append(
                        CandidateExclusion(
                            station_id=station.station_id,
                            reason_codes=(reason_code,),
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
            if not has_complete_leg_metrics(route):
                route = route.model_copy(
                    update={"flags": tuple((*route.flags, "LEG_METRICS_APPROXIMATED"))}
                )
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
            history = (
                self._occupancy_history.get_history(
                    station.station_id,
                    as_of=status.timestamp,
                    steps=self._forecasting.lookback_steps,
                )
                if self._occupancy_history is not None
                else None
            )
            forecast = self._forecasting.forecast_occupancy(
                status,
                horizon_min=horizon_min,
                occupancy_history=history,
                forecast_at=eta_at,
            )
            forecasts_to_persist.append(forecast)
            try:
                wait = self._wait_estimator.estimate_wait(
                    status,
                    forecast,
                    evaluation_at=eta_at,
                    compatible_connector_types=compatibility.matched_connectors,
                    planned_arrivals=planned_arrivals,
                    scenario_id=scenario.scenario_id,
                )
            except (KeyError, ValueError):
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("WAIT_INPUT_UNAVAILABLE",),
                    )
                )
                continue
            charging = estimate_charging(
                vehicle,
                station,
                arrival_soc=reachability.estimated_arrival_soc,
                target_soc=scenario.target_soc,
                effective_power_kw=compatibility.effective_power_kw,
            )
            remaining_distance_m = max(0.0, route.distance_m - distance_to_station_m)
            remaining_energy_kwh = (
                remaining_distance_m / 1000 * vehicle.consumption_wh_km / 1000
            )
            destination_soc = (
                scenario.target_soc
                - remaining_energy_kwh / vehicle.calculation_battery_kwh
            )
            if destination_soc < vehicle.reserve_soc:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("INSUFFICIENT_SOC_AFTER_CHARGE",),
                    )
                )
                continue
            minimum_soc = min(reachability.estimated_arrival_soc, destination_soc)
            detour_min = max(0.0, (route.duration_s - direct_route.duration_s) / 60)
            drive_to_station_min = duration_to_station_s / 60
            drive_station_to_destination_min = max(
                0.0, (route.duration_s - duration_to_station_s) / 60
            )
            total_time_min = (
                drive_to_station_min
                + wait.estimated_wait_min
                + charging.estimated_charge_min
                + drive_station_to_destination_min
            )
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
                    drive_to_station_min=drive_to_station_min,
                    drive_station_to_destination_min=drive_station_to_destination_min,
                    detour_min=detour_min,
                    arrival_soc=reachability.estimated_arrival_soc,
                    destination_soc=destination_soc,
                    minimum_soc=minimum_soc,
                    predicted_occupied_ports=forecast.predicted_occupied_ports,
                    predicted_occupancy_ratio=forecast.predicted_occupancy_ratio,
                    predicted_free_ports=max(
                        0.0,
                        forecast.operational_ports - forecast.predicted_occupied_ports,
                    ),
                    prediction_source=forecast.prediction_source,
                    model_version=forecast.model_version,
                    estimated_wait_min=wait.estimated_wait_min,
                    wait_expected_min=wait.estimated_wait_min,
                    wait_probability=wait.erlang_c_probability_wait,
                    wait_p90_min=wait.estimated_wait_p90_min,
                    wait_method=wait.method,
                    estimated_charge_min=charging.estimated_charge_min,
                    charge_min=charging.estimated_charge_min,
                    soc_after_charge=scenario.target_soc,
                    total_time_min=total_time_min,
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
                                *unknown_status_flags,
                                *forecast.flags,
                                *wait.flags,
                                *route.flags,
                            )
                        )
                    ),
                )
            )

        ordered = self._rank_by_total_time(items)
        ranked = tuple(
            item.model_copy(update={"rank": index})
            for index, item in enumerate(ordered, start=1)
        )
        if self._prediction_writer is not None and forecasts_to_persist:
            self._prediction_writer(tuple(forecasts_to_persist))
        fallback_candidate = None
        if not ranked and stations:
            nearest_station = min(
                stations,
                key=lambda station: (
                    haversine_m(
                        scenario.origin.lat,
                        scenario.origin.lon,
                        station.geometry.coordinates[1],
                        station.geometry.coordinates[0],
                    ),
                    station.station_id,
                ),
            )
            exclusion_by_station = {
                exclusion.station_id: exclusion.reason_codes
                for exclusion in exclusions
            }
            fallback_candidate = UnreachableStationFallback(
                station_id=nearest_station.station_id,
                station_name=nearest_station.properties.name,
                straight_line_distance_m=haversine_m(
                    scenario.origin.lat,
                    scenario.origin.lon,
                    nearest_station.geometry.coordinates[1],
                    nearest_station.geometry.coordinates[0],
                ),
                reason_codes=exclusion_by_station.get(
                    nearest_station.station_id, ("NOT_FEASIBLE",)
                ),
            )
        return JourneyRecommendationResult(
            scenario_id=scenario.scenario_id,
            generated_at=scenario.departure_at,
            vehicle_id=vehicle.vehicle_id,
            direct_route=direct_route,
            outcome="charging_stops" if ranked else "no_reachable_station",
            recommendations=ranked,
            excluded_candidates=tuple(exclusions),
            fallback_candidate=fallback_candidate,
            active_event_ids=self._runtime.active_event_ids(),
            flags=("RECOMMENDATION_CANDIDATE_LIMIT_REACHED",)
            if candidates_truncated
            else (),
            candidate_limit=self._max_candidates if candidates_truncated else None,
        )

    @staticmethod
    def _lower_is_better(value: float, maximum: float) -> float:
        return 1 - min(1.0, max(0.0, value) / maximum)

    @staticmethod
    def _rank_by_total_time(items: list[RecommendationItem]) -> list[RecommendationItem]:
        """Order by elapsed time, using deterministic safety tie-breaks within 0.1 min."""
        by_time = sorted(items, key=lambda item: (item.total_time_min, item.station_id))
        ordered: list[RecommendationItem] = []
        index = 0
        while index < len(by_time):
            anchor_time = by_time[index].total_time_min
            end = index + 1
            while end < len(by_time) and by_time[end].total_time_min - anchor_time <= 0.1:
                end += 1
            group = by_time[index:end]
            group.sort(
                key=lambda item: (
                    -item.minimum_soc,
                    item.wait_probability if item.wait_probability is not None else 1.0,
                    item.station_id,
                )
            )
            ordered.extend(group)
            index = end
        return ordered

    @staticmethod
    def _same_point(left, right) -> bool:
        return abs(left.lat - right.lat) < 1e-6 and abs(left.lon - right.lon) < 1e-6
