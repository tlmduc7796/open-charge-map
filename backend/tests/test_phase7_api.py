import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from backend.app.api import (
    _current_station_status,
    _release_safe_status,
    _validate_arrival_references,
    get_journey,
    station_telemetry,
    upsert_station_telemetry,
)
from backend.app.domain.models import StationStatus
from backend.app.domain.realtime import (
    DESWaitRequest,
    RealtimeTelemetryStore,
    StationTelemetrySnapshot,
)
from backend.app.main import app


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_geocoding_details_rejects_oversized_provider_place_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app.state,
        "settings",
        replace(app.state.settings, demo_mode=True),
    )

    response = asyncio.run(_request("GET", f"/geocoding/details/{'x' * 257}"))

    assert response.status_code == 422


def test_release_status_detail_uses_targeted_repository_read() -> None:
    expected = StationStatus(
        station_id="ST_RELEASE",
        timestamp="2026-10-09T00:00:00Z",
        total_ports=1,
        operational_ports=1,
        occupied_ports=0,
        available_ports=1,
        offline_ports=0,
        occupancy_ratio=0,
        queue_length=None,
        data_source="station_api",
    )

    class TargetedRuntime:
        def get_many(self, station_ids: tuple[str, ...]) -> tuple[StationStatus, ...]:
            assert station_ids == ("ST_RELEASE",)
            return (expected,)

        def refresh(self) -> None:
            raise AssertionError("release detail must not refresh the full catalog")

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(demo_mode=False),
                runtime_state=TargetedRuntime(),
            )
        )
    )

    assert _current_station_status(request, "ST_RELEASE") == expected


@pytest.mark.parametrize("invalid_reference", ["station", "vehicle"])
def test_release_arrival_validation_rejects_synthetic_references(
    invalid_reference: str,
) -> None:
    station = SimpleNamespace(
        properties=SimpleNamespace(
            source_provider=(
                "Synthetic station feed"
                if invalid_reference == "station"
                else "operator_feed"
            ),
            synthetic_fields=(),
            connectors=(SimpleNamespace(source="operator_verified"),),
        )
    )
    vehicle = SimpleNamespace(is_release_eligible=invalid_reference != "vehicle")
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(demo_mode=False),
                station_repository=SimpleNamespace(get=lambda _station_id: station),
                vehicle_repository=SimpleNamespace(get=lambda _vehicle_id: vehicle),
            )
        )
    )

    with pytest.raises(KeyError):
        _validate_arrival_references(request, "ST_TEST", "EV_TEST")


def test_release_rejects_discrete_event_wait_simulation() -> None:
    from backend.app.api import simulate_realtime_wait

    api_key = "t" * 32
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    demo_mode=False,
                    telemetry_ingest_api_key=api_key,
                )
            )
        )
    )
    payload = DESWaitRequest(
        evaluation_at="2026-10-09T08:30:00Z",
        compatible_connector_types=("CCS2",),
    )

    with pytest.raises(HTTPException) as error:
        simulate_realtime_wait("ST_RELEASE", payload, request, api_key)

    assert error.value.status_code == 403


def test_station_vehicle_route_and_model_endpoints() -> None:
    async def run_requests():
        await _request("POST", "/demo/reset")
        return await asyncio.gather(
            _request("GET", "/stations"),
            _request("GET", "/stations/ST_EVO_LAVIDA_Q7"),
            _request("GET", "/stations/ST_EVO_LAVIDA_Q7/status"),
            _request("GET", "/vehicles"),
            _request("GET", "/demo/scenarios"),
            _request(
                "POST",
                "/route",
                json={
                    "origin": {"lat": 10.7075, "lon": 106.705},
                    "destination": {"lat": 10.806, "lon": 106.687},
                    "preferred_route_id": "ROUTE_BASE_DIRECT",
                },
            ),
            _request("GET", "/model/status"),
        )

    responses = asyncio.run(run_requests())
    assert all(response.status_code == 200 for response in responses)
    assert len(responses[0].json()) == len(app.state.station_repository.all())
    assert len(responses[3].json()) == len(app.state.vehicle_repository.all())
    assert len(responses[4].json()) == len(app.state.domain_data.demo_scenarios.all())
    assert responses[5].json()["resolution_source"] == "cache"
    assert responses[6].json()["prediction_source"] == "persistence"


