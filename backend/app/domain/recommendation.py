"""Candidate filtering and fixed-threshold recommendation scoring for one journey query."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.models import Station, Vehicle
from backend.app.domain.phase7_models import (
    CandidateExclusion,
    JourneyQuery,
    JourneyRecommendationResult,
    RecommendationItem,
    RouteWaypoint,
)
from backend.app.domain.routing import (
    RoutingService,
    _haversine_m,
    route_metrics_to_station,
)
from backend.app.domain.runtime import RuntimeStateStore
from backend.app.domain.services import (
    check_compatibility,
    estimate_charging,
    estimate_reachability,
)
from backend.app.domain.station_hours import is_confirmed_open
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
    ) -> tuple[Station, ...]: ...


class RecommendationService:
    def __init__(
        self,
        runtime: RuntimeStateStore,
        routing: RoutingService,
        forecasting: OccupancyForecastService,
        wait_estimator: WaitEstimator,
        thresholds: RecommendationThresholds,
        *,
        vehicle_repository: VehicleReader,
        station_repository: StationCandidateReader,
        candidate_corridor_m: float = 5_000,
    ) -> None:
        if candidate_corridor_m <= 0:
            raise ValueError("candidate corridor must be positive")
        self._vehicles = vehicle_repository
        self._stations = station_repository
        self._runtime = runtime
        self._routing = routing
        self._forecasting = forecasting
        self._wait_estimator = wait_estimator
        self._thresholds = thresholds
        self._candidate_corridor_m = candidate_corridor_m

    def recommend(
        self,
        query: JourneyQuery,
        *,
        require_confirmed_open: bool = False,
    ) -> JourneyRecommendationResult:
        self._runtime.refresh()

        vehicle = self._vehicles.get(query.vehicle_id)
        direct_route = self._routing.route(query.origin, query.destination)

        items: list[RecommendationItem] = []
        exclusions: list[CandidateExclusion] = []
        stations = self._stations.candidates(
            query.origin.lon,
            query.origin.lat,
            query.destination.lon,
            query.destination.lat,
            self._candidate_corridor_m,
        )
        for station in stations:
            if require_confirmed_open and not is_confirmed_open(station):
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("OPENING_HOURS_UNVERIFIED",),
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

            compatibility = check_compatibility(vehicle, station)
            if not compatibility.compatible:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=compatibility.reason_codes,
                    )
                )
                continue

            try:
                status = self._runtime.get(station.station_id)
            except KeyError:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("TELEMETRY_UNAVAILABLE",),
                    )
                )
                continue
            if status.operational_ports == 0:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("STATION_OFFLINE",),
                    )
                )
                continue

            max_reachable_m = max(
                0.0,
                (query.initial_soc - vehicle.reserve_soc)
                * vehicle.calculation_battery_kwh
                / vehicle.consumption_wh_km
                * 1_000_000,
            )
            lon, lat = station.geometry.coordinates
            if _haversine_m(query.origin.lat, query.origin.lon, lat, lon) > max_reachable_m:
                exclusions.append(
                    CandidateExclusion(
                        station_id=station.station_id,
                        reason_codes=("INSUFFICIENT_SOC_RESERVE",),
                    )
                )
                continue

            try:
                route = self._routing.route(
                    query.origin,
                    query.destination,
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
                initial_soc=query.initial_soc,
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

            eta_at = query.departure_at + timedelta(seconds=duration_to_station_s)
            arrival = self._forecasting.forecast_arrival(
                status, arrival_min=duration_to_station_s / 60
            )
            forecast = arrival.at_arrival
            try:
                wait = self._wait_estimator.estimate_wait(
                    status,
                    arrival,
                    evaluation_at=eta_at,
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
                target_soc=query.target_soc,
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
            preference = query.preference
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
                    wait_distribution=wait.wait_distribution,
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
            generated_at=query.departure_at,
            vehicle_id=vehicle.vehicle_id,
            direct_route=direct_route,
            recommendations=ranked,
            excluded_candidates=tuple(exclusions),
        )

    @staticmethod
    def _lower_is_better(value: float, maximum: float) -> float:
        return 1 - min(1.0, max(0.0, value) / maximum)
