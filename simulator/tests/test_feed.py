import json
import threading
from datetime import UTC, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from script import feed
from script.__main__ import main
from script.occupancy import BUCKET

UUID_A = "00000000-0000-0000-0000-00000000000a"
UUID_B = "00000000-0000-0000-0000-00000000000b"
START = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)  # Monday 00:00 UTC


def write_fixtures(tmp_path: Path, days: int = 8) -> tuple[Path, Path]:
    stations_sql = tmp_path / "stations.sql"
    stations_sql.write_text(
        "INSERT INTO public.stations (id, code, name) VALUES\n"
        f"    ('{UUID_A}', 'ST_A', 'A'),\n"
        f"    ('{UUID_B}', 'ST_B', 'B');\n",
        encoding="utf-8",
    )
    lines = ["station_id,bucket_at,total_ports,operational_ports,occupied_ports"]
    for index in range(days * 288):
        # Occupancy depends on the bucket index so a wrong shift shows up in the assertions.
        moment = (START + index * BUCKET).astimezone(timezone(timedelta(hours=7))).isoformat()
        lines.append(f"{UUID_A},{moment},4,4,{index % 5}")
        lines.append(f"{UUID_B},{moment},2,2,{index % 3}")
    csv_path = tmp_path / "station_occupancy_5m.csv"
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, stations_sql


@pytest.fixture
def replay(tmp_path: Path) -> feed.Replay:
    csv_path, stations_sql = write_fixtures(tmp_path)
    return feed.load_replay(csv_path, stations_sql)


def test_uuids_are_mapped_to_station_codes(replay: feed.Replay) -> None:
    assert set(replay.readings) == {"ST_A", "ST_B"}
    assert replay.start == START
    assert replay.end == START + (8 * 288 - 1) * BUCKET


def test_a_moment_inside_the_data_replays_that_exact_bucket(replay: feed.Replay) -> None:
    at = START + timedelta(days=2, hours=3, minutes=7, seconds=30)
    source, updates = feed.build_updates(replay, at)

    expected_index = (2 * 288) + 3 * 12 + 1
    assert source == START + expected_index * BUCKET
    assert [item["stationId"] for item in updates] == ["ST_A", "ST_B"]
    assert updates[0]["occupiedPorts"] == expected_index % 5
    assert updates[1]["occupiedPorts"] == expected_index % 3
    assert updates[0]["totalPorts"] == updates[0]["operationalPorts"] == 4
    assert updates[0]["reportedAt"] == at.isoformat()


def test_a_moment_after_the_data_is_shifted_by_whole_weeks(replay: feed.Replay) -> None:
    at = START + timedelta(days=30, hours=5, minutes=20)  # a Wednesday, 3 weeks+ after start
    source, _ = feed.build_updates(replay, at)

    floor = feed.floor_bucket(at)
    assert replay.end - feed.WEEK < source <= replay.end
    assert (floor - source) % feed.WEEK == timedelta(0)


def test_a_moment_before_the_data_is_shifted_forward(replay: feed.Replay) -> None:
    at = START - timedelta(days=3)
    source, _ = feed.build_updates(replay, at)

    assert replay.start <= source <= replay.end
    assert source.weekday() == at.weekday()


def test_data_shorter_than_a_week_cannot_be_replayed(tmp_path: Path) -> None:
    csv_path, stations_sql = write_fixtures(tmp_path, days=2)
    short = feed.load_replay(csv_path, stations_sql)

    with pytest.raises(ValueError, match="không có bucket cùng thứ/giờ"):
        feed.build_updates(short, START + timedelta(days=20))


