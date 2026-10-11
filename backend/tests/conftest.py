from __future__ import annotations

import math
import os

import pytest

os.environ.setdefault("CATALOG_STORAGE", "memory")

from backend.app.domain.phase7_models import (  # noqa: E402
    GeoPoint,
    LineStringGeometry,
    RouteResult,
    RouteWaypoint,
)


def _haversine_m(a: GeoPoint, b: GeoPoint) -> float:
    radius = 6_371_000
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    d_phi = math.radians(b.lat - a.lat)
    d_lambda = math.radians(b.lon - a.lon)
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(value), math.sqrt(1 - value))


class StraightLineRoutingProvider:
    """Offline routing double: straight legs x1.35 road factor at 30 km/h."""

    def route(
        self,
        origin: GeoPoint,
        destination: GeoPoint,
        waypoints: tuple[RouteWaypoint, ...],
    ) -> RouteResult:
        points = [origin, *waypoints, destination]
        distance_m = 1.35 * sum(
            _haversine_m(start, end) for start, end in zip(points, points[1:], strict=False)
        )
        distance_m = max(distance_m, 1.0)
        return RouteResult(
            route_id=f"TEST_{abs(hash(tuple((p.lat, p.lon) for p in points))) % 10**10}",
            provider="osrm",
            origin=origin,
            destination=destination,
            waypoints=waypoints,
            geometry=LineStringGeometry(
                type="LineString",
                coordinates=tuple((point.lon, point.lat) for point in points),
            ),
            distance_m=distance_m,
            duration_s=max(distance_m / (30 / 3.6), 1.0),
            flags=(),
        )


@pytest.fixture(autouse=True)
def offline_routing():
    """Give the application's routing service an offline provider for every test."""
    from backend.app.main import app

    service = app.state.routing_service
    previous = (service._goong, service._osrm)
    service._goong = StraightLineRoutingProvider()
    service._osrm = None
    try:
        yield
    finally:
        service._goong, service._osrm = previous
