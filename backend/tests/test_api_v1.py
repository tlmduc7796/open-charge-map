from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.api_v1 import (
    _limit_search,
    _require_internal_key,
    availability,
    config,
    list_stations,
    search_route,
    search_stations,
    station_detail,
    station_ports,
)
from backend.app.api_v1_models import (
    ApiPoint,
    SearchRouteRequest,
    SearchStationsRequest,
)
from backend.app.main import app
from backend.app.search_store import SearchRateLimiter


@pytest.fixture
def fake_request():
    return SimpleNamespace(app=app, client=SimpleNamespace(host="test-client"))


def test_config_and_station_contract_use_boundary_fields(fake_request) -> None:
    config_result = config(fake_request)
    stations = list_stations(fake_request, "106.60,10.60,106.80,10.90")
    availability_result = availability(fake_request, None, 0)
    ports = station_ports("ST_EVO_LAVIDA_Q7", fake_request)
    detail = station_detail("ST_EVO_LAVIDA_Q7", fake_request)

    assert config_result.station_status_stale_after_sec == 120
    assert stations[0].location.model_dump(by_alias=True).keys() == {"lat", "lng"}
    assert stations[0].model_dump(by_alias=True)["availablePorts"] >= 0
    assert availability_result.is_prediction is False
    assert ports
    assert detail.by_connector
    assert sum(group.now.total for group in detail.by_connector) == detail.total_ports


def test_station_bbox_and_future_offset_validation(fake_request) -> None:
    with pytest.raises(HTTPException) as invalid_bbox:
        list_stations(fake_request, "bad")
    future = availability(fake_request, None, 20)
    with pytest.raises(HTTPException) as invalid_offset:
        availability(fake_request, None, 7)

    assert invalid_bbox.value.status_code == 400
    assert invalid_bbox.value.detail["code"] == "VALIDATION_ERROR"
    assert future.is_prediction is True
    assert all(item.prediction_source == "persistence" for item in future.items)
    assert invalid_offset.value.status_code == 400


def test_internal_port_status_requires_configuration_and_key(fake_request) -> None:
    original = app.state.settings
    try:
        with pytest.raises(HTTPException) as unconfigured:
            _require_internal_key(fake_request, None)
        app.state.settings = replace(original, internal_api_key="test-secret")
        with pytest.raises(HTTPException) as unauthorized:
            _require_internal_key(fake_request, None)
        _require_internal_key(fake_request, "test-secret")
    finally:
        app.state.settings = original

    assert unconfigured.value.status_code == 503
    assert unauthorized.value.status_code == 401


def test_openapi_exposes_versioned_contracts() -> None:
    schema = app.openapi()

    assert "/api/v1/config" in schema["paths"]
    assert "/api/v1/internal/port-status" in schema["paths"]
    assert "/api/v1/search/stations" in schema["paths"]
    assert "/api/v1/search/route" in schema["paths"]


def test_search_route_reports_no_route(fake_request, monkeypatch) -> None:
    class UnavailableRouting:
        def search_route(self, payload):
            raise RuntimeError("routing unavailable")

    monkeypatch.setattr(app.state, "search_service", UnavailableRouting())
    payload = SearchRouteRequest(
        origin=ApiPoint(lat=10.7075, lng=106.705),
        destination=ApiPoint(lat=10.806, lng=106.687),
        vehicle_id="EV_VF5_PLUS",
        battery_pct=14,
    )

    with pytest.raises(HTTPException) as error:
        search_route(payload, fake_request)

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "NO_ROUTE"


def test_out_of_range_includes_nearest_station(fake_request) -> None:
    payload = SearchStationsRequest(
        origin=ApiPoint(lat=10.7075, lng=106.705),
        vehicle_id="EV_VF5_PLUS",
        battery_pct=1,
    )

    with pytest.raises(HTTPException) as error:
        search_stations(payload, fake_request)

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "OUT_OF_RANGE"
    assert error.value.detail["nearestStation"] is not None


def test_search_endpoint_rejects_excess_requests(fake_request, monkeypatch) -> None:
    monkeypatch.setattr(app.state, "search_rate_limiter", SearchRateLimiter(1))

    _limit_search(fake_request)
    with pytest.raises(HTTPException) as error:
        _limit_search(fake_request)

    assert error.value.status_code == 429
    assert error.value.detail["code"] == "RATE_LIMITED"
