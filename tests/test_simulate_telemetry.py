from __future__ import annotations

import argparse
from datetime import UTC, datetime

import pytest

from backend.app.domain.realtime import StationTelemetrySnapshot
from scripts import simulate_telemetry


def _station(*, station_id: str = "ST_TEST") -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {
            "station_id": station_id,
            "total_ports": 4,
            "connectors": [
                {"type": "CCS2", "count": 2},
                {"type": "Type2", "count": 2},
            ],
        },
    }


def test_simulation_snapshot_is_complete_and_explicitly_synthetic() -> None:
    snapshot = simulate_telemetry.build_snapshot(
        _station(), observed_at=datetime(2026, 10, 9, 8, 0, tzinfo=UTC), cycle=0
    )

    assert snapshot["data_source"] == "simulated"
    assert snapshot["station_id"] == "ST_TEST"
    assert len(snapshot["ports"]) == 4
    assert [port["connector_types"][0] for port in snapshot["ports"]] == [
        "CCS2",
        "CCS2",
        "Type2",
        "Type2",
    ]
    assert [port["state"] for port in snapshot["ports"]] == [
        "available",
        "available",
        "available",
        "available",
    ]


def test_simulation_snapshot_varies_repeatably_by_cycle() -> None:
    station = _station()
    observed_at = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
    first = simulate_telemetry.build_snapshot(station, observed_at=observed_at, cycle=5)
    replay = simulate_telemetry.build_snapshot(station, observed_at=observed_at, cycle=5)
    next_cycle = simulate_telemetry.build_snapshot(station, observed_at=observed_at, cycle=6)

    assert first == replay
    assert [port["state"] for port in first["ports"]] == [
        "available",
        "charging",
        "charging",
        "charging",
    ]
    assert [port["state"] for port in next_cycle["ports"]] != [
        port["state"] for port in first["ports"]
    ]


def test_simulation_snapshot_rejects_inconsistent_catalog() -> None:
    station = _station()
    station["properties"]["total_ports"] = 3  # type: ignore[index]

    with pytest.raises(ValueError, match="connector counts do not match"):
        simulate_telemetry.build_snapshot(
            station, observed_at=datetime.now(UTC), cycle=0
        )


def test_simulation_snapshot_can_represent_confirmed_and_unknown_queue() -> None:
    observed_at = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
    snapshot = simulate_telemetry.build_snapshot(
        _station(), observed_at=observed_at, cycle=0, queue_length=2
    )
    unknown = simulate_telemetry.build_snapshot(
        _station(), observed_at=observed_at, cycle=0, queue_unknown=True
    )

    assert snapshot["data_source"] == "simulated"
    assert len(snapshot["queue"]) == 2
    assert [entry["queue_position"] for entry in snapshot["queue"]] == [1, 2]
    assert unknown["queue"] is None
    StationTelemetrySnapshot.model_validate(snapshot)
    StationTelemetrySnapshot.model_validate(unknown)


def test_simulation_snapshot_rejects_incompatible_queue_options() -> None:
    with pytest.raises(ValueError, match="unknown"):
        simulate_telemetry.build_snapshot(
            _station(), observed_at=datetime.now(UTC), cycle=0,
            queue_length=1, queue_unknown=True,
        )


def test_demo_mode_guard_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        simulate_telemetry,
        "request_json",
        lambda url: {"demo_mode": False},
    )

    with pytest.raises(RuntimeError, match="demo_mode=true"):
        simulate_telemetry.require_demo_mode("http://127.0.0.1:8000")


def test_api_url_preserves_api_prefix_and_quotes_query() -> None:
    assert simulate_telemetry.api_url(
        "https://localhost:8080/api", "/stations", {"after_station_id": "ST A"}
    ) == "https://localhost:8080/api/stations?after_station_id=ST+A"


def test_api_url_rejects_query_in_base_url() -> None:
    with pytest.raises(ValueError, match="query or fragment"):
        simulate_telemetry.api_url("http://localhost:8000?token=secret", "/health/ready")


def test_load_stations_follows_cursor_until_selected_station_is_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_page = [_station(station_id=f"ST_{index:03d}") for index in range(200)]
    second_page = [_station(station_id="ST_200")]
    requested_urls: list[str] = []

    def fake_request(url: str) -> list[dict[str, object]]:
        requested_urls.append(url)
        if "after_station_id=ST_199" in url:
            return second_page
        return first_page

    monkeypatch.setattr(simulate_telemetry, "request_json", fake_request)
    stations = simulate_telemetry.load_stations(
        "http://127.0.0.1:8000",
        station_ids={"ST_200"},
        max_stations=1,
    )

    assert [station["properties"]["station_id"] for station in stations] == ["ST_200"]
    assert len(requested_urls) == 2
    assert "limit=200" in requested_urls[0]


def test_interval_parser_rejects_non_finite_values() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="finite"):
        simulate_telemetry.positive_float("inf")
    with pytest.raises(argparse.ArgumentTypeError, match="finite"):
        simulate_telemetry.nonnegative_float("nan")


def test_request_pacing_keeps_global_minimum_between_writes() -> None:
    assert simulate_telemetry.request_delay_remaining(None, 10.0, 2.1) == 0
    assert simulate_telemetry.request_delay_remaining(10.0, 11.0, 2.1) == pytest.approx(1.1)
    assert simulate_telemetry.request_delay_remaining(10.0, 13.0, 2.1) == 0
