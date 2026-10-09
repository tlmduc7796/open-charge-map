from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from sqlalchemy import create_engine, text

from backend.app.app_config_repository import AppConfigRepository
from backend.app.domain.trip_service import TripService
from backend.app.main import app
from backend.app.trip_repository import DatabaseTripRepository

TEST_DATABASE_URL = os.getenv("BACKEND_TEST_DATABASE_URL")


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_trip_search_gps_history_and_planned_arrival() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    repository = DatabaseTripRepository(engine)
    old_service = app.state.trip_service
    app.state.trip_service = TripService(
        repository, app.state.search_result_store,
        AppConfigRepository(app.state.settings, engine),
        app.state.search_service,
        app.state.station_repository,
        app.state.station_status_repository,
        app.state.vehicle_repository,
    )
    trip_id = None
    try:
        search = asyncio.run(
            _request(
                "POST", "/api/v1/search/stations",
                json={
                    "origin": {"lat": 10.7075, "lng": 106.705},
                    "vehicleId": "EV_VF7_ECO", "batteryPct": 80,
                },
            )
        )
        assert search.status_code == 200, search.text
        option = search.json()["stations"][0]
        created = asyncio.run(
            _request(
                "POST", "/api/v1/trips",
                json={"searchId": search.json()["searchId"],
                      "stationId": option["station"]["id"]},
            )
        )
        assert created.status_code == 201, created.text
        trip_id = created.json()["id"]
        assert created.json()["phase"] == "to_station"
        assert created.json()["stationId"] == option["station"]["id"]
        assert DatabaseTripRepository(engine).get(trip_id).id == trip_id

        recorded_at = datetime.now(UTC) + timedelta(seconds=1)
        ping = {
            "location": option["station"]["location"],
            "recordedAt": recorded_at.isoformat(),
            "batteryPct": 70,
        }
        arrived = asyncio.run(
            _request("POST", f"/api/v1/trips/{trip_id}/position", json=ping)
        )
        duplicate = asyncio.run(
            _request("POST", f"/api/v1/trips/{trip_id}/position", json=ping)
        )
        older = asyncio.run(
            _request(
                "POST", f"/api/v1/trips/{trip_id}/position",
                json={**ping, "recordedAt": (
                    recorded_at - timedelta(milliseconds=100)
                ).isoformat()},
            )
        )
        assert arrived.status_code == 200, arrived.text
        assert arrived.json()["phase"] == "at_station"
        assert arrived.json()["positionAccepted"] is True
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["positionAccepted"] is False
        assert older.status_code == 200 and older.json()["positionAccepted"] is False

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT status, provenance FROM planned_arrivals "
                    "WHERE arrival_id=:arrival_id"
                ),
                {"arrival_id": f"TRIP_{UUID(trip_id).hex}"},
            ).mappings().one()
            position_count = connection.scalar(
                text("SELECT count(*) FROM trip_positions WHERE trip_id=CAST(:id AS uuid)"),
                {"id": trip_id},
            )
        assert row["status"] == "arrived"
        assert row["provenance"]["tripId"] == trip_id
        assert position_count == 1
    finally:
        app.state.trip_service = old_service
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM planned_arrivals WHERE provenance->>'tripId'=:id"),
                    {"id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id=CAST(:id AS uuid)"),
                    {"id": trip_id},
                )
        engine.dispose()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_decline_accept_and_cancel_keep_planned_arrival_in_sync() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    old_service = app.state.trip_service
    app.state.trip_service = TripService(
        DatabaseTripRepository(engine), app.state.search_result_store,
        AppConfigRepository(app.state.settings, engine), app.state.search_service,
        app.state.station_repository, app.state.station_status_repository,
        app.state.vehicle_repository,
    )
    trip_id = None
    try:
        search = asyncio.run(
            _request(
                "POST", "/api/v1/search/stations",
                json={"origin": {"lat": 10.7075, "lng": 106.705},
                      "vehicleId": "EV_VF7_ECO", "batteryPct": 80},
            )
        )
        assert search.status_code == 200, search.text
        stations = [item["station"]["id"] for item in search.json()["stations"]]
        assert len(stations) >= 3
        created = asyncio.run(
            _request(
                "POST", "/api/v1/trips",
                json={"searchId": search.json()["searchId"], "stationId": stations[0]},
            )
        )
        assert created.status_code == 201, created.text
        trip_id = created.json()["id"]
        unchanged = asyncio.run(
            _request(
                "PATCH", f"/api/v1/trips/{trip_id}",
                json={"action": "accept", "stationId": stations[0]},
            )
        )
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["routeVersion"] == 0
        declined = asyncio.run(
            _request(
                "PATCH", f"/api/v1/trips/{trip_id}", json={"action": "decline"}
            )
        )
        assert declined.status_code == 200, declined.text
        assert declined.json()["stationId"] != stations[0]
        assert declined.json()["routeVersion"] == 1

        accepted = asyncio.run(
            _request(
                "PATCH", f"/api/v1/trips/{trip_id}",
                json={"action": "accept", "stationId": stations[2]},
            )
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["stationId"] == stations[2]
        assert accepted.json()["routeVersion"] == 2
        assert DatabaseTripRepository(engine).get(trip_id).route_version == 2

        cancelled = asyncio.run(
            _request(
                "PATCH", f"/api/v1/trips/{trip_id}", json={"action": "cancel"}
            )
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["phase"] == "cancelled"
        with engine.connect() as connection:
            statuses = connection.execute(
                text(
                    "SELECT status FROM planned_arrivals "
                    "WHERE provenance->>'tripId'=:id ORDER BY created_at"
                ),
                {"id": trip_id},
            ).scalars().all()
            versions = connection.scalar(
                text("SELECT count(*) FROM trip_events WHERE trip_id=CAST(:id AS uuid) "
                     "AND type='reroute'"),
                {"id": trip_id},
            )
        assert statuses == ["cancelled", "cancelled", "cancelled"]
        assert versions == 2
    finally:
        app.state.trip_service = old_service
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM planned_arrivals WHERE provenance->>'tripId'=:id"),
                    {"id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id=CAST(:id AS uuid)"),
                    {"id": trip_id},
                )
        engine.dispose()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_direct_trip_arrives_without_planned_station() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    old_service = app.state.trip_service
    app.state.trip_service = TripService(
        DatabaseTripRepository(engine), app.state.search_result_store,
        AppConfigRepository(app.state.settings, engine), app.state.search_service,
        app.state.station_repository, app.state.station_status_repository,
        app.state.vehicle_repository,
    )
    trip_id = None
    try:
        destination = {"lat": 10.806, "lng": 106.687}
        search = asyncio.run(
            _request(
                "POST", "/api/v1/search/route",
                json={"origin": {"lat": 10.7075, "lng": 106.705},
                      "destination": destination, "vehicleId": "EV_VF7_ECO",
                      "batteryPct": 80},
            )
        )
        assert search.status_code == 200 and search.json()["case"] == "enough"
        created = asyncio.run(
            _request(
                "POST", "/api/v1/trips",
                json={"searchId": search.json()["searchId"]},
            )
        )
        assert created.status_code == 201, created.text
        trip_id = created.json()["id"]
        assert created.json()["phase"] == "to_destination"
        arrived = asyncio.run(
            _request(
                "POST", f"/api/v1/trips/{trip_id}/position",
                json={"location": destination,
                      "recordedAt": (datetime.now(UTC) + timedelta(seconds=1)).isoformat()},
            )
        )
        assert arrived.status_code == 200, arrived.text
        assert arrived.json()["phase"] == "arrived"
        with engine.connect() as connection:
            count = connection.scalar(
                text("SELECT count(*) FROM planned_arrivals WHERE provenance->>'tripId'=:id"),
                {"id": trip_id},
            )
        assert count == 0
    finally:
        app.state.trip_service = old_service
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM trips WHERE id=CAST(:id AS uuid)"),
                    {"id": trip_id},
                )
        engine.dispose()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_off_route_replan_respects_cooldown(monkeypatch) -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    old_service = app.state.trip_service
    service = TripService(
        DatabaseTripRepository(engine), app.state.search_result_store,
        AppConfigRepository(app.state.settings, engine), app.state.search_service,
        app.state.station_repository, app.state.station_status_repository,
        app.state.vehicle_repository,
    )
    app.state.trip_service = service
    trip_id = None
    try:
        search = asyncio.run(
            _request(
                "POST", "/api/v1/search/stations",
                json={"origin": {"lat": 10.7075, "lng": 106.705},
                      "vehicleId": "EV_VF7_ECO", "batteryPct": 80},
            )
        )
        assert search.status_code == 200, search.text
        station_id = search.json()["stations"][0]["station"]["id"]
        created = asyncio.run(
            _request(
                "POST", "/api/v1/trips",
                json={"searchId": search.json()["searchId"], "stationId": station_id},
            )
        )
        assert created.status_code == 201, created.text
        trip_id = created.json()["id"]
        snapshot = app.state.search_result_store.get(search.json()["searchId"])
        old_option = snapshot.response.stations[0]
        rerouted_geometry = ((106.715, 10.700), *old_option.route.geometry[1:])
        new_route = old_option.route.model_copy(
            update={"route_id": "test-reroute", "geometry": rerouted_geometry}
        )
        new_option = old_option.model_copy(update={"route": new_route})
        new_result = snapshot.response.model_copy(
            update={"stations": (new_option, *snapshot.response.stations[1:])}
        )
        monkeypatch.setattr(service._search_service, "search_stations", lambda *a, **k: new_result)

        t0 = datetime.now(UTC) + timedelta(seconds=1)
        first = asyncio.run(
            _request(
                "POST", f"/api/v1/trips/{trip_id}/position",
                json={"location": {"lat": 10.700, "lng": 106.715},
                      "recordedAt": t0.isoformat(), "batteryPct": 75},
            )
        )
        assert first.status_code == 200, first.text
        assert first.json()["routeVersion"] == 1
        assert "OFF_ROUTE" in first.json()["rerouteReasons"]
        second = asyncio.run(
            _request(
                "POST", f"/api/v1/trips/{trip_id}/position",
                json={"location": {"lat": 10.695, "lng": 106.720},
                      "recordedAt": (t0 + timedelta(seconds=2)).isoformat(),
                      "batteryPct": 74},
            )
        )
        assert second.status_code == 200, second.text
        assert second.json()["routeVersion"] == 1
    finally:
        app.state.trip_service = old_service
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM planned_arrivals WHERE provenance->>'tripId'=:id"),
                    {"id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id=CAST(:id AS uuid)"),
                    {"id": trip_id},
                )
        engine.dispose()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_route_trip_progresses_through_station_to_destination() -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    old_service = app.state.trip_service
    app.state.trip_service = TripService(
        DatabaseTripRepository(engine), app.state.search_result_store,
        AppConfigRepository(app.state.settings, engine), app.state.search_service,
        app.state.station_repository, app.state.station_status_repository,
        app.state.vehicle_repository,
    )
    trip_id = None
    try:
        destination = {"lat": 10.806, "lng": 106.687}
        search = asyncio.run(
            _request(
                "POST", "/api/v1/search/route",
                json={"origin": {"lat": 10.7075, "lng": 106.705},
                      "destination": destination, "vehicleId": "EV_VF5_PLUS",
                      "batteryPct": 14},
            )
        )
        assert search.status_code == 200 and search.json()["case"] == "needCharge"
        option = search.json()["stations"][0]
        created = asyncio.run(
            _request(
                "POST", "/api/v1/trips",
                json={"searchId": search.json()["searchId"],
                      "stationId": option["station"]["id"]},
            )
        )
        assert created.status_code == 201, created.text
        trip_id = created.json()["id"]
        t0 = datetime.now(UTC) + timedelta(seconds=1)
        at_station = asyncio.run(
            _request(
                "POST", f"/api/v1/trips/{trip_id}/position",
                json={"location": option["station"]["location"],
                      "recordedAt": t0.isoformat(), "batteryPct": 12},
            )
        )
        assert at_station.status_code == 200, at_station.text
        assert at_station.json()["phase"] == "at_station"
        corrected = asyncio.run(
            _request(
                "PATCH", f"/api/v1/trips/{trip_id}",
                json={"action": "correctBattery", "batteryPct": 80},
            )
        )
        assert corrected.status_code == 200 and corrected.json()["batteryPct"] == 80
        departed = asyncio.run(
            _request(
                "PATCH", f"/api/v1/trips/{trip_id}", json={"action": "depart"}
            )
        )
        assert departed.status_code == 200 and departed.json()["phase"] == "to_destination"
        arrived = asyncio.run(
            _request(
                "POST", f"/api/v1/trips/{trip_id}/position",
                json={"location": destination,
                      "recordedAt": (t0 + timedelta(minutes=1)).isoformat(),
                      "batteryPct": 60},
            )
        )
        assert arrived.status_code == 200, arrived.text
        assert arrived.json()["phase"] == "arrived"
        with engine.connect() as connection:
            status = connection.scalar(
                text("SELECT status FROM planned_arrivals "
                     "WHERE provenance->>'tripId'=:id"),
                {"id": trip_id},
            )
        assert status == "arrived"
    finally:
        app.state.trip_service = old_service
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM planned_arrivals WHERE provenance->>'tripId'=:id"),
                    {"id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id=CAST(:id AS uuid)"),
                    {"id": trip_id},
                )
        engine.dispose()


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="PostgreSQL test database required")
def test_replan_detects_battery_eta_and_station_failure(monkeypatch) -> None:
    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    repository = DatabaseTripRepository(engine)
    old_service = app.state.trip_service
    service = TripService(
        repository, app.state.search_result_store,
        AppConfigRepository(app.state.settings, engine), app.state.search_service,
        app.state.station_repository, app.state.station_status_repository,
        app.state.vehicle_repository,
    )
    app.state.trip_service = service
    trip_id = None
    try:
        search = asyncio.run(
            _request(
                "POST", "/api/v1/search/stations",
                json={"origin": {"lat": 10.7075, "lng": 106.705},
                      "vehicleId": "EV_VF7_ECO", "batteryPct": 80},
            )
        )
        assert search.status_code == 200, search.text
        station_location = search.json()["stations"][0]["station"]["location"]
        created = asyncio.run(
            _request(
                "POST", "/api/v1/trips",
                json={"searchId": search.json()["searchId"],
                      "stationId": search.json()["stations"][0]["station"]["id"]},
            )
        )
        assert created.status_code == 201, created.text
        trip_id = created.json()["id"]
        monkeypatch.setattr(
            service, "_reroute", lambda *args, **kwargs: repository.get(trip_id)
        )
        origin = {"lat": 10.7075, "lng": 106.705}
        t0 = datetime.now(UTC) + timedelta(seconds=1)
        low_battery = asyncio.run(
            _request(
                "POST", f"/api/v1/trips/{trip_id}/position",
                json={"location": origin, "recordedAt": t0.isoformat(),
                      "batteryPct": 0},
            )
        )
        assert low_battery.status_code == 200, low_battery.text
        assert "INSUFFICIENT_BATTERY" in low_battery.json()["rerouteReasons"]
        late = asyncio.run(
            _request(
                "POST", f"/api/v1/trips/{trip_id}/position",
                json={"location": origin,
                      "recordedAt": (t0 + timedelta(minutes=10)).isoformat(),
                      "batteryPct": 80},
            )
        )
        assert late.status_code == 200, late.text
        assert "ETA_INCREASED" in late.json()["rerouteReasons"]
        monkeypatch.setattr(
            service, "_statuses",
            SimpleNamespace(get=lambda _: SimpleNamespace(operational_ports=0)),
        )
        offline = asyncio.run(
            _request(
                "POST", f"/api/v1/trips/{trip_id}/position",
                json={"location": station_location,
                      "recordedAt": (t0 + timedelta(minutes=10, seconds=2)).isoformat(),
                      "batteryPct": 80},
            )
        )
        assert offline.status_code == 200, offline.text
        assert "STATION_UNAVAILABLE" in offline.json()["rerouteReasons"]
        assert offline.json()["phase"] == "to_station"
    finally:
        app.state.trip_service = old_service
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM planned_arrivals WHERE provenance->>'tripId'=:id"),
                    {"id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id=CAST(:id AS uuid)"),
                    {"id": trip_id},
                )
        engine.dispose()