def test_openapi_documents_stable_error_envelope() -> None:
    response = asyncio.run(_request("GET", "/openapi.json"))

    assert response.status_code == 200
    forecast_operation = response.json()["paths"][
        "/stations/{station_id}/forecast"
    ]["get"]
    for status in ("422", "default"):
        error_schema = forecast_operation["responses"][status]["content"][
            "application/json"
        ]["schema"]
        assert error_schema["required"] == ["detail", "error_code"]
        assert error_schema["properties"]["error_code"]["type"] == "string"


def test_model_status_reports_model_release_version(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state,
        "model_metadata",
        {"model_version": "occupancy-xgb-2026-10-09.1", "profile": "baseline"},
    )

    response = asyncio.run(_request("GET", "/model/status"))

    assert response.status_code == 200
    assert response.json()["model_version"] == "occupancy-xgb-2026-10-09.1"


def test_station_forecast_endpoint_returns_target_provenance(monkeypatch) -> None:
    persisted_forecasts = []
    monkeypatch.setattr(
        app.state,
        "model_metadata",
        {"model_version": "configured-model-not-used"},
    )
    monkeypatch.setattr(
        app.state, "persist_occupancy_forecasts", persisted_forecasts.append
    )
    async def run_requests():
        await _request("POST", "/demo/reset")
        return await _request(
            "GET", "/stations/ST_EVO_LAVIDA_Q7/forecast?horizon_min=15"
        )

    response = asyncio.run(run_requests())

    assert response.status_code == 200
    payload = response.json()
    assert payload["station_id"] == "ST_EVO_LAVIDA_Q7"
    assert payload["requested_horizon_min"] == 15
    assert payload["generated_at"].endswith("Z")
    assert payload["target_at"] > payload["generated_at"]
    assert payload["prediction_source"] == "persistence"
    assert payload["model_version"] is None
    assert len(persisted_forecasts) == 1
    assert persisted_forecasts[0][0].station_id == "ST_EVO_LAVIDA_Q7"
    assert payload["confidence"] is None
    assert "PERSISTENCE_FALLBACK" in payload["flags"]
    assert "SYNTHETIC_HISTORY" in payload["flags"]


def test_station_forecast_endpoint_survives_history_persistence_failure(monkeypatch) -> None:
    class FailingPredictionRepository:
        def save_occupancy_forecasts(self, _forecasts) -> int:
            raise RuntimeError("private database connection details")

    monkeypatch.setattr(app.state, "prediction_repository", FailingPredictionRepository())

    async def run_request():
        await _request("POST", "/demo/reset")
        return await _request(
            "GET", "/stations/ST_EVO_LAVIDA_Q7/forecast?horizon_min=15"
        )

    response = asyncio.run(run_request())

    assert response.status_code == 200
    assert response.json()["station_id"] == "ST_EVO_LAVIDA_Q7"


