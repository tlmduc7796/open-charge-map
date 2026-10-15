from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.api_v1_models import (
    ApiPoint,
    SearchRouteRequest,
    SearchStationsRequest,
)
from backend.app.domain.routing import RoutingService
from backend.app.main import app
from backend.app.search_store import SearchResultStore

ORIGIN = ApiPoint(lat=10.7075, lng=106.705)
DESTINATION = ApiPoint(lat=10.806, lng=106.687)
NOW = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)


def test_route_search_returns_enough_without_station_when_battery_is_sufficient() -> None:
    result = app.state.search_service.search_route(
        SearchRouteRequest(
            origin=ORIGIN,
            destination=DESTINATION,
            vehicle_id="EV_VF7_ECO",
            battery_pct=55,
        ),
        now=NOW,
    )

    assert result.case == "enough"
    assert result.stations == ()
    assert result.search_id.startswith("SRCH_")
    assert result.direct_route.route_id
    assert (
        app.state.search_result_store.get(
            result.search_id, now=NOW + timedelta(seconds=1)
        ).response.search_id
        == result.search_id
    )


def test_enough_with_optional_stops_ranks_voluntary_charging_stops() -> None:
    request = dict(
        origin=ORIGIN,
        destination=DESTINATION,
        vehicle_id="EV_VF7_ECO",
        battery_pct=55,
    )
    plain = app.state.search_service.search_route(SearchRouteRequest(**request), now=NOW)
    with_stops = app.state.search_service.search_route(
        SearchRouteRequest(**request, include_optional_stops=True), now=NOW
    )

    # Still "enough": the stops are optional, and the default response is unchanged.
    assert plain.stations == ()
    assert with_stops.case == "enough"
    assert with_stops.stations
    assert [item.rank for item in with_stops.stations] == list(
        range(1, len(with_stops.stations) + 1)
    )
    assert [item.total_min for item in with_stops.stations] == sorted(
        item.total_min for item in with_stops.stations
    )
    assert all(item.to_dest_min is not None for item in with_stops.stations)
    assert with_stops.search_id != plain.search_id
    # The result is stored like any other, so a trip can pick one of the stops.
    stored = app.state.search_result_store.get(
        with_stops.search_id, now=NOW + timedelta(seconds=1)
    )
    assert stored.response.stations == with_stops.stations


def test_optional_stop_charges_to_the_vehicle_default_target() -> None:
    vehicle = app.state.vehicle_repository.get("EV_VF7_ECO")
    result = app.state.search_service.search_route(
        SearchRouteRequest(
            origin=ORIGIN,
            destination=DESTINATION,
            vehicle_id="EV_VF7_ECO",
            battery_pct=55,
            include_optional_stops=True,
        ),
        now=NOW,
    )

    for option in result.stations:
        arrival = option.arrive_battery_pct / 100
        to_add = max(0.0, vehicle.default_target_soc - arrival)
        # Voluntary stops charge to the default target, not just "enough to arrive".
        if to_add > 0:
            assert option.charge_min > 0
        else:
            assert option.charge_min == 0


def test_optional_stops_flag_does_not_change_the_need_charge_case() -> None:
    base = dict(
        origin=ORIGIN,
        destination=DESTINATION,
        vehicle_id="EV_VF5_PLUS",
        battery_pct=14,
    )
    off = app.state.search_service.search_route(SearchRouteRequest(**base), now=NOW)
    on = app.state.search_service.search_route(
        SearchRouteRequest(**base, include_optional_stops=True), now=NOW
    )

    assert off.case == on.case == "needCharge"
    assert [item.station.id for item in off.stations] == [
        item.station.id for item in on.stations
    ]
    assert [round(item.charge_min, 6) for item in off.stations] == [
        round(item.charge_min, 6) for item in on.stations
    ]


