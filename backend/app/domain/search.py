"""General station and route search built on the existing domain services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.api_v1_models import (
    ApiPoint,
    SearchExclusion,
    SearchRouteRequest,
    SearchRouteResponse,
    SearchRouteSummary,
    SearchStationOption,
    SearchStationsRequest,
    SearchStationsResponse,
    StationSummary,
)
from backend.app.app_config_repository import AppConfigRepository
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.phase7_models import (
    DemoScenario,
    GeoPoint,
    RecommendationPreference,
)
from backend.app.domain.recommendation import RecommendationService
from backend.app.domain.routing import RoutingService, _haversine_m
from backend.app.domain.runtime import RuntimeStateStore
from backend.app.domain.services import check_compatibility, estimate_charging
from backend.app.domain.station_hours import is_confirmed_open
from backend.app.domain.wait_estimation import WaitEstimator
from backend.app.search_store import SearchResultStore


class SearchService:
    def __init__(
        self,
        recommendation: RecommendationService,
        routing: RoutingService,
        vehicles,
        stations,
        statuses,
        runtime: RuntimeStateStore,
        planned_arrivals,
        forecasting: OccupancyForecastService,
        wait_estimator: WaitEstimator,
        store: SearchResultStore,
        availability_green_min: int,
        config_repository: AppConfigRepository | None = None,
    ) -> None:
        self._recommendation = recommendation
        self._routing = routing
        self._vehicles = vehicles
        self._stations = stations
        self._statuses = statuses
        self._runtime = runtime
        self._planned_arrivals = planned_arrivals
        self._forecasting = forecasting
        self._wait_estimator = wait_estimator
        self._store = store
        self._availability_green_min = availability_green_min
        self._config_repository = config_repository

    @staticmethod
    def _point(point: ApiPoint) -> GeoPoint:
        return GeoPoint(lat=point.lat, lon=point.lng)

    @staticmethod
    def _route_summary(route) -> SearchRouteSummary:
        return SearchRouteSummary(
            route_id=route.route_id,
            provider=route.provider,
            distance_km=route.distance_m / 1000,
            travel_min=route.duration_s / 60,
            geometry=route.geometry.coordinates,
        )

    def _station_summary(self, station_id: str):
        station = self._stations.get(station_id)
        status = self._statuses.get(station_id)
        lon, lat = station.geometry.coordinates
        green_min = (
            self._config_repository.read().availability_green_min
            if self._config_repository is not None
            else self._availability_green_min
        )
        if status.total_ports == 0 or status.unknown_ports == status.total_ports:
            color = "grey"
        elif status.available_ports == 0:
            color = "red"
        elif status.available_ports < green_min:
            color = "yellow"
        else:
            color = "green"
        return StationSummary(
            id=station_id,
            name=station.properties.name,
            address=station.properties.address,
            location=ApiPoint(lat=lat, lng=lon),
            color=color,
            available_ports=status.available_ports,
            total_ports=status.total_ports,
            connectors=tuple(item.type for item in station.properties.connectors),
            updated_at=status.timestamp,
        )

    def _nearest_station(self, origin: ApiPoint, vehicle):
        eligible = (
            station
            for station in self._stations.all()
            if station.properties.access == "public"
            and is_confirmed_open(station)
            and check_compatibility(vehicle, station).compatible
        )
        nearest = min(
            eligible,
            key=lambda station: _haversine_m(
                origin.lat,
                origin.lng,
                station.geometry.coordinates[1],
                station.geometry.coordinates[0],
            ),
            default=None,
        )
        if nearest is None:
            return None, None
        distance_km = _haversine_m(
            origin.lat,
            origin.lng,
            nearest.geometry.coordinates[1],
            nearest.geometry.coordinates[0],
        ) / 1000
        return self._station_summary(nearest.station_id), distance_km

    def _scenario(
        self,
        *,
        origin: ApiPoint,
        destination: ApiPoint,
        vehicle_id: str,
        battery_pct: float,
        departure_at: datetime,
    ) -> DemoScenario:
        vehicle = self._vehicles.get(vehicle_id)
        return DemoScenario(
            scenario_id="GENERAL_SEARCH",
            name="General API search",
            vehicle_id=vehicle_id,
            initial_soc=battery_pct / 100,
            target_soc=vehicle.default_target_soc,
            origin=self._point(origin),
            destination=self._point(destination),
            departure_at=departure_at,
            preference=RecommendationPreference(
                wait_weight=0.25,
                detour_weight=0.25,
                charging_time_weight=0.25,
                soc_risk_weight=0.25,
            ),
            event_ids=(),
            route_ids=(),
        )

    def search_route(
        self, payload: SearchRouteRequest, *, now: datetime | None = None
    ) -> SearchRouteResponse:
        generated_at = now or datetime.now(UTC)
        vehicle = self._vehicles.get(payload.vehicle_id)
        direct = self._routing.route(
            self._point(payload.origin), self._point(payload.destination)
        )
        direct_energy_kwh = (
            direct.distance_m / 1000 * vehicle.consumption_wh_km / 1000
        )
        arrival_soc = payload.battery_pct / 100 - (
            direct_energy_kwh / vehicle.calculation_battery_kwh
        )
        reachable_km = max(
            0.0,
            (payload.battery_pct / 100 - vehicle.reserve_soc)
            * vehicle.calculation_battery_kwh
            / vehicle.consumption_wh_km
            * 1000,
        )
        if arrival_soc >= vehicle.reserve_soc:
            provisional = SearchRouteResponse(
                search_id="pending",
                case="enough",
                direct_route=self._route_summary(direct),
                direct_min=direct.duration_s / 60,
                stations=(),
                updated_at=generated_at,
            )
        else:
            recommendation = self._recommendation.recommend_scenario(
                self._scenario(
                    origin=payload.origin,
                    destination=payload.destination,
                    vehicle_id=payload.vehicle_id,
                    battery_pct=payload.battery_pct,
                    departure_at=generated_at,
                ),
                require_confirmed_open=True,
            )
            options = []
            exclusions = [
                SearchExclusion(
                    station_id=item.station_id,
                    reason_codes=item.reason_codes,
                )
                for item in recommendation.excluded_candidates
            ]
            for item in recommendation.recommendations:
                travel_min = item.route_duration_to_station_s / 60
                to_dest_min = max(0.0, item.route.duration_s / 60 - travel_min)
                to_dest_distance_km = max(
                    0.0,
                    (item.route.distance_m - item.route_distance_to_station_m) / 1000,
                )
                required_soc = vehicle.reserve_soc + (
                    to_dest_distance_km * vehicle.consumption_wh_km / 1000
                    / vehicle.calculation_battery_kwh
                )
                if required_soc > 1:
                    exclusions.append(
                        SearchExclusion(
                            station_id=item.station_id,
                            reason_codes=("DESTINATION_OUT_OF_RANGE",),
                        )
                    )
                    continue
                charging = estimate_charging(
                    vehicle,
                    self._stations.get(item.station_id),
                    arrival_soc=item.arrival_soc,
                    target_soc=required_soc,
                    effective_power_kw=item.effective_power_kw,
                )
                total_min = (
                    travel_min
                    + item.estimated_wait_min
                    + charging.estimated_charge_min
                    + to_dest_min
                )
                options.append(
                    SearchStationOption(
                        rank=1,
                        station=self._station_summary(item.station_id),
                        route=self._route_summary(item.route),
                        distance_km=item.route_distance_to_station_m / 1000,
                        travel_min=travel_min,
                        wait_min=item.estimated_wait_min,
                        charge_min=charging.estimated_charge_min,
                        to_dest_min=to_dest_min,
                        total_min=total_min,
                        arrive_battery_pct=item.arrival_soc * 100,
                        prediction_source=item.prediction_source,
                        flags=item.flags,
                    )
                )
            ordered = sorted(options, key=lambda item: (item.total_min, item.station.id))
            ranked = tuple(
                item.model_copy(update={"rank": index})
                for index, item in enumerate(ordered[: payload.limit], start=1)
            )
            nearest, nearest_km = self._nearest_station(payload.origin, vehicle)
            provisional = SearchRouteResponse(
                search_id="pending",
                case="needCharge" if ranked else "fallback",
                direct_route=self._route_summary(direct),
                direct_min=direct.duration_s / 60,
                stations=ranked,
                excluded_candidates=tuple(exclusions),
                missing_km=(
                    None if ranked or nearest_km is None
                    else max(0.0, nearest_km - reachable_km)
                ),
                nearest_station=None if ranked else nearest,
                updated_at=generated_at,
            )
        search_id = self._store.put(provisional, created_at=generated_at)
        result = provisional.model_copy(update={"search_id": search_id})
        self._store.set(search_id, result, created_at=generated_at)
        return result

    def search_stations(
        self, payload: SearchStationsRequest, *, now: datetime | None = None
    ) -> SearchStationsResponse:
        generated_at = now or datetime.now(UTC)
        vehicle = self._vehicles.get(payload.vehicle_id)
        reachable_km = max(
            0.0,
            (payload.battery_pct / 100 - vehicle.reserve_soc)
            * vehicle.calculation_battery_kwh
            / vehicle.consumption_wh_km
            * 1000,
        )
        self._runtime.refresh()
        candidates = self._stations.nearby(
            payload.origin.lng, payload.origin.lat, reachable_km * 1000
        )
        planned_arrivals = self._planned_arrivals.active_for_stations(
            tuple(station.station_id for station in candidates)
        )
        options: list[SearchStationOption] = []
        exclusions: list[SearchExclusion] = []
        for station in candidates:
            if station.properties.access != "public":
                exclusions.append(
                    SearchExclusion(
                        station_id=station.station_id,
                        reason_codes=("NON_PUBLIC_ACCESS",),
                    )
                )
                continue
            if not is_confirmed_open(station):
                exclusions.append(
                    SearchExclusion(
                        station_id=station.station_id,
                        reason_codes=("OPENING_HOURS_UNVERIFIED",),
                    )
                )
                continue
            compatibility = check_compatibility(vehicle, station)
            if not compatibility.compatible:
                exclusions.append(
                    SearchExclusion(
                        station_id=station.station_id,
                        reason_codes=compatibility.reason_codes,
                    )
                )
                continue
            try:
                status = self._runtime.get(station.station_id)
            except KeyError:
                exclusions.append(
                    SearchExclusion(
                        station_id=station.station_id,
                        reason_codes=("TELEMETRY_UNAVAILABLE",),
                    )
                )
                continue
            if status.operational_ports == 0:
                exclusions.append(
                    SearchExclusion(
                        station_id=station.station_id,
                        reason_codes=("STATION_OFFLINE",),
                    )
                )
                continue
            lon, lat = station.geometry.coordinates
            try:
                route = self._routing.route_to_station(
                    self._point(payload.origin),
                    GeoPoint(lat=lat, lon=lon),
                    station.station_id,
                )
            except RuntimeError:
                exclusions.append(
                    SearchExclusion(
                        station_id=station.station_id,
                        reason_codes=("ROUTE_NOT_AVAILABLE",),
                    )
                )
                continue
            direct_energy = route.distance_m / 1000 * vehicle.consumption_wh_km / 1000
            arrival_pct = (
                payload.battery_pct / 100
                - direct_energy / vehicle.calculation_battery_kwh
            ) * 100
            if arrival_pct < vehicle.reserve_soc * 100:
                exclusions.append(
                    SearchExclusion(
                        station_id=station.station_id,
                        reason_codes=("INSUFFICIENT_SOC_RESERVE",),
                    )
                )
                continue
            travel_min = route.duration_s / 60
            forecast = self._forecasting.forecast_occupancy(
                status, horizon_min=max(1, round(travel_min))
            )
            try:
                wait = self._wait_estimator.estimate_wait(
                    status,
                    forecast,
                    evaluation_at=generated_at + timedelta(minutes=travel_min),
                    planned_arrivals=planned_arrivals,
                    scenario_id=None,
                )
            except (KeyError, ValueError):
                exclusions.append(
                    SearchExclusion(
                        station_id=station.station_id,
                        reason_codes=("WAIT_INPUT_UNAVAILABLE",),
                    )
                )
                continue
            charging = estimate_charging(
                vehicle,
                station,
                arrival_soc=arrival_pct / 100,
                effective_power_kw=compatibility.effective_power_kw,
            )
            total_min = travel_min + wait.estimated_wait_min + charging.estimated_charge_min
            options.append(
                SearchStationOption(
                    rank=1,
                    station=self._station_summary(station.station_id),
                    route=self._route_summary(route),
                    distance_km=route.distance_m / 1000,
                    travel_min=travel_min,
                    wait_min=wait.estimated_wait_min,
                    charge_min=charging.estimated_charge_min,
                    total_min=total_min,
                    arrive_battery_pct=arrival_pct,
                    prediction_source=forecast.prediction_source,
                    flags=tuple(dict.fromkeys((*forecast.flags, *wait.flags))),
                )
            )
        ordered = sorted(options, key=lambda item: (item.total_min, item.station.id))
        ranked = tuple(
            item.model_copy(update={"rank": index})
            for index, item in enumerate(ordered[: payload.limit], start=1)
        )
        nearest, nearest_km = self._nearest_station(payload.origin, vehicle)
        provisional = SearchStationsResponse(
            search_id="pending",
            reachable_km=reachable_km,
            stations=ranked,
            excluded_candidates=tuple(exclusions),
            nearest_station=None if ranked else nearest,
            missing_km=(
                None if ranked or nearest_km is None
                else max(0.0, nearest_km - reachable_km)
            ),
            updated_at=generated_at,
        )
        search_id = self._store.put(provisional, created_at=generated_at)
        result = provisional.model_copy(update={"search_id": search_id})
        self._store.set(search_id, result, created_at=generated_at)
        return result