def test_station_forecast_endpoint_rejects_unsupported_horizon() -> None:
    response = asyncio.run(
        _request("GET", "/stations/ST_EVO_LAVIDA_Q7/forecast?horizon_min=7")
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_FAILED"
    assert "horizon_min" in response.json()["detail"]


def test_station_history_endpoint_returns_empty_without_demo_history() -> None:
    async def run_requests():
        await _request("POST", "/demo/reset")
        return await _request("GET", "/stations/ST_EVO_LAVIDA_Q7/history")

    response = asyncio.run(run_requests())
    assert response.status_code == 200
    assert response.json() == []


def test_station_history_endpoint_serializes_observed_ratios(monkeypatch) -> None:
    class HistoryRepository:
        def get_observations(self, station_id, *, start_at, end_at, limit):
            assert station_id == "ST_EVO_LAVIDA_Q7"
            assert limit == 288
            return ({
                "bucket_at": datetime(2026, 10, 9, 10, 0, tzinfo=UTC),
                "total_ports": 4,
                "operational_ports": 4,
                "occupied_ports": 2,
                "queue_length": None,
                "data_origin": "observed",
            },)

    monkeypatch.setattr(app.state, "occupancy_history_repository", HistoryRepository())
    response = asyncio.run(
        _request("GET", "/stations/ST_EVO_LAVIDA_Q7/history")
    )
    assert response.status_code == 200
    assert response.json() == [{
        "station_id": "ST_EVO_LAVIDA_Q7",
        "bucket_at": "2026-10-09T10:00:00Z",
        "total_ports": 4,
        "operational_ports": 4,
        "occupied_ports": 2,
        "occupancy_ratio": 0.5,
        "queue_length": None,
        "data_source": "observed",
    }]


def test_station_history_endpoint_rejects_unbounded_or_naive_ranges() -> None:
    too_wide = asyncio.run(_request(
        "GET", "/stations/ST_EVO_LAVIDA_Q7/history",
        params={"start_at": "2026-01-01T00:00:00Z", "end_at": "2026-02-02T00:00:00Z"},
    ))
    naive = asyncio.run(_request(
        "GET", "/stations/ST_EVO_LAVIDA_Q7/history",
        params={"start_at": "2026-01-01T00:00:00", "end_at": "2026-01-02T00:00:00Z"},
    ))
    assert too_wide.status_code == 422
    assert naive.status_code == 422


def test_station_status_batch_is_bounded_and_returns_requested_ids() -> None:
    async def run_requests():
        await _request("POST", "/demo/reset")
        station_id = "ST_EVO_LAVIDA_Q7"
        return await _request(
            "GET", "/stations/statuses", params={"station_ids": [station_id]}
        )

    response = asyncio.run(run_requests())
    assert response.status_code == 200
    assert [item["station_id"] for item in response.json()] == ["ST_EVO_LAVIDA_Q7"]


def test_station_status_batch_rejects_duplicate_and_oversized_id_lists() -> None:
    duplicate = asyncio.run(_request(
        "GET", "/stations/statuses",
        params=[("station_ids", "ST_EVO_LAVIDA_Q7"),
                ("station_ids", "ST_EVO_LAVIDA_Q7")],
    ))
    oversized = asyncio.run(_request(
        "GET", "/stations/statuses",
        params=[("station_ids", f"ST_{index}") for index in range(201)],
    ))
    assert duplicate.status_code == 422
    assert oversized.status_code == 422


def test_station_status_sse_rejects_oversized_station_id_lists() -> None:
    oversized = asyncio.run(_request(
        "GET",
        "/realtime/stations/status/events",
        params=[("station_ids", f"ST_{index}") for index in range(201)],
    ))

    assert oversized.status_code == 422


def test_station_catalog_uses_bounded_keyset_pages() -> None:
    first = asyncio.run(_request("GET", "/stations?limit=1"))
    assert first.status_code == 200
    first_station = first.json()[0]["properties"]["station_id"]
    second = asyncio.run(
        _request("GET", "/stations", params={"limit": 1, "after_station_id": first_station})
    )
    too_many = asyncio.run(_request("GET", "/stations?limit=201"))

    assert second.status_code == 200
    assert second.json()[0]["properties"]["station_id"] > first_station
    assert too_many.status_code == 422


def test_station_search_supports_radius_and_bbox_queries() -> None:
    station = app.state.station_repository.get("ST_EVO_LAVIDA_Q7")
    longitude, latitude = station.geometry.coordinates

    async def run_queries():
        await _request("POST", "/demo/reset")
        radius = await _request(
            "GET",
            "/stations/search",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "radius_m": 1000,
                "limit": 10,
            },
        )
        bbox = await _request(
            "GET",
            "/stations/search",
            params={
                "west": longitude - 0.01,
                "south": latitude - 0.01,
                "east": longitude + 0.01,
                "north": latitude + 0.01,
                "limit": 10,
            },
        )
        invalid = await _request(
            "GET",
            "/stations/search",
            params={"latitude": latitude, "longitude": longitude, "radius_m": 1000,
                    "west": longitude - 0.01, "south": latitude - 0.01,
                    "east": longitude + 0.01, "north": latitude + 0.01},
        )
        return radius, bbox, invalid

    radius, bbox, invalid = asyncio.run(run_queries())
    assert radius.status_code == bbox.status_code == 200
    assert station.station_id in {item["properties"]["station_id"] for item in radius.json()}
    assert station.station_id in {item["properties"]["station_id"] for item in bbox.json()}
    assert len(radius.json()) <= 10
    assert len(bbox.json()) <= 10
    assert invalid.status_code == 422


