import asyncio

import httpx

from backend.app.main import app


def test_health_endpoint() -> None:
    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "Smart EV Journey API",
        "environment": "development",
        "demo_mode": True,
    }


def test_application_startup_loaded_domain_data() -> None:
    assert len(app.state.domain_data.stations.all()) == 3
    assert len(app.state.domain_data.vehicles.all()) == 3
    assert len(app.state.domain_data.station_statuses.all()) == 3
    assert len(app.state.domain_data.planned_arrivals.all()) == 4
    assert app.state.occupancy_forecast_service is not None
    assert app.state.wait_estimator is not None
