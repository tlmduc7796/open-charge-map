import asyncio

import httpx

from backend.app.domain.queue_lab import (
    QueueLabPort,
    SyntheticDuration,
    demo_request,
    simulate_queue_lab,
)
from backend.app.main import app


def test_fixed_demo_is_28_minutes_for_deterministic_and_monte_carlo_runs() -> None:
    result = simulate_queue_lab(demo_request())

    assert result.estimated_wait_min == 28
    assert result.estimated_start_at.isoformat() == "2026-10-01T10:28:00+07:00"
    assert result.monte_carlo.p10_wait_min == 28
    assert result.monte_carlo.p50_wait_min == 28
    assert result.monte_carlo.p90_wait_min == 28
    assert result.monte_carlo.probability_wait_over_threshold == 0
    assert "SEEDED_TIMELINE_IS_ONE_SAMPLE" in result.caveats
    assert [(entry.port_id, entry.vehicle_id) for entry in result.timeline] == [
        ("A", "ACTIVE_A"),
        ("B", "ACTIVE_B"),
        ("A", "QUEUE_1"),
        ("A", "DEMO_REQUESTER"),
    ]


def test_uniform_duration_is_reproducible_with_a_fixed_seed() -> None:
    request = demo_request().model_copy(
        update={
            "ports": (
                QueueLabPort(
                    port_id="A",
                    connector_types=("CCS2",),
                    state="charging",
                    remaining_port_release=SyntheticDuration(kind="uniform", min_min=5, max_min=15),
                ),
                demo_request().ports[1],
            ),
            "trials": 100,
            "seed": 7,
        }
    )

    first = simulate_queue_lab(request)
    second = simulate_queue_lab(request)

    assert first.monte_carlo == second.monte_carlo
    assert first.monte_carlo.p10_wait_min < first.monte_carlo.p50_wait_min
    assert first.monte_carlo.p50_wait_min < first.monte_carlo.p90_wait_min
    assert 0 < first.monte_carlo.probability_wait_over_threshold < 1


def test_queue_lab_api_exposes_demo_and_simulation() -> None:
    async def run() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            scenario = await client.get("/queue-lab/default-scenario")
            result = await client.post("/queue-lab/simulate", json=scenario.json())
            return scenario, result

    scenario, result = asyncio.run(run())

    assert scenario.status_code == result.status_code == 200
    assert result.json()["estimated_wait_min"] == 28
    assert result.json()["monte_carlo"]["p50_wait_min"] == 28