def test_release_station_status_marks_synthetic_snapshot_stale() -> None:
    settings = replace(app.state.settings, demo_mode=False)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings))
    )
    snapshot = app.state.runtime_state.get("ST_VF_LANDMARK_81")
    response = _release_safe_status(request, snapshot)

    assert response.data_source == "synthetic"
    assert response.is_stale is True
    simulated = snapshot.model_copy(update={"data_source": "simulated", "is_stale": False})
    assert _release_safe_status(request, simulated).is_stale is True


def test_release_telemetry_ingest_rejects_future_snapshot_before_storage() -> None:
    settings = replace(
        app.state.settings,
        demo_mode=False,
        telemetry_ingest_api_key="test-telemetry-api-key",
        realtime_telemetry_max_future_skew_s=60,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=settings,
                station_repository=SimpleNamespace(
                    get=lambda _station_id: SimpleNamespace(
                        properties=SimpleNamespace(
                            synthetic_fields=(),
                            total_ports=1,
                            connectors=(SimpleNamespace(type="CCS2", source="operator"),),
                        )
                    )
                ),
            )
        )
    )
    payload = StationTelemetrySnapshot(
        station_id="ST_EVO_AUDI_HCM",
        observed_at=datetime.now(UTC) + timedelta(days=1),
        data_source="station_api",
        ports=(
            {
                "port_id": "PORT_1",
                "connector_types": ["CCS2"],
                "state": "available",
            },
        ),
    )

    with pytest.raises(HTTPException) as error:
        upsert_station_telemetry(
            payload.station_id,
            payload,
            request,
            api_key="test-telemetry-api-key",
        )

    assert error.value.status_code == 422


def test_telemetry_ingest_rejects_connector_counts_that_differ_from_catalog() -> None:
    station_id = "ST_CONNECTOR_COUNTS"

    class TelemetryStore:
        def upsert(self, _snapshot):
            raise AssertionError("mismatched connector counts must not be stored")

    station = SimpleNamespace(
        properties=SimpleNamespace(
            synthetic_fields=(),
            total_ports=2,
            connectors=(
                SimpleNamespace(type="CCS2", count=1, source="operator"),
                SimpleNamespace(type="Type2", count=1, source="operator"),
            ),
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=replace(
                    app.state.settings,
                    demo_mode=False,
                    telemetry_ingest_api_key="test-telemetry-api-key",
                ),
                station_repository=SimpleNamespace(get=lambda _station_id: station),
                realtime_telemetry_store=TelemetryStore(),
            )
        )
    )
    payload = StationTelemetrySnapshot(
        station_id=station_id,
        observed_at=datetime.now(UTC),
        data_source="station_api",
        ports=(
            {
                "port_id": "CCS2-1",
                "connector_types": ["CCS2"],
                "state": "available",
            },
            {
                "port_id": "CCS2-2",
                "connector_types": ["CCS2"],
                "state": "available",
            },
        ),
    )

    with pytest.raises(HTTPException) as error:
        upsert_station_telemetry(
            station_id,
            payload,
            request,
            api_key="test-telemetry-api-key",
        )

    assert error.value.status_code == 409
    assert error.value.detail == "telemetry connector counts do not match station catalog"


