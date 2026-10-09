"""Cache-first routing with Goong primary and public OSRM fallback providers."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Protocol

import httpx

from backend.app.domain.phase7_models import (
    GeoPoint,
    LineStringGeometry,
    RouteResult,
    RouteWaypoint,
)
from backend.app.domain.repositories import RouteRepository


class RoutingProvider(Protocol):
    def route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        waypoints: tuple[RouteWaypoint, ...],
    ) -> RouteResult: ...


def _route_id(prefix: str, points: tuple[GeoPoint, ...]) -> str:
    payload = ";".join(f"{point.lat:.7f},{point.lon:.7f}" for point in points)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:12].upper()
    return f"{prefix}_{digest}"


def _decode_polyline(encoded: str, precision: int = 5) -> tuple[tuple[float, float], ...]:
    coordinates: list[tuple[float, float]] = []
    latitude = 0
    longitude = 0
    index = 0
    factor = 10**precision
    while index < len(encoded):
        deltas: list[int] = []
        for _ in range(2):
            result = 0
            shift = 0
            while True:
                if index >= len(encoded):
                    raise ValueError("invalid encoded route polyline")
                value = ord(encoded[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += deltas[0]
        longitude += deltas[1]
        coordinates.append((longitude / factor, latitude / factor))
    return tuple(coordinates)


class GoongRoutingProvider:
    def __init__(
        self,
        api_key: str,
        *,
        timeout_s: float = 8,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_s)

    def route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        waypoints: tuple[RouteWaypoint, ...],
    ) -> RouteResult:
        destinations = (*waypoints, destination)
        params: dict[str, str] = {
            "origin": f"{origin.lat},{origin.lon}",
            "destination": ";".join(
                f"{point.lat},{point.lon}" for point in destinations
            ),
            "vehicle": "car",
            "api_key": self._api_key,
        }
        response = self._client.get("https://rsapi.goong.io/Direction", params=params)
        response.raise_for_status()
        payload = response.json()
        routes = payload.get("routes", [])
        if not routes:
            raise RuntimeError("Goong returned no route")
        route = routes[0]
        legs = route.get("legs", [])
        distance_m = sum(float(leg["distance"]["value"]) for leg in legs)
        duration_s = sum(float(leg["duration"]["value"]) for leg in legs)
        encoded = route.get("overview_polyline", {}).get("points")
        if not encoded:
            raise RuntimeError("Goong route has no overview polyline")
        points: tuple[GeoPoint, ...] = (origin, *waypoints, destination)
        return RouteResult(
            route_id=_route_id("LIVE_GOONG", points),
            provider="goong",
            resolution_source="live",
            origin=origin,
            destination=destination,
            waypoints=waypoints,
            geometry=LineStringGeometry(
                type="LineString", coordinates=_decode_polyline(encoded)
            ),
            distance_m=distance_m,
            duration_s=duration_s,
            flags=(),
        )


class OsrmRoutingProvider:
    def __init__(
        self,
        *,
        timeout_s: float = 8,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout_s)

    def route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        waypoints: tuple[RouteWaypoint, ...],
    ) -> RouteResult:
        points: tuple[GeoPoint, ...] = (origin, *waypoints, destination)
        coordinate_path = ";".join(f"{point.lon},{point.lat}" for point in points)
        response = self._client.get(
            f"https://router.project-osrm.org/route/v1/driving/{coordinate_path}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise RuntimeError("OSRM returned no route")
        route = payload["routes"][0]
        return RouteResult(
            route_id=_route_id("LIVE_OSRM", points),
            provider="osrm",
            resolution_source="live",
            origin=origin,
            destination=destination,
            waypoints=waypoints,
            geometry=LineStringGeometry.model_validate(route["geometry"]),
            distance_m=route["distance"],
            duration_s=route["duration"],
            flags=("OSRM_FALLBACK",),
        )


class RoutingService:
    def __init__(
        self,
        routes: RouteRepository,
        *,
        goong: RoutingProvider | None,
        osrm: RoutingProvider | None,
    ) -> None:
        self._routes = routes
        self._goong = goong
        self._osrm = osrm

    def route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        waypoints: tuple[RouteWaypoint, ...] = (),
        *,
        preferred_route_id: str | None = None,
    ) -> RouteResult:
        if preferred_route_id is not None:
            return self.cached_route(preferred_route_id)

        cached = self._find_exact_cache(origin, destination, waypoints)
        if cached is not None:
            return self._from_cache(cached.route_id)

        flags: list[str] = []
        if self._goong is not None:
            try:
                return self._goong.route(origin, destination, waypoints)
            except Exception:
                flags.append("GOONG_FAILED")
        else:
            flags.append("GOONG_NOT_CONFIGURED")

        if self._osrm is not None:
            try:
                result = self._osrm.route(origin, destination, waypoints)
                return result.model_copy(update={"flags": tuple([*flags, *result.flags])})
            except Exception:
                flags.append("OSRM_FAILED")
        raise RuntimeError(f"routing unavailable ({', '.join(flags)})")

    def cached_route(self, route_id: str) -> RouteResult:
        return self._from_cache(route_id)

    def route_to_station(
        self, origin: GeoPoint, station: GeoPoint, station_id: str
    ) -> RouteResult:
        cached = self._routes.find_by_station(station_id)
        if cached is None or not self._same_point(cached.origin, origin):
            return self.route(origin, station)
        full = self._from_cache(cached.route_id)
        distance_m, duration_s = route_metrics_to_station(full, station_id)
        nearest_index = min(
            range(len(full.geometry.coordinates)),
            key=lambda index: _haversine_m(
                full.geometry.coordinates[index][1],
                full.geometry.coordinates[index][0],
                station.lat,
                station.lon,
            ),
        )
        coordinates = full.geometry.coordinates[: nearest_index + 1]
        if not coordinates or coordinates[-1] != (station.lon, station.lat):
            coordinates = (*coordinates, (station.lon, station.lat))
        if len(coordinates) < 2:
            coordinates = ((origin.lon, origin.lat), (station.lon, station.lat))
        return RouteResult(
            route_id=f"{full.route_id}_TO_{station_id}",
            provider=full.provider,
            resolution_source="cache",
            origin=origin,
            destination=station,
            waypoints=(),
            geometry=LineStringGeometry(type="LineString", coordinates=coordinates),
            distance_m=distance_m,
            duration_s=duration_s,
            flags=full.flags,
        )

    def _from_cache(self, route_id: str) -> RouteResult:
        route = self._routes.get(route_id)
        return RouteResult(
            route_id=route.route_id,
            provider=route.provider,
            resolution_source="cache",
            origin=route.origin,
            destination=route.destination,
            waypoints=route.waypoints,
            geometry=route.geometry,
            distance_m=route.distance_m,
            duration_s=route.duration_s,
            flags=("ROUTE_CACHE",),
        )

    def _find_exact_cache(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        waypoints: tuple[RouteWaypoint, ...],
    ):
        requested = (origin, *waypoints, destination)
        for route in self._routes.all():
            cached = (route.origin, *route.waypoints, route.destination)
            if len(requested) != len(cached):
                continue
            if all(
                abs(left.lat - right.lat) < 1e-6 and abs(left.lon - right.lon) < 1e-6
                for left, right in zip(requested, cached, strict=True)
            ):
                return route
        return None

    @staticmethod
    def _same_point(left: GeoPoint, right: GeoPoint) -> bool:
        return abs(left.lat - right.lat) < 1e-6 and abs(left.lon - right.lon) < 1e-6


def route_metrics_to_station(route: RouteResult, station_id: str) -> tuple[float, float]:
    waypoint = next(
        (waypoint for waypoint in route.waypoints if waypoint.station_id == station_id),
        None,
    )
    if waypoint is None:
        raise ValueError(f"route {route.route_id} has no waypoint for {station_id}")

    coordinates = route.geometry.coordinates
    nearest_index = min(
        range(len(coordinates)),
        key=lambda index: _haversine_m(
            coordinates[index][1],
            coordinates[index][0],
            waypoint.lat,
            waypoint.lon,
        ),
    )
    segment_lengths = [
        _haversine_m(start[1], start[0], end[1], end[0])
        for start, end in zip(coordinates, coordinates[1:], strict=False)
    ]
    geometry_total = sum(segment_lengths)
    if geometry_total <= 0:
        raise ValueError("route geometry has zero length")
    fraction = sum(segment_lengths[:nearest_index]) / geometry_total
    return route.distance_m * fraction, route.duration_s * fraction


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_m * math.atan2(math.sqrt(value), math.sqrt(1 - value))
