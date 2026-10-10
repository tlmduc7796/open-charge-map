#!/usr/bin/env python3
"""Send explicitly simulated station telemetry to a demo API instance.

This tool is for exercising the ingest and realtime path before an aggregator
is selected. It refuses to send data unless the caller opts in and the API
reports ``demo_mode=true``. It cannot provision operational release data.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from itertools import chain
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


def api_url(api_root: str, path: str, query: dict[str, str] | None = None) -> str:
    parts = urlsplit(api_root.rstrip("/"))
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("API URL must be an absolute HTTP(S) URL")
    if parts.query or parts.fragment:
        raise ValueError("API URL must not contain a query or fragment")
    root_path = parts.path.rstrip("/")
    return urlunsplit(
        (parts.scheme, parts.netloc, f"{root_path}/{path.lstrip('/')}", urlencode(query or {}), "")
    )


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    telemetry_key: str | None = None,
) -> Any:
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if telemetry_key is not None:
        headers["X-Telemetry-API-Key"] = telemetry_key
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"API request failed: {exc.reason}") from exc


def require_demo_mode(api_root: str) -> None:
    readiness = request_json(api_url(api_root, "/health/ready"))
    if not isinstance(readiness, dict) or readiness.get("demo_mode") is not True:
        raise RuntimeError("refusing simulated telemetry: API does not report demo_mode=true")


def load_stations(
    api_root: str,
    *,
    station_ids: set[str],
    max_stations: int,
) -> list[dict[str, Any]]:
    stations: list[dict[str, Any]] = []
    after_station_id: str | None = None
    while len(stations) < max_stations:
        query = {"limit": "200"}
        if after_station_id is not None:
            query["after_station_id"] = after_station_id
        page = request_json(api_url(api_root, "/stations", query))
        if not isinstance(page, list):
            raise RuntimeError("station catalog response is not a list")
        if not page:
            break
        for station in page:
            properties = station.get("properties", {})
            station_id = properties.get("station_id")
            if station_ids and station_id not in station_ids:
                continue
            stations.append(station)
            if len(stations) == max_stations:
                break
        found = {station.get("properties", {}).get("station_id") for station in stations}
        if station_ids and station_ids <= found:
            break
        last_station_id = page[-1].get("properties", {}).get("station_id")
        if not isinstance(last_station_id, str) or len(page) < 200:
            break
        after_station_id = last_station_id
    if station_ids:
        found = {station.get("properties", {}).get("station_id") for station in stations}
        missing = station_ids - found
        if missing:
            raise RuntimeError("unknown or out-of-range station IDs: " + ", ".join(sorted(missing)))
    if not stations:
        raise RuntimeError("no stations selected for simulation")
    return stations


def build_snapshot(
    station: dict[str, Any],
    *,
    observed_at: datetime,
    cycle: int,
    queue_length: int = 0,
    queue_unknown: bool = False,
) -> dict[str, Any]:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must include a timezone")
    if not 0 <= queue_length <= 2000:
        raise ValueError("queue_length must be between 0 and 2000")
    if queue_unknown and queue_length:
        raise ValueError("queue_length cannot be set when queue state is unknown")
    properties = station.get("properties")
    if not isinstance(properties, dict):
        raise ValueError("station record has no properties object")
    station_id = properties.get("station_id")
    connectors = properties.get("connectors")
    total_ports = properties.get("total_ports")
    if not isinstance(station_id, str) or not isinstance(connectors, list):
        raise ValueError("station record is missing station_id or connectors")
    if type(total_ports) is not int or total_ports < 1 or total_ports > 1000:
        raise ValueError("station total_ports must be between 1 and 1000")

    connector_types = chain.from_iterable(
        [connector["type"]] * connector["count"]
        for connector in connectors
        if isinstance(connector.get("type"), str)
        and type(connector.get("count")) is int
        and connector["count"] > 0
    )
    types = list(connector_types)
    if len(types) != total_ports:
        raise ValueError("station connector counts do not match total_ports")

    ports = []
    for index, connector_type in enumerate(types):
        phase = (cycle + index) % 10
        if phase < 6:
            port = {"state": "available"}
        elif phase < 9:
            port = {
                "state": "charging",
                "session_id": f"SIM-{station_id}-{cycle}-{index + 1}",
                "reported_remaining_port_release_min": float(5 + ((cycle + index) % 26)),
            }
        else:
            port = {"state": "out_of_service"}
        ports.append(
            {
                "port_id": f"SIM-{station_id}-{index + 1}",
                "connector_types": [connector_type],
                **port,
            }
        )
    queue = None if queue_unknown else [
        {
            "queue_id": f"SIM-Q-{station_id}-{cycle}-{position}",
            "queue_position": position,
            "entered_queue_at": (
                observed_at.astimezone(UTC) - timedelta(minutes=position * 3)
            ).isoformat(),
            "compatible_connector_types": [types[(position - 1) % len(types)]],
            "expected_charge_duration_min": float(25 + (position % 4) * 5),
        }
        for position in range(1, queue_length + 1)
    ]
    return {
        "station_id": station_id,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "ports": ports,
        "queue": queue,
        "avg_session_duration_min": 30.0,
        "data_source": "simulated",
    }


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be finite and positive")
    return parsed


def nonnegative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("value must be finite and non-negative")
    return parsed


def request_delay_remaining(
    last_write_at: float | None, now: float, minimum_delay_s: float
) -> float:
    if last_write_at is None:
        return 0.0
    return max(0.0, minimum_delay_s - (now - last_write_at))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url", default="http://127.0.0.1:8000", help="API root, optionally ending in /api"
    )
    parser.add_argument(
        "--station-id", action="append", default=[], help="station to simulate; repeatable"
    )
    parser.add_argument("--max-stations", type=int, default=10)
    parser.add_argument(
        "--cycles", type=int, default=1, help="number of snapshots per selected station"
    )
    parser.add_argument(
        "--queue-length", type=int, default=0, help="synthetic confirmed queue size"
    )
    parser.add_argument(
        "--queue-unknown", action="store_true", help="send unknown queue state (queue=null)"
    )
    parser.add_argument("--interval-s", type=positive_float, default=15.0)
    parser.add_argument(
        "--request-delay-s", type=nonnegative_float, default=2.1,
        help="delay between station writes to stay below the default API write rate limit",
    )
    parser.add_argument(
        "--confirm-demo-simulation", action="store_true",
        help="explicitly authorize sending simulated telemetry to a demo API",
    )
    args = parser.parse_args()
    if not args.confirm_demo_simulation:
        parser.error("pass --confirm-demo-simulation to authorize simulated writes")
    if not 1 <= args.max_stations <= 200:
        parser.error("--max-stations must be between 1 and 200")
    if not 1 <= args.cycles <= 10_000:
        parser.error("--cycles must be between 1 and 10000")
    if not 0 <= args.queue_length <= 2000:
        parser.error("--queue-length must be between 0 and 2000")
    if args.queue_unknown and args.queue_length:
        parser.error("--queue-length cannot be used with --queue-unknown")
    if not 0 <= args.request_delay_s <= 60:
        parser.error("--request-delay-s must be between 0 and 60")
    if len(args.station_id) > args.max_stations:
        parser.error("the number of --station-id arguments cannot exceed --max-stations")
    if any(not station_id.strip() for station_id in args.station_id):
        parser.error("--station-id values cannot be empty")
    if len(set(args.station_id)) != len(args.station_id):
        parser.error("--station-id values must be unique")

    telemetry_key = os.getenv("TELEMETRY_INGEST_API_KEY", "").strip()
    if not telemetry_key:
        parser.error("set TELEMETRY_INGEST_API_KEY in the environment")
    try:
        require_demo_mode(args.api_url)
        stations = load_stations(
            args.api_url,
            station_ids=set(args.station_id),
            max_stations=args.max_stations,
        )
        last_write_at: float | None = None
        last_cycle_started_at: float | None = None
        for cycle in range(args.cycles):
            now = time.monotonic()
            if last_cycle_started_at is not None:
                cycle_delay = max(
                    0.0, args.interval_s - (now - last_cycle_started_at)
                )
                if cycle_delay:
                    time.sleep(cycle_delay)
            last_cycle_started_at = time.monotonic()
            for station in stations:
                delay = request_delay_remaining(
                    last_write_at, time.monotonic(), args.request_delay_s
                )
                if delay:
                    time.sleep(delay)
                snapshot = build_snapshot(
                    station,
                    observed_at=datetime.now(UTC),
                    cycle=cycle,
                    queue_length=args.queue_length,
                    queue_unknown=args.queue_unknown,
                )
                station_id = snapshot["station_id"]
                request_json(
                    api_url(
                        args.api_url,
                        f"/realtime/stations/{quote(station_id, safe='')}/telemetry",
                    ),
                    method="PUT",
                    payload=snapshot,
                    telemetry_key=telemetry_key,
                )
                print(f"simulated snapshot accepted station_id={station_id} cycle={cycle + 1}")
                last_write_at = time.monotonic()
    except (RuntimeError, ValueError) as exc:
        print(f"[FAIL] telemetry simulation: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