def test_release_telemetry_rejects_connectors_assigned_to_wrong_catalog_ports() -> None:
    station_id = "ST_PORT_CONNECTOR_MAPPING"

    class TelemetryStore:
        def upsert(self, _snapshot):
            raise AssertionError("port connector mismatch must not be stored")

    station = SimpleNamespace(
        properties=SimpleNamespace(
            synthetic_fields=(),
            total_ports=2,
            connectors=(
                SimpleNamespace(type="CCS2", count=1, source="operator"),
                SimpleNamespace(type="Type2", count=1, source="operator"),
            ),
        )
    )
    repository = SimpleNamespace(
        get=lambda _station_id: station,
        telemetry_port_inventory=lambda _station_id: (
            ("PORT_CCS2", "CCS2"),
            ("PORT_TYPE2", "Type2"),
        ),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=replace(
                    app.state.settings,
                    demo_mode=False,
                    telemetry_ingest_api_key="test-telemetry-api-key",
                ),
                station_repository=repository,
                realtime_telemetry_store=TelemetryStore(),
            )
        )
    )
    payload = StationTelemetrySnapshot(
        station_id=station_id,
        observed_at=datetime.now(UTC),
        data_source="station_api",
        ports=(
            {
                "port_id": "PORT_CCS2",
                "connector_types": ["Type2"],
                "state": "available",
            },
            {
                "port_id": "PORT_TYPE2",
                "connector_types": ["CCS2"],
                "state": "available",
            },
        ),
    )

    with pytest.raises(HTTPException) as error:
        upsert_station_telemetry(
            station_id,
            payload,
            request,
            api_key="test-telemetry-api-key",
        )

    assert error.value.status_code == 409
    assert error.value.detail == (
        "telemetry port connector types do not match station catalog"
    )


def test_telemetry_replay_does_not_publish_duplicate_realtime_event() -> None:
    station_id = "ST_NOTIFICATION_REPLAY"

    class Publisher:
        def __init__(self) -> None:
            self.published: list[tuple[str, str]] = []

        def publish(self, channel: str, value: str) -> None:
            self.published.append((channel, value))

    publisher = Publisher()
    station = SimpleNamespace(
        properties=SimpleNamespace(
            synthetic_fields=(),
            total_ports=1,
            connectors=(SimpleNamespace(type="CCS2", count=1, source="operator"),),
        )
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=replace(
                    app.state.settings,
                    demo_mode=True,
                    telemetry_ingest_api_key=None,
                ),
                station_repository=SimpleNamespace(get=lambda _station_id: station),
                realtime_telemetry_store=RealtimeTelemetryStore(),
                redis_sync_client=publisher,
            )
        )
    )
    payload = StationTelemetrySnapshot(
        station_id=station_id,
        observed_at=datetime.now(UTC),
        data_source="station_api",
        ports=(
            {
                "port_id": "CCS2-1",
                "connector_types": ["CCS2"],
                "state": "available",
            },
        ),
    )

    first = upsert_station_telemetry(station_id, payload, request)
    replay = upsert_station_telemetry(station_id, payload, request)

    assert first == replay == payload
    assert publisher.published == [("smart-ev:station-status-updated", station_id)]


def test_release_telemetry_rejects_synthetic_station_before_storage() -> None:
    station_id = "ST_SYNTHETIC_RELEASE"
    synthetic_station = SimpleNamespace(
        properties=SimpleNamespace(
            synthetic_fields=(),
            source_provider="Synthetic Import Feed",
            connectors=(SimpleNamespace(type="CCS2", source="operator"),),
        )
    )

    class TelemetryStore:
        def upsert(self, _snapshot):
            raise AssertionError("synthetic station telemetry must not be stored")

        def get(self, _station_id):
            raise AssertionError("synthetic station telemetry must not be exposed")

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=replace(
                    app.state.settings,
                    demo_mode=False,
                    telemetry_ingest_api_key="test-telemetry-api-key",
                ),
                station_repository=SimpleNamespace(
                    get=lambda _station_id: synthetic_station,
                ),
                realtime_telemetry_store=TelemetryStore(),
            )
        )
    )
    payload = StationTelemetrySnapshot(
        station_id=station_id,
        observed_at=datetime.now(UTC),
        data_source="station_api",
        ports=(
            {
                "port_id": "PORT_1",
                "connector_types": ["CCS2"],
                "state": "available",
            },
        ),
    )

    with pytest.raises(HTTPException) as ingest_error:
        upsert_station_telemetry(
            station_id,
            payload,
            request,
            api_key="test-telemetry-api-key",
        )
    with pytest.raises(HTTPException) as read_error:
        station_telemetry(
            station_id,
            request,
            api_key="test-telemetry-api-key",
        )

    assert ingest_error.value.status_code == 404
    assert read_error.value.status_code == 404


