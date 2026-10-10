from datetime import UTC, datetime

import pytest

from backend.app.config import load_settings
from backend.app.domain.phase7_models import (
    GeoPoint,
    LineStringGeometry,
    RouteLeg,
    RouteResult,
    RouteWaypoint,
)
from backend.app.domain.repositories import load_domain_data
from backend.app.domain.routing import (
    GoongRoutingProvider,
    OsrmRoutingProvider,
    RoutingService,
    route_metrics_to_station,
)


class FailingProvider:
    def route(self, origin, destination, waypoints):
        raise RuntimeError("provider unavailable")


class StaticOsrmProvider:
    def route(self, origin, destination, waypoints):
        return RouteResult(
            route_id="LIVE_TEST",
            provider="osrm",
            resolution_source="live",
            origin=origin,
            destination=destination,
            waypoints=waypoints,
            geometry=LineStringGeometry(
                type="LineString",
                coordinates=((origin.lon, origin.lat), (destination.lon, destination.lat)),
            ),
            distance_m=1000,
            duration_s=120,
            flags=("OSRM_FALLBACK",),
        )


class CompleteLegMetricsProvider:
    def route(self, origin, destination, waypoints):
        points = (origin, *waypoints, destination)
        retrieved_at = datetime.now(UTC)
        legs = tuple(
            RouteLeg(
                origin=start,
                destination=end,
                distance_m=500,
                duration_s=60,
                provider="osrm",
                retrieved_at=retrieved_at,
            )
            for start, end in zip(points[:-1], points[1:], strict=True)
        )
        return RouteResult(
            route_id="LIVE_OSRM_LEGS",
            provider="osrm",
            resolution_source="live",
            origin=origin,
            destination=destination,
            waypoints=waypoints,
            geometry=LineStringGeometry(
                type="LineString",
                coordinates=((origin.lon, origin.lat), (destination.lon, destination.lat)),
            ),
            distance_m=1000,
            duration_s=120,
            legs=legs,
        )


class FakeResponse:
    status_code = 200
    headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "routes": [
                {
                    "legs": [
                        {"distance": {"value": 600}, "duration": {"value": 80}},
                        {"distance": {"value": 900}, "duration": {"value": 100}},
                    ],
                    "overview_polyline": {"points": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
                }
            ]
        }


class CapturingClient:
    def __init__(self):
        self.params = None

    def get(self, _url, *, params):
        self.params = params
        return FakeResponse()


def test_route_cache_returns_normalized_geometry_distance_and_duration() -> None:
    data = load_domain_data(load_settings().data_dir)
    service = RoutingService(data.routes, goong=None, osrm=None)

    result = service.cached_route("ROUTE_VIA_LAVIDA")
    distance, duration = route_metrics_to_station(result, "ST_EVO_LAVIDA_Q7")

    assert result.resolution_source == "cache"
    assert result.provider == "osrm"
    assert result.geometry.type == "LineString"
    assert result.distance_m > 0
    assert result.duration_s > 0
    assert 0 < distance < result.distance_m
    assert 0 < duration < result.duration_s


def test_goong_failure_uses_osrm_fallback_for_uncached_route() -> None:
    data = load_domain_data(load_settings().data_dir)
    provider_events = []
    service = RoutingService(
        data.routes,
        goong=FailingProvider(),
        osrm=StaticOsrmProvider(),
        record_provider_event=lambda provider, event: provider_events.append(
            (provider, event)
        ),
    )

    result = service.route(
        GeoPoint(lat=10.0, lon=106.0),
        GeoPoint(lat=10.1, lon=106.1),
        (RouteWaypoint(lat=10.05, lon=106.05),),
    )

    assert result.provider == "osrm"
    assert result.resolution_source == "live"
    assert "GOONG_FAILED" in result.flags
    assert "OSRM_FALLBACK" in result.flags
    assert provider_events == [("goong", "failure"), ("osrm", "fallback")]