def test_csv_with_an_unmapped_station_is_rejected(tmp_path: Path) -> None:
    csv_path, stations_sql = write_fixtures(tmp_path)
    stations_sql.write_text(
        f"INSERT INTO public.stations (id, code, name) VALUES\n    ('{UUID_A}', 'ST_A', 'A');\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="không có trong stations.sql"):
        feed.load_replay(csv_path, stations_sql)


def test_next_beat_is_the_next_five_minute_mark_plus_delay() -> None:
    now = datetime(2026, 10, 12, 9, 7, 30, tzinfo=UTC)

    assert feed.seconds_until_next_beat(now, 15) == 2 * 60 + 30 + 15
    on_boundary = datetime(2026, 10, 12, 9, 10, 0, tzinfo=UTC)
    assert feed.seconds_until_next_beat(on_boundary, 15) == 5 * 60 + 15


class _Backend:
    """Tiny stand-in for the backend endpoint; records requests and answers from a script."""

    def __init__(self, unknown_stations: set[str] | None = None, fail_first: int = 0) -> None:
        self.requests: list[dict] = []
        self.unknown_stations = unknown_stations or set()
        self.fail_first = fail_first
        backend = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                backend.requests.append(
                    {"path": self.path, "key": self.headers.get("X-API-Key"), "body": body}
                )
                if backend.fail_first:
                    backend.fail_first -= 1
                    return self._reply(503, {"error": {"message": "busy"}})
                for item in body["updates"]:
                    if item["stationId"] in backend.unknown_stations:
                        message = f"station not found: {item['stationId']}"
                        return self._reply(404, {"error": {"message": message}})
                return self._reply(200, {"updated": len(body["updates"])})

            def _reply(self, status: int, payload: dict) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def backend():
    server = _Backend()
    yield server
    server.close()


def test_a_batch_is_posted_with_the_api_key(replay: feed.Replay, backend: _Backend) -> None:
    written = feed.feed_once(
        replay, at=START + timedelta(hours=1), url=backend.url, api_key="secret"
    )

    assert written == 2
    (request,) = backend.requests
    assert request["path"] == "/api/v1/internal/station-occupancy"
    assert request["key"] == "secret"
    assert {item["stationId"] for item in request["body"]["updates"]} == {"ST_A", "ST_B"}


def test_an_unknown_station_is_dropped_and_the_rest_is_resent(replay: feed.Replay) -> None:
    server = _Backend(unknown_stations={"ST_B"})
    try:
        written = feed.feed_once(replay, at=START, url=server.url, api_key="secret")
    finally:
        server.close()

    assert written == 1
    assert len(server.requests) == 2
    assert [i["stationId"] for i in server.requests[1]["body"]["updates"]] == ["ST_A"]


def test_server_errors_are_retried_then_succeed(replay: feed.Replay) -> None:
    server = _Backend(fail_first=2)
    pauses: list[float] = []
    try:
        written = feed.feed_once(
            replay, at=START, url=server.url, api_key="secret", sleep=pauses.append
        )
    finally:
        server.close()

    assert written == 2 and len(server.requests) == 3
    assert pauses == [2.0, 4.0]


def test_missing_api_key_is_a_clear_error(replay: feed.Replay) -> None:
    with pytest.raises(ValueError, match="INTERNAL_API_KEY"):
        feed.feed_once(replay, at=START, url="http://127.0.0.1:9", api_key=None)


def test_loop_keeps_going_after_a_failed_beat(replay: feed.Replay, capsys) -> None:
    moments = iter(START + timedelta(minutes=5 * n) for n in range(10))
    pauses: list[float] = []
    feed.run_loop(
        replay,
        url="http://127.0.0.1:9",  # nothing listens here: every beat fails to connect
        api_key="secret",
        delay_s=15,
        now=lambda: next(moments),
        sleep=pauses.append,
        iterations=3,
    )

    err = capsys.readouterr().err
    assert err.count("lỗi:") == 3
    assert len(pauses) >= 2


def test_cli_dry_run_prints_the_batch_without_calling_the_backend(
    tmp_path: Path, capsys
) -> None:
    csv_path, stations_sql = write_fixtures(tmp_path)

    code = main(
        [
            "feed",
            "--csv", str(csv_path),
            "--stations-sql", str(stations_sql),
            "--dry-run",
            "--at", "2026-08-04T10:05:00+00:00",
        ]
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "dry-run" in out and '"stationId": "ST_A"' in out