def test_release_raw_telemetry_does_not_expose_persisted_simulation() -> None:
    station = SimpleNamespace(
        properties=SimpleNamespace(
            synthetic_fields=(),
            connectors=(SimpleNamespace(type="CCS2", source="operator"),),
        )
    )
    snapshot = StationTelemetrySnapshot(
        station_id="ST_OPERATIONAL",
        observed_at=datetime.now(UTC),
        data_source="simulated",
        ports=(
            {
                "port_id": "PORT_1",
                "connector_types": ["CCS2"],
                "state": "available",
            },
        ),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=replace(
                    app.state.settings,
                    demo_mode=False,
                    telemetry_ingest_api_key="test-telemetry-api-key",
                ),
                station_repository=SimpleNamespace(get=lambda _station_id: station),
                realtime_telemetry_store=SimpleNamespace(
                    get=lambda _station_id: snapshot,
                ),
            )
        )
    )

    with pytest.raises(HTTPException) as error:
        station_telemetry(
            snapshot.station_id,
            request,
            api_key="test-telemetry-api-key",
        )

    assert error.value.status_code == 404


def test_get_journey_includes_only_its_active_planned_arrival() -> None:
    journey_id = UUID("a9d75b53-e852-4dda-aabe-0bf7b1b15008")
    arrival = SimpleNamespace(arrival_id="ARR_ACTIVE")

    class JourneyRepository:
        def get(self, requested_id, *, access_token):
            assert requested_id == journey_id
            assert access_token == "journey-capability"
            return {"journey_id": str(journey_id), "recommendation": {}}

    class PlannedArrivalReader:
        def active_for_journey(self, requested_id):
            assert requested_id == str(journey_id)
            return arrival

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                journey_repository=JourneyRepository(),
                planned_arrival_store=PlannedArrivalReader(),
            )
        )
    )

    result = get_journey(
        journey_id,
        request,
        authorization="Bearer journey-capability",
    )

    assert result["active_planned_arrival"] is arrival


def test_two_end_to_end_recommendation_scenarios() -> None:
    async def run_scenarios():
        await _request("POST", "/demo/reset")
        normal = await _request(
            "POST",
            "/journey/recommend",
            json={
                "scenario_id": "SCN_LOW_SOC",
                "origin": {"lat": 10.7075, "lon": 106.705},
                "destination": {"lat": 10.806, "lon": 106.687},
                "departure_at": "2026-09-26T18:00:00+07:00",
            },
        )
        await _request("POST", "/demo/reset")
        outage_before = await _request(
            "POST",
            "/journey/recommend",
            json={"scenario_id": "SCN_PORT_OUTAGE_REROUTE", "initial_soc": 0.14},
        )
        outage_after = await _request(
            "POST",
            "/journey/recommend",
            json={
                "scenario_id": "SCN_PORT_OUTAGE_REROUTE",
                "initial_soc": 0.14,
                "apply_scenario_events": True,
            },
        )
        await _request("POST", "/demo/reset")
        unreachable = await _request(
            "POST",
            "/journey/recommend",
            json={"scenario_id": "SCN_NORMAL", "initial_soc": 0.10},
        )
        return normal, outage_before, outage_after, unreachable

    normal, before, after, unreachable = asyncio.run(run_scenarios())
    assert (
        normal.status_code
        == before.status_code
        == after.status_code
        == unreachable.status_code
        == 200
    )
    assert normal.json()["recommendations"][0]["route"]["geometry"]["type"] == (
        "LineString"
    )
    assert normal.json()["recommendations"][0]["energy_to_add_kwh"] > 0
    assert normal.json()["recommendations"][0]["wait_p90_min"] is not None
    assert normal.json()["recommendations"][0]["wait_method"] == "erlang_c"
    assert normal.json()["recommendations"][0]["wait_data_source"] == "derived"
    assert normal.json()["recommendations"][0]["wait_expected_min"] == normal.json()[
        "recommendations"
    ][0]["estimated_wait_min"]
    assert normal.json()["recommendations"][0]["charge_min"] == normal.json()[
        "recommendations"
    ][0]["estimated_charge_min"]
    assert normal.json()["recommendations"][0]["soc_after_charge"] is not None
    assert normal.json()["recommendations"][0]["predicted_free_ports"] is not None
    assert normal.json()["recommendations"][0]["station_id"] == "ST_VF_LA_VELA"
    assert before.json()["recommendations"][0]["station_id"] == "ST_VF_LA_VELA"
    assert after.json()["recommendations"][0]["station_id"] != "ST_VF_LA_VELA"
    assert unreachable.json()["outcome"] == "no_reachable_station"
    fallback = unreachable.json()["fallback_candidate"]
    assert fallback["is_reachable"] is False
    assert fallback["straight_line_distance_m"] > 0
    assert fallback["reason_codes"]


