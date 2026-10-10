"""Cache-first routing with Goong primary and public OSRM fallback providers."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from backend.app.domain.geo import haversine_m as _haversine_m
from backend.app.domain.phase7_models import (
    GeoPoint,
    LineStringGeometry,
    RouteLeg,
    RouteResult,
    RouteWaypoint,
)
from backend.app.domain.provider_http import get_with_retry
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
        response = get_with_retry(
            self._client, "https://rsapi.goong.io/Direction", params=params
        )
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
        retrieved_at = datetime.now(UTC)
        route_legs = (
            tuple(
                RouteLeg(
                    origin=start,
                    destination=end,
                    distance_m=float(leg["distance"]["value"]),
                    duration_s=float(leg["duration"]["value"]),
                    provider="goong",
                    retrieved_at=retrieved_at,
                )
                for start, end, leg in zip(points[:-1], points[1:], legs, strict=True)
            )
            if len(legs) == len(points) - 1
            else ()
        )
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
            legs=route_legs,
            flags=(),
        )


class OsrmRoutingProvider:
    def __init__(
        self,
        *,
        base_url: str = "https://router.project-osrm.org",
        timeout_s: float = 8,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_s)

    def route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        waypoints: tuple[RouteWaypoint, ...],
    ) -> RouteResult:
        points: tuple[GeoPoint, ...] = (origin, *waypoints, destination)
        coordinate_path = ";".join(f"{point.lon},{point.lat}" for point in points)
        response = get_with_retry(
            self._client,
            f"{self._base_url}/route/v1/driving/{coordinate_path}",
            params={"overview": "full", "geometries": "geojson", "steps": "false"},
        )
        payload: dict[str, Any] = response.json()
        if payload.get("code") != "Ok" or not payload.get("routes"):
            raise RuntimeError("OSRM returned no route")
        route = payload["routes"][0]
        legs = route.get("legs", [])
        retrieved_at = datetime.now(UTC)
        route_legs = (
            tuple(
                RouteLeg(
                    origin=start,
                    destination=end,
                    distance_m=float(leg["distance"]),
                    duration_s=float(leg["duration"]),
                    provider="osrm",
                    retrieved_at=retrieved_at,
                )
                for start, end, leg in zip(points[:-1], points[1:], legs, strict=True)
            )
            if len(legs) == len(points) - 1
            else ()
        )
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
            legs=route_legs,
            flags=("OSRM_FALLBACK",),
        )


class RoutingService:
    def __init__(
        self,
        routes: RouteRepository,
        *,
        goong: RoutingProvider | None,
        osrm: RoutingProvider | None,
        require_leg_metrics: bool = False,
        record_provider_event: Callable[[str, str], None] | None = None,
    ) -> None:
        self._routes = routes
        self._goong = goong
        self._osrm = osrm
        self._require_leg_metrics = require_leg_metrics
        self._record_provider_event = record_provider_event

    def route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        waypoints: tuple[RouteWaypoint, ...] = (),
        *,
        preferred_route_id: str | None = None,
    ) -> RouteResult:
        cached_result = (
            self._from_cache(preferred_route_id)
            if preferred_route_id is not None
            else None
        )
        if cached_result is None:
            cached = self._find_exact_cache(origin, destination, waypoints)
            if cached is not None:
                cached_result = self._from_cache(cached.route_id)
        if cached_result is not None and (
            not self._require_leg_metrics or has_complete_leg_metrics(cached_result)
        ):
            return cached_result

        flags: list[str] = (
            ["ROUTE_CACHE_LEG_METRICS_UNAVAILABLE"]
            if cached_result is not None
            else []
        )
        if self._goong is not None:
            try:
                result = self._goong.route(origin, destination, waypoints)
            except Exception:
                self._record_provider("goong", "failure")
                flags.append("GOONG_FAILED")
            else:
                if self._require_leg_metrics and not has_complete_leg_metrics(
                    result, waypoints
                ):
                    self._record_provider("goong", "failure")
                    flags.append("GOONG_LEG_METRICS_UNAVAILABLE")
                else:
                    self._record_provider("goong", "success")
                    return result
        else:
            self._record_provider("goong", "not_configured")
            flags.append("GOONG_NOT_CONFIGURED")

        if self._osrm is not None:
            try:
                result = self._osrm.route(origin, destination, waypoints)
            except Exception:
                self._record_provider("osrm", "failure")
                flags.append("OSRM_FAILED")
            else:
                if self._require_leg_metrics and not has_complete_leg_metrics(
                    result, waypoints
                ):
                    self._record_provider("osrm", "failure")
                    flags.append("OSRM_LEG_METRICS_UNAVAILABLE")
                else:
                    self._record_provider(
                        "osrm",
                        "fallback"
                        if {
                            "GOONG_FAILED",
                            "GOONG_NOT_CONFIGURED",
                            "GOONG_LEG_METRICS_UNAVAILABLE",
                        }.intersection(flags)
                        else "success",
                    )
                    return result.model_copy(
                        update={"flags": tuple([*flags, *result.flags])}
                    )
        if cached_result is not None and not self._require_leg_metrics:
            return cached_result.model_copy(update={"flags": tuple(flags)})
        raise RuntimeError(f"routing unavailable ({', '.join(flags)})")

    def _record_provider(self, provider: str, event: str) -> None:
        if self._record_provider_event is not None:
            self._record_provider_event(provider, event)

    def cached_route(self, route_id: str) -> RouteResult:
        result = self._from_cache(route_id)
        if self._require_leg_metrics and not has_complete_leg_metrics(result):
            raise RuntimeError("cached route has no complete per-leg metrics")
        return result

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
            legs=route.legs,
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


def route_metrics_to_station(route: RouteResult, station_id: str) -> tuple[float, float]:
    waypoint = next(
        (waypoint for waypoint in route.waypoints if waypoint.station_id == station_id),
        None,
    )
    if waypoint is None:
        raise ValueError(f"route {route.route_id} has no waypoint for {station_id}")

    waypoint_index = route.waypoints.index(waypoint)
    if len(route.legs) == len(route.waypoints) + 1:
        return (
            sum(leg.distance_m for leg in route.legs[: waypoint_index + 1]),
            sum(leg.duration_s for leg in route.legs[: waypoint_index + 1]),
        )

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


def has_complete_leg_metrics(
    route: RouteResult,
    requested_waypoints: tuple[RouteWaypoint, ...] | None = None,
) -> bool:
    # A direct route's whole-route metrics are its single leg. Waypoint routes
    # need provider-reported metrics for every segment.
    waypoints = route.waypoints if requested_waypoints is None else requested_waypoints
    return not waypoints or len(route.legs) == len(waypoints) + 1
