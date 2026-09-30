import asyncio
from dataclasses import replace
from pathlib import Path

import httpx

from backend.app.config import load_settings
from backend.app.domain.forecasting import OccupancyForecastService
from backend.app.domain.repositories import load_domain_data
from backend.app.health import run_startup_checks
from backend.app.main import app


def _statuses(report: dict[str, object]) -> dict[str, str]:
    return {check["name"]: check["status"] for check in report["checks"]}


def test_health_checks_endpoint_reports_degraded_demo_without_model() -> None:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/checks")

    response = asyncio.run(request())
    body = response.json()

    assert response.status_code == 200
    assert body["demo_ready"] is True
    assert body["status"] in {"ok", "degraded"}
    assert _statuses(body)["data_files"] == "ok"
    assert _statuses(body)["route_cache_coverage"] == "ok"
    assert _statuses(body)["occupancy_model"] == "warn"


def test_missing_data_file_fails_the_check(tmp_path: Path) -> None:
    settings = replace(load_settings(), data_dir=tmp_path)
    data = load_domain_data(load_settings().data_dir)

    report = run_startup_checks(settings, data, OccupancyForecastService())

    assert report["status"] == "fail"
    assert report["demo_ready"] is False
    assert _statuses(report)["data_files"] == "fail"


def test_missing_goong_key_only_degrades() -> None:
    settings = replace(load_settings(), goong_api_key=None)
    data = load_domain_data(settings.data_dir)

    report = run_startup_checks(settings, data, OccupancyForecastService())

    assert report["demo_ready"] is True
    assert _statuses(report)["goong_api"] == "warn"


def test_configured_goong_key_is_ok() -> None:
    settings = replace(load_settings(), goong_api_key="test-key")
    data = load_domain_data(settings.data_dir)

    report = run_startup_checks(settings, data, OccupancyForecastService())

    assert _statuses(report)["goong_api"] == "ok"