def test_planned_arrival_api_lifecycle() -> None:
    payload = {
        "arrival_id": "ARR_API_TEST",
        "station_id": "ST_EVO_LAVIDA_Q7",
        "vehicle_id": "EV_VF5_PLUS",
        "eta_at": "2099-01-01T10:10:00+07:00",
        "eta_window_start": "2099-01-01T10:05:00+07:00",
        "eta_window_end": "2099-01-01T10:15:00+07:00",
        "expected_energy_kwh": 12,
        "expected_charge_duration_min": 20,
        "arrival_probability": 0.8,
        "expires_at": "2099-01-01T10:20:00+07:00",
        "route_id": "ROUTE_VIA_LAVIDA",
    }

    async def lifecycle():
        await _request("POST", "/demo/reset")
        invalid_timestamp = await _request(
            "POST",
            "/planned-arrivals",
            json={**payload, "arrival_id": "ARR_API_NAIVE", "eta_at": "2099-01-01T10:10:00"},
        )
        invalid_window = await _request(
            "POST",
            "/planned-arrivals",
            json={
                **payload,
                "arrival_id": "ARR_API_WINDOW",
                "eta_at": "2099-01-01T10:20:00+07:00",
            },
        )
        invalid_expiry = await _request(
            "POST",
            "/planned-arrivals",
            json={
                **payload,
                "arrival_id": "ARR_API_EXPIRY",
                "expires_at": "2099-01-01T10:15:00+07:00",
            },
        )
        missing_arrival_id = await _request(
            "POST",
            "/planned-arrivals",
            json={key: value for key, value in payload.items() if key != "arrival_id"},
        )
        created = await _request("POST", "/planned-arrivals", json=payload)
        cancelled = await _request(
            "POST", "/planned-arrivals/ARR_API_TEST/cancel"
        )
        cancelled_retry = await _request(
            "POST", "/planned-arrivals/ARR_API_TEST/cancel"
        )
        return (
            invalid_timestamp,
            invalid_window,
            invalid_expiry,
            missing_arrival_id,
            created,
            cancelled,
            cancelled_retry,
        )

    (
        invalid_timestamp,
        invalid_window,
        invalid_expiry,
        missing_arrival_id,
        created,
        cancelled,
        cancelled_retry,
    ) = asyncio.run(lifecycle())
    assert invalid_timestamp.status_code == 422
    assert invalid_window.status_code == 422
    assert invalid_expiry.status_code == 422
    assert missing_arrival_id.status_code == 422
    assert created.status_code == 200
    assert created.json()["status"] == "planned"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled_retry.status_code == 200
    assert cancelled_retry.json()["status"] == "cancelled"


