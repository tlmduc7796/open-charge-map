import asyncio

import httpx

from backend.app.main import app


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_station_vehicle_route_and_model_endpoints() -> None:
    async def run_requests():
        return await asyncio.gather(
            _request("GET", "/stations"),
            _request("GET", "/stations/ST_EVO_LAVIDA_Q7"),
            _request("GET", "/stations/ST_EVO_LAVIDA_Q7/status"),
            _request("GET", "/vehicles"),
            _request(
                "POST",
                "/route",
                json={
                    "origin": {"lat": 10.7075, "lon": 106.705},
                    "destination": {"lat": 10.806, "lon": 106.687},
                },
            ),
            _request("GET", "/model/status"),
        )

    responses = asyncio.run(run_requests())
    assert all(response.status_code == 200 for response in responses)
    assert len(responses[0].json()) == 16
    assert len(responses[3].json()) == 3
    assert responses[4].json()["geometry"]["type"] == "LineString"
    assert responses[5].json()["prediction_source"] == "default"


def test_unknown_station_returns_404() -> None:
    response = asyncio.run(_request("GET", "/stations/ST_DOES_NOT_EXIST"))

    assert response.status_code == 404


def test_scenario_demo_and_planned_arrival_endpoints_are_removed() -> None:
    async def run_requests():
        return await asyncio.gather(
            _request("GET", "/demo/scenarios"),
            _request("POST", "/demo/reset"),
            _request("POST", "/journey/recommend", json={"scenario_id": "SCN_NORMAL"}),
            _request("GET", "/planned-arrivals"),
        )

    assert [response.status_code for response in asyncio.run(run_requests())] == [
        404, 404, 404, 404
    ]
