import asyncio

import httpx

from backend.app.main import app


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


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
    assert len(responses[0].json()) == 16
    assert len(responses[3].json()) == 3
    assert len(responses[4].json()) == 4
    assert responses[5].json()["resolution_source"] == "cache"
    assert responses[6].json()["prediction_source"] == "persistence"


def test_required_end_to_end_recommendation_scenarios() -> None:
    async def run_scenarios():
        await _request("POST", "/demo/reset")
        normal = await _request(
            "POST",
            "/journey/recommend",
            json={
                "scenario_id": "SCN_NORMAL",
                "origin": {"lat": 10.7075, "lon": 106.705},
                "destination": {"lat": 10.806, "lon": 106.687},
                "departure_at": "2026-09-26T18:00:00+07:00",
            },
        )
        await _request("POST", "/demo/reset")
        low_soc = await _request(
            "POST",
            "/journey/recommend",
            json={"scenario_id": "SCN_LOW_SOC"},
        )
        await _request("POST", "/demo/reset")
        congestion_before = await _request(
            "POST",
            "/journey/recommend",
            json={"scenario_id": "SCN_CONGESTION_REROUTE"},
        )
        congestion_after = await _request(
            "POST",
            "/journey/recommend",
            json={
                "scenario_id": "SCN_CONGESTION_REROUTE",
                "apply_scenario_events": True,
            },
        )
        await _request("POST", "/demo/reset")
        outage_before = await _request(
            "POST",
            "/journey/recommend",
            json={"scenario_id": "SCN_PORT_OUTAGE_REROUTE"},
        )
        outage_after = await _request(
            "POST",
            "/journey/recommend",
            json={
                "scenario_id": "SCN_PORT_OUTAGE_REROUTE",
                "apply_scenario_events": True,
            },
        )
        return normal, low_soc, congestion_before, congestion_after, outage_before, outage_after

    normal, low_soc, congestion_before, congestion_after, outage_before, outage_after = (
        asyncio.run(run_scenarios())
    )
    assert all(
        response.status_code == 200
        for response in (
            normal,
            low_soc,
            congestion_before,
            congestion_after,
            outage_before,
            outage_after,
        )
    )
    assert normal.json()["recommendations"][0]["route"]["geometry"]["type"] == (
        "LineString"
    )
    assert normal.json()["recommendations"][0]["energy_to_add_kwh"] > 0
    assert normal.json()["recommendations"][0]["station_id"] == "ST_VF_LA_VELA"
    assert any(
        "INSUFFICIENT_SOC_RESERVE" in item["reason_codes"]
        for item in low_soc.json()["excluded_candidates"]
    )
    assert congestion_before.json()["recommendations"][0]["station_id"] == (
        "ST_VF_LA_VELA"
    )
    assert congestion_after.json()["recommendations"][0]["station_id"] != (
        "ST_VF_LA_VELA"
    )
    assert outage_before.json()["recommendations"][0]["station_id"] == "ST_VF_LA_VELA"
    assert outage_after.json()["recommendations"][0]["station_id"] != "ST_VF_LA_VELA"


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
        created = await _request("POST", "/planned-arrivals", json=payload)
        cancelled = await _request(
            "POST", "/planned-arrivals/ARR_API_TEST/cancel"
        )
        return created, cancelled

    created, cancelled = asyncio.run(lifecycle())
    assert created.status_code == 200
    assert created.json()["status"] == "planned"
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


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
        committed = await _request(
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
        cancelled = await _request(
            "POST", f"/planned-arrivals/{committed.json()['arrival_id']}/cancel"
        )
        return invalid, committed, cancelled

    invalid, committed, cancelled = asyncio.run(lifecycle())
    assert invalid.status_code == 422
    assert committed.status_code == 200
    assert committed.json()["eta_at"] == "2099-01-01T10:10:00+07:00"
    assert committed.json()["route_id"] == "LIVE_GOONG_DEMO"
    assert cancelled.json()["status"] == "cancelled"