def test_station_search_ranks_by_total_minutes_and_exposes_source() -> None:
    result = app.state.search_service.search_stations(
        SearchStationsRequest(
            origin=ORIGIN,
            vehicle_id="EV_VF7_ECO",
            battery_pct=55,
            limit=5,
        ),
        now=NOW,
    )

    assert result.stations
    assert [item.rank for item in result.stations] == list(
        range(1, len(result.stations) + 1)
    )
    assert [item.total_min for item in result.stations] == sorted(
        item.total_min for item in result.stations
    )
    assert all(item.prediction_source == "default" for item in result.stations)


def test_route_search_with_low_battery_ranks_charge_stops_by_total_minutes() -> None:
    result = app.state.search_service.search_route(
        SearchRouteRequest(
            origin=ORIGIN,
            destination=DESTINATION,
            vehicle_id="EV_VF5_PLUS",
            battery_pct=14,
        ),
        now=NOW,
    )

    assert result.case == "needCharge"
    assert result.stations
    assert [item.total_min for item in result.stations] == sorted(
        item.total_min for item in result.stations
    )
    assert all(item.to_dest_min is not None for item in result.stations)


def test_route_search_fallback_includes_nearest_station_and_missing_range() -> None:
    result = app.state.search_service.search_route(
        SearchRouteRequest(
            origin=ORIGIN,
            destination=DESTINATION,
            vehicle_id="EV_VF5_PLUS",
            battery_pct=1,
        ),
        now=NOW,
    )

    assert result.case == "fallback"
    assert result.nearest_station is not None
    assert result.missing_km is not None
    assert result.stations == ()


def test_station_search_reports_exclusion_reasons() -> None:
    result = app.state.search_service.search_stations(
        SearchStationsRequest(
            origin=ORIGIN,
            vehicle_id="EV_VF7_ECO",
            battery_pct=55,
        ),
        now=NOW,
    )

    assert any(
        "OPENING_HOURS_UNVERIFIED" in item.reason_codes
        for item in result.excluded_candidates
    )
    assert any(
        "NON_PUBLIC_ACCESS" in item.reason_codes
        for item in result.excluded_candidates
    )


def test_search_reports_offline_station_when_ports_are_unavailable(monkeypatch) -> None:
    runtime = app.state.runtime_state
    status = runtime.get("ST_VF_LA_VELA")
    offline = status.model_copy(
        update={
            "operational_ports": 0,
            "occupied_ports": 0,
            "available_ports": 0,
            "offline_ports": status.total_ports,
            "occupancy_ratio": None,
        }
    )
    monkeypatch.setattr(runtime, "refresh", lambda: None)
    monkeypatch.setitem(runtime._statuses, "ST_VF_LA_VELA", offline)

    result = app.state.search_service.search_stations(
        SearchStationsRequest(
            origin=ORIGIN,
            vehicle_id="EV_VF7_ECO",
            battery_pct=55,
        ),
        now=NOW,
    )

    assert any(
        item.station_id == "ST_VF_LA_VELA" and "STATION_OFFLINE" in item.reason_codes
        for item in result.excluded_candidates
    )


def test_outside_demo_region_without_live_provider_has_no_route(monkeypatch) -> None:
    routing = RoutingService(goong=None, osrm=None)
    monkeypatch.setattr(app.state.search_service, "_routing", routing)

    with pytest.raises(RuntimeError, match="routing unavailable"):
        app.state.search_service.search_route(
            SearchRouteRequest(
                origin=ApiPoint(lat=16.0, lng=108.0),
                destination=ApiPoint(lat=16.1, lng=108.1),
                vehicle_id="EV_VF5_PLUS",
                battery_pct=55,
            ),
            now=NOW,
        )


def test_search_result_store_expires_results() -> None:
    store = SearchResultStore(ttl=timedelta(minutes=10))
    search_id = store.put({"value": 1}, created_at=NOW)

    assert store.get(search_id, now=NOW + timedelta(minutes=9)) == {"value": 1}
    with pytest.raises(KeyError):
        store.get(search_id, now=NOW + timedelta(minutes=10))
