"""Trip API orchestration around a short-lived search and durable trip record."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.app.api_v1_models import (
    ApiPoint,
    SearchRouteRequest,
    SearchStationOption,
    SearchStationsRequest,
    SearchStationsResponse,
    TripActionRequest,
    TripCreateRequest,
    TripPositionRequest,
    TripResponse,
)
from backend.app.app_config_repository import AppConfigRepository
from backend.app.domain.routing import _haversine_m
from backend.app.domain.search import SearchService
from backend.app.domain.trips import distance_to_route_m
from backend.app.search_store import SearchResultStore, SearchSnapshot
from backend.app.trip_repository import DatabaseTripRepository


class TripService:
    def __init__(
        self,
        repository: DatabaseTripRepository,
        searches: SearchResultStore,
        config: AppConfigRepository,
        search_service: SearchService,
        stations,
        statuses,
        vehicles,
    ) -> None:
        self._repository = repository
        self._searches = searches
        self._config = config
        self._search_service = search_service
        self._stations = stations
        self._statuses = statuses
        self._vehicles = vehicles

    def create(self, payload: TripCreateRequest) -> TripResponse:
        snapshot = self._searches.get(payload.search_id)
        if not isinstance(snapshot, SearchSnapshot):
            raise ValueError("searchId does not contain a trip-ready search")
        request = snapshot.request
        response = snapshot.response
        vehicle = self._vehicles.get(request.vehicle_id)
        options = response.stations
        option = next(
            (item for item in options if item.station.id == payload.station_id), None
        )
        if isinstance(response, SearchStationsResponse):
            if option is None:
                raise ValueError("stationId must be one of the search results")
            route = option.route
            destination = None
        else:
            if response.case == "enough" and payload.station_id is None:
                route = response.direct_route
            elif option is not None:
                route = option.route
            else:
                raise ValueError("stationId must be one of the search results")
            destination = (
                request.destination if isinstance(request, SearchRouteRequest) else None
            )
        return self._repository.create(
            search_id=payload.search_id,
            vehicle_id=request.vehicle_id,
            origin=request.origin,
            destination=destination,
            battery_pct=request.battery_pct,
            battery_kwh=vehicle.calculation_battery_kwh,
            consumption_wh_km=vehicle.consumption_wh_km,
            target_battery_pct=vehicle.default_target_soc * 100,
            route=route,
            option=option,
            created_at=datetime.now(UTC),
        )

    def get(self, trip_id: str) -> TripResponse:
        return self._repository.get(trip_id)

    def position(self, trip_id: str, payload: TripPositionRequest) -> TripResponse:
        config = self._config.read()
        before = self._repository.snapshot(trip_id)
        station_available = True
        if before["station_code"] is not None:
            try:
                station_available = (
                    self._statuses.get(before["station_code"]).operational_ports > 0
                )
            except KeyError:
                station_available = False
        updated = self._repository.record_position(
            trip_id,
            location=payload.location,
            recorded_at=payload.recorded_at,
            battery_pct=payload.battery_pct,
            speed_kmh=payload.speed_kmh,
            heading=payload.heading,
            near_station_m=config.near_station_radius_m,
            arrival_m=config.arrival_radius_m,
            allow_station_arrival=station_available,
        )
        if updated.position_accepted is not True or updated.phase not in {
            "to_station", "to_destination"
        }:
            return updated
        reasons: list[str] = []
        deviation = distance_to_route_m(
            lat=payload.location.lat, lng=payload.location.lng,
            geometry=updated.route.geometry,
        )
        if deviation > config.reroute_deviation_m:
            reasons.append("OFF_ROUTE")
        if (
            updated.eta_at is not None
            and before["planned"].get("etaAt")
            and updated.eta_at - datetime.fromisoformat(before["planned"]["etaAt"])
            > timedelta(minutes=config.reroute_eta_delta_min)
        ):
            reasons.append("ETA_INCREASED")
        if updated.station_id is not None:
            if not station_available:
                reasons.append("STATION_UNAVAILABLE")
            target = self._stations.get(updated.station_id)
            target_lng, target_lat = target.geometry.coordinates
        else:
            target_lng = before["destination_lng"]
            target_lat = before["destination_lat"]
        if target_lng is not None and target_lat is not None:
            vehicle = self._vehicles.get(updated.vehicle_id)
            lower_bound_km = _haversine_m(
                payload.location.lat, payload.location.lng, target_lat, target_lng
            ) / 1000
            needed_pct = (
                vehicle.reserve_soc * 100
                + lower_bound_km * vehicle.consumption_wh_km
                / 1000 / vehicle.calculation_battery_kwh * 100
            )
            if updated.battery_pct < needed_pct:
                reasons.append("INSUFFICIENT_BATTERY")
        if not reasons:
            return updated
        try:
            rerouted = self._reroute(
                trip_id, before=before, origin=payload.location,
                battery_pct=updated.battery_pct,
                evaluated_at=payload.recorded_at,
                exclude_current="STATION_UNAVAILABLE" in reasons,
                cooldown_sec=config.reroute_cooldown_sec,
            )
        except (KeyError, RuntimeError, ValueError):
            return updated.model_copy(update={"reroute_reasons": tuple(reasons)})
        return rerouted.model_copy(
            update={"position_accepted": True, "reroute_reasons": tuple(reasons)}
        )

    def action(self, trip_id: str, payload: TripActionRequest) -> TripResponse:
        if payload.action in {"accept", "decline"}:
            before = self._repository.snapshot(trip_id)
            if before["phase"] not in {"to_station", "to_destination"}:
                raise ValueError(f"cannot change station in phase {before['phase']}")
            if payload.action == "decline" and before["station_code"] is None:
                raise ValueError("trip has no station to decline")
            if payload.action == "accept" and payload.station_id is None:
                raise ValueError("stationId is required")
            origin = ApiPoint(
                lat=(
                    before["last_lat"] if before["last_lat"] is not None
                    else before["origin_lat"]
                ),
                lng=(
                    before["last_lng"] if before["last_lng"] is not None
                    else before["origin_lng"]
                ),
            )
            return self._reroute(
                trip_id, before=before, origin=origin,
                battery_pct=before["planned"]["batteryPct"],
                evaluated_at=datetime.now(UTC),
                exclude_current=payload.action == "decline",
                requested_station_id=payload.station_id,
                declined_station_id=(
                    before["station_code"] if payload.action == "decline" else None
                ),
                cooldown_sec=0,
            )
        return self._repository.transition(
            trip_id,
            action=payload.action,
            now=datetime.now(UTC),
            battery_pct=payload.battery_pct,
        )

    def _reroute(
        self, trip_id: str, *, before, origin: ApiPoint, battery_pct: float,
        evaluated_at: datetime, exclude_current: bool,
        cooldown_sec: int, requested_station_id: str | None = None,
        declined_station_id: str | None = None,
    ) -> TripResponse:
        declined = set(before["declined_station_codes"])
        if exclude_current and before["station_code"] is not None:
            declined.add(before["station_code"])
        if before["mode"] == "find_station":
            result = self._search_service.search_stations(
                SearchStationsRequest(
                    origin=origin,
                    vehicle_id=before["planned"]["vehicleId"],
                    battery_pct=battery_pct,
                    limit=25,
                ),
                now=evaluated_at,
            )
            direct_route = None
        else:
            result = self._search_service.search_route(
                SearchRouteRequest(
                    origin=origin,
                    destination=ApiPoint(
                        lat=before["destination_lat"],
                        lng=before["destination_lng"],
                    ),
                    vehicle_id=before["planned"]["vehicleId"],
                    battery_pct=battery_pct,
                    limit=25,
                ),
                now=evaluated_at,
            )
            direct_route = result.direct_route if result.case == "enough" else None
        options = [
            option for option in result.stations
            if option.station.id not in declined
        ]
        option: SearchStationOption | None
        if requested_station_id is not None:
            option = next(
                (item for item in options if item.station.id == requested_station_id),
                None,
            )
            if option is None:
                raise ValueError("stationId is not an available re-plan option")
        elif direct_route is not None:
            option = None
        else:
            option = next(
                (item for item in options if item.station.id == before["station_code"]),
                None,
            ) if not exclude_current else None
            if option is None:
                option = options[0] if options else None
            if option is None:
                raise ValueError("no reachable re-plan option")
        return self._repository.change_route(
            trip_id,
            route=option.route if option is not None else direct_route,
            option=option,
            evaluated_at=evaluated_at,
            cooldown_sec=cooldown_sec,
            declined_station_id=declined_station_id,
        )