def test_commit_arrival_and_timezone_validation() -> None:
    async def lifecycle():
        await _request("POST", "/demo/reset")
        invalid = await _request(
            "POST",
            "/journey/recommend",
            json={
                "scenario_id": "SCN_NORMAL",
                "departure_at": "2026-09-26T18:00:00",
            },
        )
        missing_arrival_id = await _request(
            "POST",
            "/planned-arrivals/commit",
            json={
                "station_id": "ST_EVO_LAVIDA_Q7",
                "vehicle_id": "EV_VF5_PLUS",
                "departure_at": "2099-01-01T10:00:00+07:00",
                "route_id": "LIVE_GOONG_DEMO",
                "route_duration_to_station_s": 600,
                "expected_energy_kwh": 12,
                "expected_charge_duration_min": 20,
            },
        )
        commit_payload = {
            "arrival_id": "ARR_COMMIT_TEST",
            "station_id": "ST_EVO_LAVIDA_Q7",
            "vehicle_id": "EV_VF5_PLUS",
            "departure_at": "2099-01-01T10:00:00+07:00",
            "route_id": "LIVE_GOONG_DEMO",
            "route_duration_to_station_s": 600,
            "expected_energy_kwh": 12,
            "expected_charge_duration_min": 20,
        }
        committed = await _request(
            "POST",
            "/planned-arrivals/commit",
            json=commit_payload,
        )
        committed_retry = await _request(
            "POST", "/planned-arrivals/commit", json=commit_payload
        )
        conflicting_retry = await _request(
            "POST",
            "/planned-arrivals/commit",
            json={
                **commit_payload,
                "departure_at": "2099-01-01T10:01:00+07:00",
            },
        )
        cancelled = await _request(
            "POST", f"/planned-arrivals/{committed.json()['arrival_id']}/cancel"
        )
        return (
            invalid,
            missing_arrival_id,
            committed,
            committed_retry,
            conflicting_retry,
            cancelled,
        )

    (
        invalid,
        missing_arrival_id,
        committed,
        committed_retry,
        conflicting_retry,
        cancelled,
    ) = asyncio.run(lifecycle())
    assert invalid.status_code == 422
    assert missing_arrival_id.status_code == 422
    assert committed.status_code == 200
    assert committed_retry.status_code == 200
    assert committed_retry.json() == committed.json()
    assert conflicting_retry.status_code == 409
    assert committed.json()["eta_at"] == "2099-01-01T10:10:00+07:00"
    assert committed.json()["route_id"] == "LIVE_GOONG_DEMO"
    assert cancelled.json()["status"] == "cancelled"


def test_simulated_realtime_telemetry_can_drive_des_wait_endpoint() -> None:
    snapshot = {
        "station_id": "ST_EVO_AUDI_HCM",
        "observed_at": "2026-09-26T10:00:00+07:00",
        "data_source": "simulated",
        "ports": [
            {
                "port_id": "A",
                "connector_types": ["CCS2"],
                "state": "charging",
                "session_id": "SESSION_A",
                "reported_remaining_port_release_min": 8,
            },
            {
                "port_id": "B",
                "connector_types": ["CCS2"],
                "state": "charging",
                "session_id": "SESSION_B",
                "reported_remaining_port_release_min": 8,
            },
            {
                "port_id": "C",
                "connector_types": ["Type2"],
                "state": "charging",
                "session_id": "SESSION_C",
                "reported_remaining_port_release_min": 15,
            },
            {
                "port_id": "D",
                "connector_types": ["Type2"],
                "state": "charging",
                "session_id": "SESSION_D",
                "reported_remaining_port_release_min": 15,
            },
        ],
        "queue": [
            {
                "queue_id": "Q1",
                "queue_position": 1,
                "entered_queue_at": "2026-09-26T09:55:00+07:00",
                "compatible_connector_types": ["CCS2"],
                "expected_charge_duration_min": 20,
            }
        ],
        "avg_session_duration_min": 20,
    }

    async def run():
        await _request("POST", "/demo/reset")
        saved = await _request(
            "PUT", "/realtime/stations/ST_EVO_AUDI_HCM/telemetry", json=snapshot
        )
        result = await _request(
            "POST", "/realtime/stations/ST_EVO_AUDI_HCM/simulate-wait",
            json={
                "evaluation_at": "2026-09-26T10:00:00+07:00",
                "compatible_connector_types": ["CCS2"],
            },
        )
        return saved, result

    saved, result = asyncio.run(run())
    assert saved.status_code == result.status_code == 200
    assert result.json()["method"] == "discrete_event_simulation"
    assert result.json()["estimated_wait_min"] == 8