def test_release_rejects_incomplete_live_metrics_and_uses_provider_fallback() -> None:
    data = load_domain_data(load_settings().data_dir)
    provider_events = []
    service = RoutingService(
        data.routes,
        goong=StaticOsrmProvider(),
        osrm=CompleteLegMetricsProvider(),
        require_leg_metrics=True,
        record_provider_event=lambda provider, event: provider_events.append(
            (provider, event)
        ),
    )

    result = service.route(
        GeoPoint(lat=10.0, lon=106.0),
        GeoPoint(lat=10.1, lon=106.1),
        (RouteWaypoint(lat=10.05, lon=106.05, station_id="ST_TEST"),),
    )

    assert result.route_id == "LIVE_OSRM_LEGS"
    assert len(result.legs) == 2
    assert "GOONG_LEG_METRICS_UNAVAILABLE" in result.flags
    assert provider_events == [("goong", "failure"), ("osrm", "fallback")]


def test_release_fails_closed_when_live_providers_omit_waypoint_metrics() -> None:
    data = load_domain_data(load_settings().data_dir)
    provider_events = []
    service = RoutingService(
        data.routes,
        goong=StaticOsrmProvider(),
        osrm=StaticOsrmProvider(),
        require_leg_metrics=True,
        record_provider_event=lambda provider, event: provider_events.append(
            (provider, event)
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="GOONG_LEG_METRICS_UNAVAILABLE, OSRM_LEG_METRICS_UNAVAILABLE",
    ):
        service.route(
            GeoPoint(lat=10.0, lon=106.0),
            GeoPoint(lat=10.1, lon=106.1),
            (RouteWaypoint(lat=10.05, lon=106.05, station_id="ST_TEST"),),
        )

    assert provider_events == [("goong", "failure"), ("osrm", "failure")]


def test_release_accepts_whole_route_metrics_without_waypoints() -> None:
    data = load_domain_data(load_settings().data_dir)
    service = RoutingService(
        data.routes,
        goong=StaticOsrmProvider(),
        osrm=None,
        require_leg_metrics=True,
    )

    result = service.route(
        GeoPoint(lat=10.0, lon=106.0),
        GeoPoint(lat=10.1, lon=106.1),
    )

    assert result.waypoints == ()
    assert result.duration_s == 120


def test_goong_serializes_waypoint_as_intermediate_destination() -> None:
    client = CapturingClient()
    provider = GoongRoutingProvider("test-key", client=client)
    origin = GeoPoint(lat=10.7, lon=106.7)
    destination = GeoPoint(lat=10.8, lon=106.8)
    waypoint = RouteWaypoint(
        lat=10.75, lon=106.75, station_id="ST_TEST"
    )

    result = provider.route(origin, destination, (waypoint,))

    assert client.params["destination"] == "10.75,106.75;10.8,106.8"
    assert "waypoints" not in client.params
    assert result.distance_m == 1500
    assert result.duration_s == 180
    assert len(result.legs) == 2
    distance, duration = route_metrics_to_station(result, "ST_TEST")
    assert (distance, duration) == (600, 80)


def test_osrm_uses_configured_base_url() -> None:
    class OsrmResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": "Ok",
                "routes": [
                    {
                        "distance": 1000,
                        "duration": 120,
                        "legs": [{"distance": 1000, "duration": 120}],
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[106.7, 10.7], [106.8, 10.8]],
                        },
                    }
                ],
            }

    class OsrmClient:
        url = None

        def get(self, url, *, params):
            self.url = url
            return OsrmResponse()

    client = OsrmClient()
    provider = OsrmRoutingProvider(
        base_url="https://routing.internal.test/osrm/",
        client=client,
    )
    provider.route(GeoPoint(lat=10.7, lon=106.7), GeoPoint(lat=10.8, lon=106.8), ())

    assert client.url == (
        "https://routing.internal.test/osrm/route/v1/driving/106.7,10.7;106.8,10.8"
    )
